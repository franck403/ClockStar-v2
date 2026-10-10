"""BLE tools extension -- lives in Settings as "BLE tools".

Two tools in one page:
  Scan devices  lists nearby BLE devices with a signal bar.
  Control mode  a clock screen where UP opens a command list; SEL sends the
                chosen command over the BLE UART to whatever is connected
                (PC / website via Web Bluetooth).

Both need the radio to themselves, so while a phone is connected a
"disconnect first" screen is shown, then the tool starts on its own as soon
as the phone link drops.
"""

import time
import gc

SCAN_DURATION_MS = 6000
CMD_FLASH_MS = 1200
RSSI_MIN = -100
RSSI_MAX = -40

# Commands sent from control mode (edit this list to add your own).
COMMANDS = ("KILLL", "solve", "scramble", "move1", "move2", "move3", "Rotate")

OPTIONS = ("Scan devices", "Control mode")

# modes
M_MENU = 0
M_BLOCKED = 1
M_SCAN = 2
M_CONTROL = 3
M_PICKER = 4

_mode = M_MENU
_menu_idx = 0
_wants_control = False

_scan_results = []
_scan_done = False
_scan_started = 0
_scan_idx = 0

_last_cmd = ""
_last_cmd_at = 0
_picker_idx = 0


def _rssi_frac(rssi):
    f = (rssi - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)
    return 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)


