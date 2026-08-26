# phone_link.py
# Implements the Clockstar v2 official-app BLE protocol on top of ble_nus.py.
# Protocol reverse-derived from the public Clockstar-v2-Firmware source
# (main/src/Notifs/Android.cpp, main/src/BLE/UART.h) — this is what the real
# CircuitMess phone app speaks over Nordic UART.
#
# Wire format: '\n'-terminated lines, fields split on ';'. Fields may use a
# length-prefixed form '<len>:<content>' to safely embed ';' or '\n' inside
# a string field (e.g. notification text) -- we only need to *parse* that
# form here, not emit it, since everything we send to the phone is simple.


import time
from ble_nus import BLEUart

PROTOCOL_VERSION = "1"
FIRMWARE_VERSION = "v2.1"  # reported to the app; cosmetic, matches stock fw string

_TRUNCATED_MARKER = "\u2026"  # ellipsis

def pause_advertising():
    BLEUart.pause_advertising()
    
def resume_advertising():
    BLEUart.resume_advertising()


def _split_protocol_msg(line, delim=";"):
    out = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == delim:
            out.append("")
            i += 1
            continue

        num_start = i
        value = 0
        is_number = False
        while i < n and line[i].isdigit():
            is_number = True
            value = value * 10 + int(line[i])
            i += 1

        if is_number and i < n and line[i] == ":":
            i += 1
            end = i + value
            if end > n:
                # Declared length overruns the buffer -- truncated write.
                # Take what we actually got instead of indexing past n.
                out.append(line[i:n])
                i = n
                break
            out.append(line[i:end])
            i = end
            if i < n and line[i] == delim:
                i += 1
        else:
            i = num_start
            start = i
            while i < n and line[i] != delim:
                i += 1
            out.append(line[start:i])
            if i < n and line[i] == delim:
                i += 1

    if line.endswith(delim):
        out.append("")

    return out


def _field(parts, idx, default=""):
    return parts[idx] if len(parts) > idx and parts[idx] != "" else default


