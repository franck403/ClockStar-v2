import gc
import bluetooth
from micropython import const
import time

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_MTU_EXCHANGED = const(21)
_IRQ_ENCRYPTION_UPDATE = const(28)

_FLAG_WRITE = const(0x0008)
_FLAG_WRITE_NO_RESPONSE = const(0x0004)
_FLAG_NOTIFY = const(0x0010)
_FLAG_READ = const(0x0002)

_IO_CAPABILITY_NO_INPUT_OUTPUT = const(3)

_UART_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
_UART_RX = (
    bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e"),
    _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE,
)
_UART_TX = (
    bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e"),
    _FLAG_NOTIFY | _FLAG_READ,
)
_UART_SERVICE = (
    _UART_UUID,
    (_UART_TX, _UART_RX),
)

_ADV_SERVICE_UUID_BYTES = bytes(
    (
        0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x01, 0x00, 0x40, 0x6E,
    )
)

def _build_adv_payload(name):
    name_bytes = name.encode()
    adv = bytearray()
    adv += bytes((2, 0x01, 0x06))
    adv += bytes((3, 0x19, 0xC0, 0x00))
    adv += bytes((len(_ADV_SERVICE_UUID_BYTES) + 1, 0x07)) + _ADV_SERVICE_UUID_BYTES
    scan_resp = bytearray()
    scan_resp += bytes((len(name_bytes) + 1, 0x09)) + name_bytes
    return bytes(adv), bytes(scan_resp)


# ---------------------------------------------------------------------------
# BLE SIG "Company Identifier Code" -> short brand label, for scan results
# with no advertised name. Deliberately tiny (kept as a flat dict, not a
# library) -- this is only meant to cover common wearables/phones/beacons,
# not be exhaustive. Values from the public Bluetooth SIG assigned-numbers
# list. Little-endian 2-byte CIC as it appears in AD type 0xFF.
# ---------------------------------------------------------------------------
_COMPANY_ID_BRAND = {
    0x004C: "Apple",
    0x0075: "Samsung",
    0x00E0: "Google",
    0x0087: "Garmin",
    0x0157: "Fitbit",
    0x00D2: "Tile",
    0x0059: "Nordic",
    0x02E5: "Espressif",
    0x000F: "Broadcom",
    0x0006: "Microsoft",
    0x01D7: "Xiaomi",
}


def _guess_brand_from_adv(adv_data):
    """Best-effort brand label from AD type 0xFF (Manufacturer Specific
    Data) inside a raw advertising payload. Returns None if nothing usable
    is found. adv_data is the raw bytes as delivered by the scan IRQ."""
    i = 0
    n = len(adv_data)
    while i + 1 < n:
        length = adv_data[i]
        if length == 0:
            break
        end = i + 1 + length
        if end > n:
            break
        ad_type = adv_data[i + 1]
        if ad_type == 0xFF and length >= 3:
            cic = adv_data[i + 2] | (adv_data[i + 3] << 8)
            brand = _COMPANY_ID_BRAND.get(cic)
            if brand:
                return brand
        i = end
    return None


