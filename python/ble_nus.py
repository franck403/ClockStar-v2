import gc
gc.collect()
import bluetooth
from micropython import const
import time

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
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

_ADV_SERVICE_UUID_BYTES = bytes((
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x01, 0x00, 0x40, 0x6e,
))

def _build_adv_payload(name):
    name_bytes = name.encode()
    adv = bytearray()
    adv += bytes((2, 0x01, 0x06))
    adv += bytes((3, 0x19, 0xC0, 0x00))
    adv += bytes((len(_ADV_SERVICE_UUID_BYTES) + 1, 0x07)) + _ADV_SERVICE_UUID_BYTES
    scan_resp = bytearray()
    scan_resp += bytes((len(name_bytes) + 1, 0x09)) + name_bytes
    return bytes(adv), bytes(scan_resp)


class BLEUart:
    def __init__(self, name="Clockstar", on_line=None, on_connect=None, on_disconnect=None,
                 on_bond_status=None):
        gc.collect()
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)

        time.sleep_ms(100)
        
        try:
            self._ble.config(bond=True, mitm=False, io=_IO_CAPABILITY_NO_INPUT_OUTPUT, le_secure=True)
        except (ValueError, OSError):
            pass

        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        self._ble.gatts_set_buffer(self._rx_handle, 256, False)

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

        self._advertise()

    def is_connected(self):
        return len(self._connections) > 0

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        for conn_handle in self._connections:
            self._ble.gatts_notify(conn_handle, self._tx_handle, data)

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
        self._ble.gap_advertise(None)

    def resume_advertising(self, interval_us=20000):
        self._advertise(interval_us)

    def poll_pairing(self):
        return

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            self._rx_buf.clear()
            self._encrypted[conn_handle] = False
            self._connect_time_ms[conn_handle] = time.ticks_ms()

            try:
                self._ble.gattc_exchange_mtu(conn_handle)
            except Exception:
                pass

            if self._on_connect:
                self._on_connect()

        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            self._connections.discard(conn_handle)
            self._encrypted.pop(conn_handle, None)
            self._connect_time_ms.pop(conn_handle, None)
            if self._on_disconnect:
                self._on_disconnect()
            self._advertise()

        elif event == _IRQ_ENCRYPTION_UPDATE:
            conn_handle, encrypted, authenticated, bonded, key_size = data
            self._encrypted[conn_handle] = bool(encrypted)
            if encrypted and bonded:
                self.bonded = True
            if self._on_bond_status:
                self._on_bond_status(bool(encrypted), bool(bonded))

        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self._rx_handle:
                chunk = self._ble.gatts_read(value_handle)
                if chunk:
                    self._rx_buf.extend(chunk)

                    while True:
                        nl = self._rx_buf.find(b"\n")
                        if nl == -1:
                            semicolon = self._rx_buf.find(b";")
                            if semicolon != -1 and len(self._rx_buf) > 64:
                                nl = semicolon
                            else:
                                break

                        line = bytes(self._rx_buf[:nl])
                        del self._rx_buf[:nl + 1]
                        if self._on_line:
                            try:
                                self._on_line(line.decode("utf-8", "ignore"))
                            except Exception:
                                pass

    def _advertise(self, interval_us=20000):
        self._ble.gap_advertise(
            interval_us,
            adv_data=self._adv_payload,
            resp_data=self._resp_payload,
        )