def register(api):
    ctx = api.ctx
    link = ctx.link
    d = ctx.display
    C = ctx.Color

    # ------------------------------------------------------------- helpers
    def _set_mode(m):
        global _mode
        _mode = m
        ctx.mark_dirty()

    def _on_scan_result(results):
        global _scan_results
        _scan_results = results
        ctx.mark_dirty()

    def _on_scan_done(results):
        global _scan_results, _scan_done
        _scan_results = results
        _scan_done = True
        ctx.mark_dirty()
        gc.collect()

    def _start_scan():
        global _scan_results, _scan_done, _scan_started, _scan_idx
        _scan_results = []
        _scan_done = False
        _scan_idx = 0
        _scan_started = time.ticks_ms()
        _set_mode(M_SCAN)
        link.uart.start_scan(duration_ms=SCAN_DURATION_MS,
                             on_result=_on_scan_result,
                             on_done=_on_scan_done)

    def _stop_scan():
        global _scan_results
        try:
            link.uart.stop_scan()
        except Exception as e:
            print("ble_tools stop_scan:", e)
        _scan_results = []
        gc.collect()

    def _go(wants_control):
        global _wants_control
        _wants_control = wants_control
        if ctx.ble_connected():
            _set_mode(M_BLOCKED)
        elif wants_control:
            _set_mode(M_CONTROL)
        else:
            _start_scan()

    def _send(cmd):
        global _last_cmd, _last_cmd_at
        link.uart.send_line(cmd)
        _last_cmd = cmd
        _last_cmd_at = time.ticks_ms()
        ctx.mark_dirty()

    # -------------------------------------------------------------- drawing
    def _draw_menu():
        d.fill(C.Black)
        header_h = ctx.draw_header("BLE TOOLS", badge=False)
        y = header_h + 8
        for i, label in enumerate(OPTIONS):
            if i == _menu_idx:
                d.fill_rect(2, y - 1, ctx.WIDTH - 4, 13, C.White)
                d.text(label, 6, y + 1, C.Black)
            else:
                d.text(label, 6, y + 1, C.White)
            y += 14
        ctx.draw_footer_hint("SEL open BACK exit")

    def _draw_blocked():
        d.fill(C.Black)
        header_h = ctx.draw_header("BLE TOOLS", badge=False)
        y = header_h + 14
        for line in ("Phone is connected.", "Please disconnect", "the phone first."):
            d.text(line, (ctx.WIDTH - len(line) * 8) // 2, y, C.White)
            y += 12
        label = "[SEL] Disconnect"
        d.text(label, (ctx.WIDTH - len(label) * 8) // 2, y + 14, C.White)
        ctx.draw_footer_hint("BACK cancel")

    def _draw_scan():
        d.fill(C.Black)
        count = len(_scan_results)
        title = "SCANNING" if not _scan_done else "FOUND (%d)" % count
        header_h = ctx.draw_header(title, badge=False)
        row_h = 14
        y = header_h + 4
        max_rows = (ctx.HEIGHT - header_h - 4 - 12) // row_h
        if not _scan_results:
            msg = "Scanning..." if not _scan_done else "No devices found"
            d.text(msg, (ctx.WIDTH - len(msg) * 8) // 2, ctx.HEIGHT // 2 - 4, C.White)
        else:
            name_max = (ctx.WIDTH - 8 - 34) // 8
            for i, (label, rssi) in enumerate(_scan_results[:max_rows]):
                selected = _scan_done and i == _scan_idx
                if selected:
                    d.fill_rect(2, y - 1, ctx.WIDTH - 4, row_h - 1, C.White)
                    col = C.Black
                else:
                    col = C.White
                d.text(ctx.truncate(label, name_max), 4, y, col)
                ctx.draw_progress_bar(ctx.WIDTH - 34, y + 1, 28, 6, _rssi_frac(rssi), color=col)
                y += row_h
        if not _scan_done:
            elapsed = time.ticks_diff(time.ticks_ms(), _scan_started)
            left = max(0, (SCAN_DURATION_MS - elapsed) // 1000 + 1)
            ctx.draw_footer_hint("BACK cancel (%ds)" % left)
        else:
            ctx.draw_footer_hint("UP/DN sel BACK exit")

    def _draw_control():
        ctx.draw_background_alternative()
        ctx.draw_connection_badge()
        h, m, _s = ctx.get_local_time()
        t = "{:02d}:{:02d}".format(h, m)
        ty = ctx.HEIGHT // 2 - 16
        ctx.text_2x(t, (ctx.WIDTH - len(t) * 16) // 2, ty, C.White)
        dy = ty + 24
        d.fill_rect((ctx.WIDTH - 40) // 2, dy, 40, 1, C.White)
        year, month, day = ctx.get_local_date()
        date_y = dy + 8
        if year is not None:
            ds = "{:02d}/{:02d}/{:04d}".format(day, month, year)
            d.text(ds, (ctx.WIDTH - len(ds) * 8) // 2, date_y, C.White)
        if _last_cmd and time.ticks_diff(time.ticks_ms(), _last_cmd_at) < CMD_FLASH_MS:
            sent = "Sent: %s" % _last_cmd
            sy = date_y + 14 if year is not None else dy + 8
            d.text(sent, (ctx.WIDTH - len(sent) * 8) // 2, sy, C.White)

    def _draw_picker():
        d.fill(C.Black)
        ctx.draw_background_alternative()
        header_h = ctx.draw_header("SEND COMMAND", badge=False)
        y = header_h + 6
        for i, cmd in enumerate(COMMANDS):
            if i == _picker_idx:
                d.fill_rect(2, y - 2, ctx.WIDTH - 4, 14, C.White)
                d.text(cmd, 6, y + 1, C.Black)
            else:
                d.text(cmd, 6, y + 1, C.White)
            y += 16
        ctx.draw_footer_hint("SEL send BACK")

    def draw():
        if _mode == M_MENU:
            _draw_menu()
        elif _mode == M_BLOCKED:
            _draw_blocked()
        elif _mode == M_SCAN:
            _draw_scan()
        elif _mode == M_CONTROL:
            _draw_control()
        else:
            _draw_picker()

    # -------------------------------------------------------------- buttons
    def on_up():
        global _menu_idx, _scan_idx, _picker_idx
        if _mode == M_MENU:
            _menu_idx = (_menu_idx - 1) % len(OPTIONS)
        elif _mode == M_SCAN and _scan_done and _scan_results:
            _scan_idx = (_scan_idx - 1) % len(_scan_results)
        elif _mode == M_CONTROL:
            _picker_idx = 0
            _set_mode(M_PICKER)
        elif _mode == M_PICKER:
            _picker_idx = (_picker_idx - 1) % len(COMMANDS)

    def on_down():
        global _menu_idx, _scan_idx, _picker_idx
        if _mode == M_MENU:
            _menu_idx = (_menu_idx + 1) % len(OPTIONS)
        elif _mode == M_SCAN and _scan_done and _scan_results:
            _scan_idx = (_scan_idx + 1) % len(_scan_results)
        elif _mode == M_PICKER:
            _picker_idx = (_picker_idx + 1) % len(COMMANDS)

    def on_select():
        if _mode == M_MENU:
            _go(_menu_idx == 1)
        elif _mode == M_BLOCKED:
            link.disconnect()
        elif _mode == M_PICKER:
            _send(COMMANDS[_picker_idx])

    def on_back():
        if _mode == M_MENU:
            return False          # leave to Settings
        if _mode == M_SCAN:
            _stop_scan()
        if _mode == M_PICKER:
            _set_mode(M_CONTROL)
        else:
            _set_mode(M_MENU)

    def tick(now):
        # phone dropped while the "disconnect first" screen is up -> go on
        if _mode == M_BLOCKED and not ctx.ble_connected():
            _go(_wants_control)
            return True
        # clear the "Sent: ..." flash
        if _mode == M_CONTROL and _last_cmd and \
                time.ticks_diff(now, _last_cmd_at) >= CMD_FLASH_MS:
            return True
        return False

    def on_enter():
        global _mode
        _mode = M_MENU

    def on_exit():
        global _mode
        if _mode == M_SCAN:
            _stop_scan()
        _mode = M_MENU

    api.add_screen("BLE tools", draw, on_up=on_up, on_down=on_down,
                   on_select=on_select, on_back=on_back, tick=tick,
                   on_enter=on_enter, on_exit=on_exit,
                   veille_exempt=True, in_settings=True, order=90)