class PhoneLink:
    def __init__(self, name="Clockstar", on_time=None, on_notif=None, on_notif_del=None,
                 on_call=None, on_call_stop=None, on_media_state=None, on_media_info=None,
                 on_connect=None, on_disconnect=None, on_bond_status=None):
        """
        All on_* callbacks are optional.
          on_time(unix_ts: int, tz_offset_min: int)
          on_notif(notif: dict)        # {id, title, message, app_id, category, truncated}
          on_notif_del(notif_id: int)
          on_call(call_id: int, name: str, number: str)
          on_call_stop(call_id: int)
          on_media_state(state: str)   # "stopped" | "playing" | "paused"
          on_media_info(info: dict)    # {title, artist, album, app_id}
          on_connect() / on_disconnect()
          on_bond_status(encrypted: bool, bonded: bool)
        """
        self._on_time = on_time
        self._on_notif = on_notif
        self._on_notif_del = on_notif_del
        self._on_call = on_call
        self._on_call_stop = on_call_stop
        self._on_media_state = on_media_state
        self._on_media_info = on_media_info
        self._user_on_connect = on_connect
        self._user_on_disconnect = on_disconnect
        self._user_on_bond_status = on_bond_status

        self._handshaken = False
        self.connected = False
        self.find_phone_active = False

        self.uart = BLEUart(
            name=name,
            on_line=self._handle_line,
            on_connect=self._handle_connect,
            on_disconnect=self._handle_disconnect,
            on_bond_status=self._handle_bond_status,
        )

    def poll(self):
        """Call from the main loop; drives bonding follow-up (see ble_nus.py)."""
        self.uart.poll_pairing()

    @property
    def is_bonded(self):
        return self.uart.bonded

    # ---- outgoing commands (watch -> phone) ----

    def notif_pos(self, notif_id):
        if not self._handshaken:
            return
        self.uart.send_line("notifPos;%d" % notif_id)

    def notif_neg(self, notif_id):
        if not self._handshaken:
            return
        self.uart.send_line("notifNeg;%d" % notif_id)

    def call_reject(self, call_id):
        if not self._handshaken:
            return
        self.uart.send_line("callReject;%d" % call_id)

    def notif_list(self):
        if not self._handshaken:
            return
        self.uart.send_line("notifList")

    def find_phone_start(self):
        if not self._handshaken or self.find_phone_active:
            return
        self.uart.send_line("findPhoneStart")
        self.find_phone_active = True

    def find_phone_stop(self):
        if not self._handshaken or not self.find_phone_active:
            return
        self.uart.send_line("findPhoneStop")
        self.find_phone_active = False

    def media_play(self):
        if self._handshaken:
            self.uart.send_line("mediaPlay")

    def media_pause(self):
        if self._handshaken:
            self.uart.send_line("mediaPause")

    def media_next(self):
        if self._handshaken:
            self.uart.send_line("mediaNext")

    def media_prev(self):
        if self._handshaken:
            self.uart.send_line("mediaPrev")

    def disconnect(self):
        """Force-drop the current BLE connection, if any.

        Used for the low-battery kill-switch: cuts the radio link to save
        power once the charge is critically low. Advertising resumes
        automatically afterward (handled in ble_nus.py's disconnect IRQ),
        so a charger or a fresh connect attempt will still work -- this
        just isn't allowed to keep servicing an active link below the
        cutoff.
        """
        self.uart.disconnect()

    # ---- internals ----

    def _handle_connect(self):
        self.connected = True
        self._handshaken = False
        if self._user_on_connect:
            self._user_on_connect()

    def _handle_disconnect(self):
        self.connected = False
        self._handshaken = False
        self.find_phone_active = False
        if self._user_on_disconnect:
            self._user_on_disconnect()

    def _handle_bond_status(self, encrypted, bonded):
        if self._user_on_bond_status:
            self._user_on_bond_status(encrypted, bonded)

    def _handle_line(self, line):
        line = line.strip()
        if not line:
            return

        parts = _split_protocol_msg(line)
        if not parts:
            return
        command = parts[0]

        if command == "hello":
            if len(parts) < 2:
                return
            phone_protocol_version = parts[1]
            # Must reply with our version string or the app treats it as a
            # mismatch and refuses to proceed.
            self.uart.send_line("version;%s;%s" % (PROTOCOL_VERSION, FIRMWARE_VERSION))
            if phone_protocol_version == PROTOCOL_VERSION:
                self._handshaken = True
                # Stock firmware requests these right after connecting.
                self.uart.send_line("time")
                self.uart.send_line("notifList")
            return

        if not self._handshaken:
            return  # ignore everything else until handshake completes

        if command == "time" and len(parts) >= 3:
            try:
                ts = int(parts[1])
                tz_offset = int(parts[2])
            except ValueError:
                return
            if ts == 0:
                return
            if self._on_time:
                self._on_time(ts, tz_offset)

        elif command == "notifAdd" and len(parts) >= 1:
            # A truncated write commonly lands here with far fewer than the
            # full 8 fields, or with the last field cut mid-string. We still
            # want *something* useful on screen rather than a blank/garbled
            # entry, so missing fields get an explicit placeholder instead
            # of silently becoming "".
            was_truncated = len(parts) < 4  # title/message didn't fully arrive
            notif = {
                "id": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                "title": _field(parts, 2, "Notification"),
                "message": _field(parts, 3, _TRUNCATED_MARKER if was_truncated else ""),
                "app_id": _field(parts, 4),
                "sender": _field(parts, 5),
                "category": _field(parts, 6),
                "label_pos": _field(parts, 7),
                "label_neg": _field(parts, 8),
                "truncated": was_truncated,
            }
            if self._on_notif:
                self._on_notif(notif)

        elif command == "notifModify" and len(parts) >= 3:
            notif = {
                "id": int(parts[1]) if parts[1].isdigit() else 0,
                "title": _field(parts, 2, "Notification"),
                "message": _field(parts, 3, _TRUNCATED_MARKER),
                "app_id": _field(parts, 4),
                "sender": _field(parts, 5),
                "category": _field(parts, 6),
                "truncated": len(parts) < 4,
            }
            if self._on_notif:
                self._on_notif(notif)

        elif command == "notifDel" and len(parts) >= 2 and parts[1].isdigit():
            if self._on_notif_del:
                self._on_notif_del(int(parts[1]))

        elif command == "callIncoming" and len(parts) >= 4:
            if self._on_call:
                self._on_call(int(parts[1]) if parts[1].isdigit() else 0, parts[2], parts[3])

        elif command == "callIncomingStop" and len(parts) >= 2 and parts[1].isdigit():
            if self._on_call_stop:
                self._on_call_stop(int(parts[1]))

        elif command == "findPhoneStopAck" or command == "findPhoneStopNack":
            self.find_phone_active = False

        elif command == "mediaState" and len(parts) >= 2:
            state_map = {"0": "stopped", "1": "playing", "2": "paused"}
            state = state_map.get(parts[1], "stopped")
            if self._on_media_state:
                self._on_media_state(state)

        elif command == "mediaInfo" and len(parts) >= 2:
            info = {
                "title": _field(parts, 1),
                "artist": _field(parts, 2),
                "album": _field(parts, 3),
                "app_id": _field(parts, 4),
            }
            if self._on_media_info:
                self._on_media_info(info)