class BLEUart:
    def __init__(
        self,
        name="Clockstar",
        on_line=None,
        on_connect=None,
        on_disconnect=None,
        on_bond_status=None,
    ):
        gc.collect()
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)
        time.sleep_ms(100)
        try:
            self._ble.config(
                bond=True,
                mitm=False,
                io=_IO_CAPABILITY_NO_INPUT_OUTPUT,
                le_secure=True,
                mtu=300,
            )
        except (ValueError, OSError):
            pass

        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._ble.gatts_set_buffer(self._rx_handle, 1024, True)

        self._connections = set()
        self._rx_buf = bytearray()
        self._name = name
        self._adv_payload, self._resp_payload = _build_adv_payload(name)

        self._on_line = on_line
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_bond_status = on_bond_status

        self._encrypted = {}
        self._connect_time_ms = {}
        self.bonded = False

        self._pending_connect = False
        self._pending_disconnect = False
        self._pending_readvertise = False
        self._pending_bond_status = None
        self._pending_lines = []

        # -- scan state --
        # Kept intentionally small: a dict keyed by addr (as bytes), capped
        # at _SCAN_MAX_RESULTS entries, storing only what the UI needs
        # (name-or-brand string + latest rssi). Raw adv payloads are never
        # retained past a single _irq() call -- only the derived label is
        # kept, so heap use doesn't grow with how many packets a nearby
        # beacon spams during the scan window.
        self._scanning = False
        self._scan_results = {}  # addr_bytes -> (label, rssi)
        self._scan_order = []    # addr_bytes, insertion order, capped
        self._on_scan_result = None
        self._on_scan_done = None
        self._pending_scan_updated = False
        self._pending_scan_done = False

        self._advertise()

    _SCAN_MAX_RESULTS = 15

    def is_connected(self):
        return len(self._connections) > 0

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        for conn_handle in self._connections:
            try:
                self._ble.gatts_notify(conn_handle, self._tx_handle, data)
            except Exception:
                pass

    def send_line(self, line):
        if not line.endswith("\n"):
            line += "\n"
        self.write(line)

    def disconnect(self):
        for conn_handle in tuple(self._connections):
            try:
                self._ble.gap_disconnect(conn_handle)
            except Exception:
                pass

    def pause_advertising(self):
        try:
            self._ble.gap_advertise(None)
        except Exception:
            pass

    def resume_advertising(self, interval_us=20000):
        self._advertise(interval_us)

    def poll_pairing(self):
        pass

    # ---- scanning (central role, transient) ----
    # Only meant to be active while the user is looking at a "nearby
    # devices" screen -- not left running. Advertising is paused for the
    # duration (caller is expected to have already refused entry if a
    # phone is connected, so this never fights with an active link).

    def start_scan(self, duration_ms=6000, on_result=None, on_done=None):
        if self._scanning:
            print("DEBUG start_scan: already scanning, ignored")
            return
        self._scan_results = {}
        self._scan_order = []
        self._on_scan_result = on_result
        self._on_scan_done = on_done
        self._scanning = True
        self.pause_advertising()
        try:
            # active=False: skip scan-response round trips, halves radio
            # time per device seen and avoids extra IRQ/alloc churn --
            # we only need the primary adv payload for name/mfg-data.
            self._ble.gap_scan(duration_ms, 30000, 30000, False)
            print("DEBUG start_scan: gap_scan() call succeeded, duration_ms=", duration_ms)
        except Exception as e:
            print("DEBUG start_scan: gap_scan() raised:", e)
            self._scanning = False
            self.resume_advertising()

    def stop_scan(self):
        if not self._scanning:
            return
        try:
            self._ble.gap_scan(None)
        except Exception:
            pass

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            self._rx_buf = bytearray()
            self._encrypted[conn_handle] = False
            self._connect_time_ms[conn_handle] = time.ticks_ms()
            self._pending_connect = True
            try:
                self._ble.gattc_exchange_mtu(conn_handle)
            except Exception:
                pass

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.discard(conn_handle)
            self._encrypted.pop(conn_handle, None)
            self._connect_time_ms.pop(conn_handle, None)
            self._pending_disconnect = True
            self._pending_readvertise = True

        elif event == _IRQ_ENCRYPTION_UPDATE:
            conn_handle, encrypted, authenticated, bonded, key_size = data
            self._encrypted[conn_handle] = bool(encrypted)
            if encrypted and bonded:
                self.bonded = True
            self._pending_bond_status = (bool(encrypted), bool(bonded))

        elif event == _IRQ_MTU_EXCHANGED:
            pass

        elif event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            addr_key = bytes(addr)  # data is only valid during this call

            name = None
            try:
                n = len(adv_data)
                i = 0
                while i + 1 < n:
                    length = adv_data[i]
                    if length == 0:
                        break
                    end = i + 1 + length
                    if end > n:
                        break
                    ad_type = adv_data[i + 1]
                    if ad_type in (0x08, 0x09):  # shortened / complete local name
                        name = bytes(adv_data[i + 2:end]).decode("utf-8", "ignore")
                        break
                    i = end
            except Exception:
                name = None

            if name:
                label = name
            else:
                brand = _guess_brand_from_adv(adv_data)
                label = brand if brand else "Unknown"

            is_new = addr_key not in self._scan_results
            if is_new and len(self._scan_order) >= self._SCAN_MAX_RESULTS:
                pass  # full -- drop new devices, still update ones we have
            elif is_new:
                self._scan_order.append(addr_key)
                self._scan_results[addr_key] = (label, rssi)
                self._pending_scan_updated = True
            else:
                # refresh rssi/label for an existing entry only
                self._scan_results[addr_key] = (label, rssi)
                self._pending_scan_updated = True

        elif event == _IRQ_SCAN_DONE:
            self._scanning = False
            self._pending_scan_done = True

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self._rx_handle:
                while True:
                    try:
                        chunk = self._ble.gatts_read(value_handle)
                    except Exception:
                        chunk = None
                    if not chunk:
                        break
                    print("DEBUG BLE RX t={}: {}".format(time.ticks_ms(), chunk))
                    self._rx_buf.extend(chunk)

                while b"\n" in self._rx_buf:
                    pos = self._rx_buf.index(b"\n")
                    line = bytes(self._rx_buf[:pos])
                    self._rx_buf = self._rx_buf[pos + 1:]
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    if line:
                        self._pending_lines.append(line)

    def _advertise(self, interval_us=20000):
        try:
            self._ble.gap_advertise(
                interval_us,
                adv_data=self._adv_payload,
                resp_data=self._resp_payload,
            )
        except Exception:
            pass

    def poll(self):
        if self._pending_connect:
            self._pending_connect = False
            if self._on_connect:
                try:
                    self._on_connect()
                except Exception:
                    pass

        if self._pending_disconnect:
            self._pending_disconnect = False
            if self._on_disconnect:
                try:
                    self._on_disconnect()
                except Exception:
                    pass

        if self._pending_readvertise:
            self._pending_readvertise = False
            self._advertise()

        if self._pending_bond_status is not None:
            encrypted, bonded = self._pending_bond_status
            self._pending_bond_status = None
            if self._on_bond_status:
                try:
                    self._on_bond_status(encrypted, bonded)
                except Exception:
                    pass

        if self._pending_lines:
            lines = self._pending_lines
            self._pending_lines = []
            for line in lines:
                if self._on_line:
                    try:
                        self._on_line(line.decode("utf-8", "ignore"))
                    except Exception:
                        pass

        if self._pending_scan_updated:
            self._pending_scan_updated = False
            if self._on_scan_result:
                try:
                    self._on_scan_result(self.scan_results())
                except Exception:
                    pass

        if self._pending_scan_done:
            self._pending_scan_done = False
            self.resume_advertising()
            if self._on_scan_done:
                try:
                    self._on_scan_done(self.scan_results())
                except Exception:
                    pass

    def scan_results(self):
        """List of (label, rssi) tuples in discovery order, newest info."""
        return [self._scan_results[a] for a in self._scan_order]
