import time
import json
import sys
import machine
import gc
import esp32

try:
    import sprite
except Exception as e:
    sys.print_exception(e)
    print('sprite failed')
    time.sleep(10)
    machine.reset()
    
from machine import PWM, Pin, freq
from phone_link import PhoneLink
import battery
import pedometer
import render
import Clockstar_v2 as cs

WIDTH = cs.display.width
HEIGHT = cs.display.height

display = cs.display
rtc = cs.rtc
buttons = cs.buttons
piezo = cs.piezo
Color = cs.Display.Color
print(Color)
Buttons = cs.Buttons

BG_SPRITE_PATH = "clock_bg.spr"
HAVE_BG = False
_BG_W = _BG_H = 0
if hasattr(display, "blit"):
    try:
        _BG_W, _BG_H = sprite.peek_size(BG_SPRITE_PATH)
        HAVE_BG = True
    except OSError:
        pass


 
def draw_background():
    _t0 = time.ticks_ms()
    display.fill(Color.Black)
    _t1 = time.ticks_ms()
    if HAVE_BG:
        bg_x = (WIDTH - _BG_W) // 2
        bg_y = (HEIGHT - _BG_H) // 2
        sprite.blit_file(display, BG_SPRITE_PATH, bg_x, bg_y)
    _t2 = time.ticks_ms()
    print("draw_background: fill=%dms blit=%dms" % (
        time.ticks_diff(_t1, _t0), time.ticks_diff(_t2, _t1)))


# ---------------------------------------------------------------------------
# Alternate background (BLE control mode)
# ---------------------------------------------------------------------------
# Control mode replaces the normal clock face while a command session is
# active over BLE, so it gets its own background instead of clock_bg.spr:
# control_bg.spr, loaded with the exact same peek_size/HAVE_*/blit_file
# pattern as BG_SPRITE_PATH/clock_bg.spr above, so control mode is
# visually distinct from the regular clock screen at a glance. Falls
# back to a flat fill + thin border if control_bg.spr is missing
# on-device (mirrors the HAVE_BG guard pattern above).
ALT_BG_COLOR = Color.Black
ALT_BG_BORDER_COLOR = Color.White
ALT_BG_BORDER_MARGIN = 3

CONTROL_BG_SPRITE_PATH = "control_bg.spr"
HAVE_CONTROL_BG = False
_CONTROL_BG_W = _CONTROL_BG_H = 0
if hasattr(display, "blit"):
    try:
        _CONTROL_BG_W, _CONTROL_BG_H = sprite.peek_size(CONTROL_BG_SPRITE_PATH)
        HAVE_CONTROL_BG = True
    except OSError:
        pass


def draw_background_alternative():
    _t0 = time.ticks_ms()
    display.fill(ALT_BG_COLOR)
    if HAVE_CONTROL_BG:
        bg_x = (WIDTH - _CONTROL_BG_W) // 2
        bg_y = (HEIGHT - _CONTROL_BG_H) // 2
        sprite.blit_file(display, CONTROL_BG_SPRITE_PATH, bg_x, bg_y)
    elif hasattr(display, "rect"):
        m = ALT_BG_BORDER_MARGIN
        display.rect(m, m, WIDTH - 2 * m, HEIGHT - 2 * m, ALT_BG_BORDER_COLOR)
    _t1 = time.ticks_ms()
    print("draw_background_alternative: fill+bg=%dms" % time.ticks_diff(_t1, _t0))


BATT_ICONS = sprite.IconSet(
    {
        battery.LEVEL_FULL: "/icons/batt_full.spr",
        battery.LEVEL_HALF: "/icons/batt_half.spr",
        battery.LEVEL_LOW: "/icons/batt_low.spr",
        battery.LEVEL_CRITICAL: "/icons/batt_critical.spr",
    },
    overlay="/icons/batt_charging.spr",
)

PHONE_ICONS = sprite.IconSet(
    {
        "pair": "/icons/phone_connected.spr",
    }
)

HAVE_BATT_ICONS = False
if hasattr(display, "blit"):
    try:
        for _p in BATT_ICONS.frames.values():
            sprite.peek_size(_p)
        HAVE_BATT_ICONS = True
    except OSError:
        pass

SLIDER_SPRITE_PATH = "/icons/settings_slider.spr"
HAVE_SLIDER_SPRITE = False
_SLIDER_W = _SLIDER_H = 0
if hasattr(display, "blit"):
    try:
        _SLIDER_W, _SLIDER_H = sprite.peek_size(SLIDER_SPRITE_PATH)
        HAVE_SLIDER_SPRITE = True
    except OSError:
        pass

SLIDER_TRACK_SPRITE_PATH = "/icons/settings_slider_track.spr"
HAVE_SLIDER_TRACK_SPRITE = False
_SLIDER_TRACK_W = _SLIDER_TRACK_H = 0
if hasattr(display, "blit"):
    try:
        _SLIDER_TRACK_W, _SLIDER_TRACK_H = sprite.peek_size(SLIDER_TRACK_SPRITE_PATH)
        HAVE_SLIDER_TRACK_SPRITE = True
    except OSError:
        pass


# ---------------------------------------------------------------------------
# RTC sync lock
# ---------------------------------------------------------------------------
# The BM8563 RTC powers on (or resets on brownout/battery-dead) at
# 1900-01-01 -- a real "no time sync yet" state, not a valid date. Any
# year below this is treated as "unsynced" so a genuine future date isn't
# accidentally flagged.
RTC_SYNC_MIN_YEAR = 2020

_synced = False


def set_rtc(unix_ts, tz_offset_min):
    print('?')
    global _synced
    local_ts = unix_ts + tz_offset_min * 60

    EPOCH_DIFF_1970_TO_2000 = 946684800
    tm = time.gmtime(local_ts - EPOCH_DIFF_1970_TO_2000)

    print("SET_RTC DEBUG: unix_ts=", unix_ts, "tz_offset_min=", tz_offset_min,
          "local_ts=", local_ts, "gmtime tm=", tm)

    t = cs.rtc.time
    t.year = tm[0]
    t.month = tm[1]
    t.day = tm[2]
    t.hours = tm[3]
    t.minutes = tm[4]
    t.seconds = tm[5]
    rtc.set_time(t)

    print("SET_RTC DEBUG: wrote year=", t.year, "month=", t.month, "day=", t.day)

    was_synced = _synced
    _synced = True
    if not was_synced:
        _on_sync_acquired()


def get_local_time():
    return rtc.get_hours(), rtc.get_minutes(), rtc.get_seconds()


def get_local_date():
    try:
        t = rtc.time
        year, month, day = t.year, t.month, t.day
    except AttributeError:
        try:
            year, month, day = rtc.get_year(), rtc.get_month(), rtc.get_day()
        except AttributeError:
            return None, None, None

    if year is not None and year < 100:
        year += 2000

    return year, month, day


def _check_rtc_synced_from_hw():
    """Read the RTC directly to decide sync state at boot, independent of
    the in-RAM _synced flag (which starts False every boot regardless of
    whether the RTC chip itself already holds a real time from before a
    reset)."""
    year, _month, _day = get_local_date()
    if year is None:
        return False
    return year >= RTC_SYNC_MIN_YEAR


_ble_connected = False
_ble_bonded = False
_ble_encrypted = False


def on_ble_connect():
    global _ble_connected
    _ble_connected = True
    _mark_dirty()
    _refresh_idle_freq()
    _enforce_battery_ble_cutoff()


def on_ble_disconnect():
    global _ble_connected, _ble_encrypted
    _ble_connected = False
    _ble_encrypted = False
    _mark_dirty()
    _refresh_idle_freq()


def on_ble_bond_status(encrypted, bonded):
    global _ble_encrypted, _ble_bonded
    _ble_encrypted = encrypted
    if bonded:
        _ble_bonded = True
    _mark_dirty()


_notifications = []
_selected_notif_idx = 0
_MAX_NOTIFS = 20


def _clamp_selected_idx():
    global _selected_notif_idx
    if not _notifications:
        _selected_notif_idx = 0
    elif _selected_notif_idx >= len(_notifications):
        _selected_notif_idx = len(_notifications) - 1
    elif _selected_notif_idx < 0:
        _selected_notif_idx = 0


def on_notif(notif):
    global _notifications, _selected_notif_idx

    title = (notif.get("title") or "").strip()
    message = (notif.get("message") or "").strip()
    if not message and (not title or title.lower() == "notification"):
        return

    notif_id = notif.get("id", 0)
    if notif_id:
        for i, existing in enumerate(_notifications):
            if existing.get("id") == notif_id:
                _notifications[i] = notif
                _mark_dirty()
                return

    _notifications.insert(0, notif)
    if len(_notifications) > _MAX_NOTIFS:
        _notifications.pop()

    _selected_notif_idx += 1 if _screen == SCREEN_NOTIF_LIST and _notifications else 0
    _clamp_selected_idx()

    _mark_dirty()


def on_notif_del(notif_id):
    global _notif_nav_mode
    for i, existing in enumerate(_notifications):
        if existing.get("id") == notif_id:
            _notifications.pop(i)
            break
    _clamp_selected_idx()
    if not _notifications:
        _notif_nav_mode = False
    _mark_dirty()


_media_state = "stopped"
_media_title = ""
_media_artist = ""


def on_media_state(state):
    global _media_state
    _media_state = state
    _mark_dirty()


def on_media_info(info):
    global _media_title, _media_artist
    _media_title = info.get("title", "")
    _media_artist = info.get("artist", "")
    _mark_dirty()

gc.collect()

link = PhoneLink(
    name="Clockstar",
    on_time=set_rtc,
    on_notif=on_notif,
    on_notif_del=on_notif_del,
    on_connect=on_ble_connect,
    on_disconnect=on_ble_disconnect,
    on_media_state=on_media_state,
    on_media_info=on_media_info,
    on_bond_status=on_ble_bond_status,
)

gc.collect()
cs.begin()
gc.collect()
print("after cs.begin():", esp32.idf_heap_info(esp32.HEAP_DATA))
gc.collect()


SCREEN_SYNC_LOCK = -1
SCREEN_CLOCK = 0
SCREEN_MEDIA = 1
SCREEN_PEDOMETER = 2
SCREEN_NOTIF_LIST = 3
SCREEN_SETTINGS = 4
SCREEN_BLE_SCAN = 5
SCREEN_BLE_CONTROL = 6
SCREEN_BLE_BLOCKED = 7
SCREEN_BLE_CMD_PICKER = 8
_NUM_SCREENS = 4 

_screen = SCREEN_CLOCK
_prev_screen = SCREEN_CLOCK  
_dirty = True
_notif_nav_mode = False
_media_control_mode = False
# _BLE_NAV gates the BLE command picker's own UP/DOWN cursor movement.
# It's True exactly while SCREEN_BLE_CMD_PICKER is the active screen and
# False otherwise -- set in _enter_ble_cmd_picker()/_exit_ble_cmd_picker()
# below, mirroring how _notif_nav_mode/_media_control_mode gate their own
# screens' UP/DOWN behaviour elsewhere in this file.
_BLE_NAV = False


def _mark_dirty():
    global _dirty
    _dirty = True


# ---------------------------------------------------------------------------
# Delayed sync -> clock screen transition
# ---------------------------------------------------------------------------
SYNC_TRANSITION_DELAY_MS = 400
_sync_transition_pending_at = None


def _on_sync_acquired():
    """Called once, the moment a real time sync lands (either via BLE
    set_rtc, or found already valid in the RTC chip at boot). Does NOT
    switch screens immediately -- see SYNC_TRANSITION_DELAY_MS note above.
    Arms the delayed transition instead, which main_loop() carries out."""
    global _sync_transition_pending_at
    if _screen == SCREEN_SYNC_LOCK:
        _sync_transition_pending_at = time.ticks_ms()
    _mark_dirty()


SETTINGS_HOLD_MS = 1400
SLIDE_BOX_W = _SLIDER_W if HAVE_SLIDER_SPRITE else 10
SLIDE_BOX_H = _SLIDER_H if HAVE_SLIDER_SPRITE else 10
SLIDE_MARGIN = 4
SLIDE_TRAVEL = WIDTH - (2 * SLIDE_MARGIN) - SLIDE_BOX_W

_select_held = False
_select_hold_start = 0
_select_press_woke_dark_screen = False
_slide_progress = 0.0 
_slide_active = False
_settings_just_opened_at = 0 


def _slide_x():
    return SLIDE_MARGIN + int(SLIDE_TRAVEL * _slide_progress)


def _slide_y():
    return HEIGHT - SLIDE_MARGIN - SLIDE_BOX_H


def _open_settings():
    global _screen, _prev_screen, _slide_active, _slide_progress, _settings_just_opened_at
    if _screen != SCREEN_SETTINGS:
        _prev_screen = _screen
    _screen = SCREEN_SETTINGS
    _settings_reset_nav()
    _slide_active = False
    _slide_progress = 0.0
    _settings_just_opened_at = time.ticks_ms()
    _mark_dirty()


def _close_settings():
    global _screen
    _screen = _prev_screen
    _mark_dirty()


# ---------------------------------------------------------------------------
# Sync lock screen
# ---------------------------------------------------------------------------

_SYNC_DOT_FRAMES = ("", ".", "..", "...")
_sync_anim_idx = 0
_sync_screen_battery_drawn = False
SYNC_ANIM_INTERVAL_MS = 500


def draw_sync_lock_screen(full_redraw=True):
    """Draw the lock screen.

    full_redraw=False only repaints the small animated status line, not
    the whole screen -- the battery icon draw (blit_file) allocates and
    frees several buffers per call, and redrawing it every 500ms forever
    while someone sits unpaired on this screen was fragmenting the heap
    badly enough to eventually starve BLE controller init on reboot.
    """
    global _sync_screen_battery_drawn

    status_y = HEIGHT - 24

    if full_redraw:
        display.fill(Color.Black)

        title = "SYNC NEEDED"
        display.text(title, (WIDTH - len(title) * 8) // 2, 14, Color.White)

        divider_w = 60
        display.fill_rect((WIDTH - divider_w) // 2, 26, divider_w, 1, Color.White)

        msg_lines = ["Open the", "CircuitMess app", "and connect via", "Bluetooth to", "set the time."]
        y = 40
        for line in msg_lines:
            display.text(line, (WIDTH - len(line) * 8) // 2, y, Color.White)
            y += 12

        draw_battery_icon(WIDTH - 4 - 14 - 2, 3, invert=False)
        _sync_screen_battery_drawn = True
    else:
        display.fill_rect(0, status_y, WIDTH, 10, Color.Black)

    if _ble_connected:
        status = "Connected" + _SYNC_DOT_FRAMES[_sync_anim_idx]
    else:
        status = "Waiting" + _SYNC_DOT_FRAMES[_sync_anim_idx]
    display.text(status, (WIDTH - len(status) * 8) // 2, status_y, Color.White)


def _sync_lock_tick_anim():
    global _sync_anim_idx
    _sync_anim_idx = (_sync_anim_idx + 1) % len(_SYNC_DOT_FRAMES)
    _mark_dirty()


# ---------------------------------------------------------------------------
# Settings screen
# ---------------------------------------------------------------------------

SETTINGS_ROW_VEILLE = 0
SETTINGS_ROW_TILT_WAKE = 1
SETTINGS_ROW_GYRO = 2
SETTINGS_ROW_BATTERY = 3
SETTINGS_ROW_BLE_TOOLS = 4
_SETTINGS_NUM_ROWS = 5

_settings_selected_row = 0
_settings_in_row = False

# BLE tools is a small sub-page with its own 2-entry cursor: Scan devices
# and Control mode, navigated the same way as every other in-row screen
# (UP/DOWN moves, SEL commits).
_BLE_TOOLS_OPT_SCAN = 0
_BLE_TOOLS_OPT_CONTROL = 1
_BLE_TOOLS_OPTIONS = ("Scan devices", "Control mode")
_ble_tools_selected_idx = 0

# Veille (idle backlight timeout) options, in ms
VEILLE_OPTIONS_MS = [5000, 10000, 20000, 30000, 60000]
_veille_idx = 2 

_tilt_to_wake_enabled = True

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------
SETTINGS_PATH = "settings.json"


def _load_settings():
    global _veille_idx, _tilt_to_wake_enabled
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return

    idx = data.get("veille_idx")
    if isinstance(idx, int) and 0 <= idx < len(VEILLE_OPTIONS_MS):
        _veille_idx = idx

    tilt = data.get("tilt_to_wake_enabled")
    if isinstance(tilt, bool):
        _tilt_to_wake_enabled = tilt


def _save_settings():
    try:
        with open(SETTINGS_PATH, "w") as f:
            json.dump({
                "veille_idx": _veille_idx,
                "tilt_to_wake_enabled": _tilt_to_wake_enabled,
            }, f)
    except OSError as e:
        print("settings save error:", e)


def _settings_reset_nav():
    global _settings_selected_row, _settings_in_row
    _settings_selected_row = 0
    _settings_in_row = False


def _settings_row_label(row):
    if row == SETTINGS_ROW_VEILLE:
        secs = VEILLE_OPTIONS_MS[_veille_idx] // 1000
        return "Veille: %ds" % secs
    elif row == SETTINGS_ROW_TILT_WAKE:
        return "Tilt wake: %s" % ("On" if _tilt_to_wake_enabled else "Off")
    elif row == SETTINGS_ROW_GYRO:
        return "Debug gyro"
    elif row == SETTINGS_ROW_BATTERY:
        return "Batterie"
    elif row == SETTINGS_ROW_BLE_TOOLS:
        return "BLE tools"
    return "?"


def draw_settings_screen():
    display.fill(Color.Black)
    header_h = draw_header("SETTINGS", badge=False)

    if not _settings_in_row:
        row_h = 16
        y = header_h + 6
        for row in range(_SETTINGS_NUM_ROWS):
            if row == _settings_selected_row:
                display.fill_rect(2, y - 2, WIDTH - 4, row_h - 2, Color.White)
                display.text(_settings_row_label(row), 6, y + 1, Color.Black)
            else:
                display.text(_settings_row_label(row), 6, y + 1, Color.White)
            y += row_h
        draw_footer_hint("SEL open BACK exit")
        return

    body_y = header_h + 8
    if _settings_selected_row == SETTINGS_ROW_VEILLE:
        display.text("Veille (idle)", 4, body_y, Color.White)
        secs = VEILLE_OPTIONS_MS[_veille_idx] // 1000
        _text_2x("%ds" % secs, (WIDTH - len(str(secs) + "s") * 16) // 2, HEIGHT // 2 - 8, Color.White)
        dot_w = 8
        total_w = len(VEILLE_OPTIONS_MS) * dot_w
        dots_x = (WIDTH - total_w) // 2
        dots_y = HEIGHT // 2 + 14
        for i in range(len(VEILLE_OPTIONS_MS)):
            cx = dots_x + i * dot_w + dot_w // 2
            if i == _veille_idx:
                display.fill_rect(cx - 2, dots_y - 2, 4, 4, Color.White)
            else:
                display.rect(cx - 1, dots_y - 1, 2, 2, Color.White)
        display.text("UP/DN change", 4, HEIGHT - 24, Color.White)
        draw_footer_hint("BACK exit")

    elif _settings_selected_row == SETTINGS_ROW_TILT_WAKE:
        display.text("Tilt to wake", 4, body_y, Color.White)
        state_str = "ON" if _tilt_to_wake_enabled else "OFF"
        _text_2x(state_str, (WIDTH - len(state_str) * 16) // 2, HEIGHT // 2 - 8, Color.White)
        display.text("SEL toggle", 4, HEIGHT - 24, Color.White)
        draw_footer_hint("BACK exit")

    elif _settings_selected_row == SETTINGS_ROW_GYRO:
        display.text("GYRO DEBUG", 4, body_y, Color.White)
        try:
            gx, gy, gz = cs.imu.get_gyro()
            row_y = body_y + 16
            for label, val in (("x", gx), ("y", gy), ("z", gz)):
                display.text("%s:" % label, 4, row_y, Color.White)
                display.text("%+.2f" % val, 24, row_y, Color.White)
                row_y += 12
        except Exception:
            display.text("gyro read error", 4, body_y + 16, Color.White)
        draw_footer_hint("BACK exit")

    elif _settings_selected_row == SETTINGS_ROW_BATTERY:
        display.text("BATTERY INFO", 4, body_y, Color.White)
        try:
            voltage = battery.get_battery_voltage()
            percentage = battery.get_battery_percentage()
            capacity = battery.get_remaining_capacity_mah()
            row_y = body_y + 16
            display.text("%.3f V" % voltage, 4, row_y, Color.White)
            row_y += 12
            display.text("%d %%" % percentage, 4, row_y, Color.White)
            row_y += 12
            draw_progress_bar(4, row_y, WIDTH - 8, 8, percentage / 100.0)
            row_y += 14
            display.text("%d mAh" % capacity, 4, row_y, Color.White)
            row_y += 12
            display.text("chg: %s" % ("yes" if _charging else "no"), 4, row_y, Color.White)
            row_y += 12
            if _charge_pin is not None:
                try:
                    raw_pin_val = _charge_pin.value()
                    display.text("pin raw: %d" % raw_pin_val, 4, row_y, Color.White)
                except Exception:
                    display.text("pin read err", 4, row_y, Color.White)
            else:
                display.text("pin: not init", 4, row_y, Color.White)
        except Exception:
            display.text("battery read error", 4, body_y + 16, Color.White)
        draw_footer_hint("BACK exit")

    elif _settings_selected_row == SETTINGS_ROW_BLE_TOOLS:
        display.text("BLE TOOLS", 4, body_y, Color.White)
        opt_y = body_y + 16
        for i, opt_label in enumerate(_BLE_TOOLS_OPTIONS):
            if i == _ble_tools_selected_idx:
                display.fill_rect(2, opt_y - 1, WIDTH - 4, 13, Color.White)
                display.text(opt_label, 6, opt_y + 1, Color.Black)
            else:
                display.text(opt_label, 6, opt_y + 1, Color.White)
            opt_y += 14
        draw_footer_hint("SEL open BACK exit")


def _settings_on_up():
    global _settings_selected_row, _veille_idx, _ble_tools_selected_idx
    if not _settings_in_row:
        _settings_selected_row = (_settings_selected_row - 1) % _SETTINGS_NUM_ROWS
        _mark_dirty()
    elif _settings_selected_row == SETTINGS_ROW_VEILLE:
        _veille_idx = (_veille_idx + 1) % len(VEILLE_OPTIONS_MS)
        _save_settings()
        _mark_dirty()
    elif _settings_selected_row == SETTINGS_ROW_BLE_TOOLS:
        _ble_tools_selected_idx = (_ble_tools_selected_idx - 1) % len(_BLE_TOOLS_OPTIONS)
        _mark_dirty()


def _settings_on_down():
    global _settings_selected_row, _veille_idx, _ble_tools_selected_idx
    if not _settings_in_row:
        _settings_selected_row = (_settings_selected_row + 1) % _SETTINGS_NUM_ROWS
        _mark_dirty()
    elif _settings_selected_row == SETTINGS_ROW_VEILLE:
        _veille_idx = (_veille_idx - 1) % len(VEILLE_OPTIONS_MS)
        _save_settings()
        _mark_dirty()
    elif _settings_selected_row == SETTINGS_ROW_BLE_TOOLS:
        _ble_tools_selected_idx = (_ble_tools_selected_idx + 1) % len(_BLE_TOOLS_OPTIONS)
        _mark_dirty()


def _settings_on_select():
    global _settings_in_row, _tilt_to_wake_enabled
    print("DEBUG settings_on_select: in_row=", _settings_in_row,
          "row=", _settings_selected_row, "ble_idx=", _ble_tools_selected_idx)
    if not _settings_in_row:
        _settings_in_row = True
        _mark_dirty()
        return
    if _settings_selected_row == SETTINGS_ROW_TILT_WAKE:
        _tilt_to_wake_enabled = not _tilt_to_wake_enabled
        _save_settings()
        _mark_dirty()
    elif _settings_selected_row == SETTINGS_ROW_BLE_TOOLS:
        if _ble_tools_selected_idx == _BLE_TOOLS_OPT_SCAN:
            print("DEBUG -> _enter_ble_scan()")
            _enter_ble_scan()
        else:
            print("DEBUG -> _enter_ble_control()")
            _enter_ble_control()

def _settings_on_back():
    global _settings_in_row
    if _settings_in_row:
        _settings_in_row = False
        _mark_dirty()
    else:
        _close_settings()


# ---------------------------------------------------------------------------
# BLE tools: scan screen + control-mode screen
# ---------------------------------------------------------------------------
# Both entry points are gated behind _ble_connected: the radio is a single
# shared instance owned by `link` (PhoneLink -> ble_nus.BLEUart), so it
# cannot scan (central role) while a phone is actively connected
# (peripheral role) without tearing down that link. Rather than silently
# disconnecting the phone, we show a blocking screen with an explicit
# "disconnect first" action -- see SCREEN_BLE_BLOCKED. Control mode is
# gated the SAME way even though it only uses the existing peripheral
# link (not central/scan role) -- while a phone is connected, that link
# is busy servicing the phone protocol (time sync, notifs, media), and
# sending raw control-mode strings down the same NUS TX/RX pair would
# collide with/corrupt that traffic. So control mode also requires the
# phone to be disconnected first, exactly like scan.

BLE_SCAN_DURATION_MS = 6000

_ble_scan_results = []      # list of (label, rssi), refreshed via callback
_ble_scan_done = False
_ble_scan_started_at = 0
_ble_scan_selected_idx = 0

# Commands sent from control mode, over the existing UART TX
# characteristic to whatever is connected (PC/website via Web Bluetooth).
# No protocol changes needed -- send_line() already does the right thing.
BLE_CMD_SOLVE = "solve"
BLE_CMD_KILL = "KILLL"
BLE_CMD_SCRAMBLE = "scramble"
BLE_CMD_MOVE1 = "move1"
BLE_CMD_MOVE2 = "move2"
BLE_CMD_MOVE3 = "move3"
BLE_CMD_MOVE4 = "Middle"
_BLE_CMD_LIST = (BLE_CMD_KILL, BLE_CMD_SOLVE, BLE_CMD_SCRAMBLE, BLE_CMD_MOVE1, BLE_CMD_MOVE2, BLE_CMD_MOVE3,BLE_CMD_MOVE4)

_ble_control_last_cmd = ""
_ble_control_last_cmd_at = 0
BLE_CONTROL_CMD_FLASH_MS = 1200

_ble_cmd_picker_selected_idx = 0


# _ble_return_screen tracks where BACK should take you out of any of the
# three BLE screens (scan / control / blocked). This is DELIBERATELY kept
# separate from _prev_screen (which belongs to _open_settings/
# _close_settings). Both entry points below set it to SCREEN_SETTINGS --
# their only entry path -- and every exit reads from it, never from
# _prev_screen.
_ble_return_screen = SCREEN_SETTINGS
# Which BLE screen to proceed into once a blocking phone connection drops
# -- set right before showing SCREEN_BLE_BLOCKED so _ble_blocked_recheck()
# knows whether to resume into scan or control.
_ble_blocked_wants_control = False


def _ble_scan_on_result(results):
    global _ble_scan_results
    _ble_scan_results = results
    _mark_dirty()


def _ble_scan_on_done(results):
    global _ble_scan_results, _ble_scan_done
    _ble_scan_results = results
    _ble_scan_done = True
    _mark_dirty()
    gc.collect()


def _enter_ble_scan():
    global _screen, _ble_return_screen, _ble_blocked_wants_control
    print("DEBUG _enter_ble_scan called, ble_connected=", _ble_connected)
    _ble_return_screen = SCREEN_SETTINGS
    if _ble_connected:
        _ble_blocked_wants_control = False
        _screen = SCREEN_BLE_BLOCKED
        _mark_dirty()
        return
    _start_ble_scan()


def _start_ble_scan():
    global _screen, _ble_scan_results, _ble_scan_done, _ble_scan_started_at, _ble_scan_selected_idx
    print("DEBUG _start_ble_scan: entering SCREEN_BLE_SCAN, was screen=", _screen)
    _screen = SCREEN_BLE_SCAN
    _ble_scan_results = []
    _ble_scan_done = False
    _ble_scan_selected_idx = 0
    _ble_scan_started_at = time.ticks_ms()
    link.uart.start_scan(
        duration_ms=BLE_SCAN_DURATION_MS,
        on_result=_ble_scan_on_result,
        on_done=_ble_scan_on_done,
    )
    print("DEBUG _start_ble_scan: now screen=", _screen)
    _mark_dirty()


def _exit_ble_scan():
    global _screen, _ble_scan_results
    link.uart.stop_scan()
    _ble_scan_results = []
    _screen = _ble_return_screen
    _mark_dirty()
    gc.collect()


def _enter_ble_control():
    global _screen, _ble_return_screen, _ble_blocked_wants_control
    print("DEBUG _enter_ble_control called, ble_connected=", _ble_connected)
    _ble_return_screen = SCREEN_SETTINGS
    if _ble_connected:
        _ble_blocked_wants_control = True
        _screen = SCREEN_BLE_BLOCKED
        _mark_dirty()
        return
    _screen = SCREEN_BLE_CONTROL
    print("DEBUG _enter_ble_control: now screen=", _screen)
    _mark_dirty()


def _exit_ble_control():
    global _screen
    _screen = _ble_return_screen
    _mark_dirty()


def _enter_ble_cmd_picker():
    # Entered from SCREEN_BLE_CONTROL via UP (see _on_up_press). Sets
    # _BLE_NAV True so this sub-screen's own UP/DOWN handlers
    # (_ble_cmd_picker_on_up/_down) take over the cursor -- mirrors
    # _notif_nav_mode/_media_control_mode gating their screens elsewhere.
    global _screen, _ble_cmd_picker_selected_idx, _BLE_NAV
    _ble_cmd_picker_selected_idx = 0
    _BLE_NAV = True
    _screen = SCREEN_BLE_CMD_PICKER
    _mark_dirty()


def _exit_ble_cmd_picker():
    global _screen, _BLE_NAV
    _BLE_NAV = False
    _screen = SCREEN_BLE_CONTROL
    _mark_dirty()


def _ble_cmd_picker_on_up():
    global _ble_cmd_picker_selected_idx
    _ble_cmd_picker_selected_idx = (_ble_cmd_picker_selected_idx - 1) % len(_BLE_CMD_LIST)
    _mark_dirty()


def _ble_cmd_picker_on_down():
    global _ble_cmd_picker_selected_idx
    _ble_cmd_picker_selected_idx = (_ble_cmd_picker_selected_idx + 1) % len(_BLE_CMD_LIST)
    _mark_dirty()


def _ble_cmd_picker_confirm():
    cmd = _BLE_CMD_LIST[_ble_cmd_picker_selected_idx]
    _ble_control_send(cmd)


def _ble_control_send(cmd):
    global _ble_control_last_cmd, _ble_control_last_cmd_at
    link.uart.send_line(cmd)
    _ble_control_last_cmd = cmd
    _ble_control_last_cmd_at = time.ticks_ms()
    _mark_dirty()


def _ble_blocked_disconnect():
    link.disconnect()
    # on_ble_disconnect() fires from the BLE IRQ->poll path shortly after
    # this and flips _ble_connected on its own, but we don't want the user
    # stuck staring at "please disconnect" until they press something
    # again -- main_loop() polls _ble_blocked_recheck() each tick while
    # this screen is up so it moves on automatically once the phone link
    # actually drops.
    _mark_dirty()


def _ble_blocked_recheck():
    """Called every main_loop() tick while SCREEN_BLE_BLOCKED is showing.
    Once the phone has actually disconnected, proceed into whichever BLE
    screen the user originally asked for."""
    if _screen != SCREEN_BLE_BLOCKED or _ble_connected:
        return
    if _ble_blocked_wants_control:
        _enter_ble_control()
    else:
        _enter_ble_scan()


def draw_ble_blocked_screen():
    display.fill(Color.Black)
    header_h = draw_header("BLE TOOLS", badge=False)

    lines = ["Phone is connected.", "Please disconnect", "the phone first."]
    y = header_h + 14
    for line in lines:
        display.text(line, (WIDTH - len(line) * 8) // 2, y, Color.White)
        y += 12

    btn_label = "[SEL] Disconnect"
    btn_y = y + 14
    display.text(btn_label, (WIDTH - len(btn_label) * 8) // 2, btn_y, Color.White)

    draw_footer_hint("BACK cancel")


RSSI_MIN = -100
RSSI_MAX = -40


def _rssi_bar_frac(rssi):
    frac = (rssi - RSSI_MIN) / (RSSI_MAX - RSSI_MIN)
    if frac < 0.0:
        frac = 0.0
    if frac > 1.0:
        frac = 1.0
    return frac


def draw_ble_scan_screen():
    display.fill(Color.Black)
    count = len(_ble_scan_results)
    title = "SCANNING" if not _ble_scan_done else "FOUND (%d)" % count
    header_h = draw_header(title, badge=False)

    row_h = 14
    y = header_h + 4
    max_rows = (HEIGHT - header_h - 4 - 12) // row_h

    if not _ble_scan_results:
        msg = "Scanning..." if not _ble_scan_done else "No devices found"
        display.text(msg, (WIDTH - len(msg) * 8) // 2, HEIGHT // 2 - 4, Color.White)
    else:
        name_max_chars = (WIDTH - 8 - 34) // 8
        for i, (label, rssi) in enumerate(_ble_scan_results[:max_rows]):
            row_label = _truncate(label, name_max_chars)
            selected = _ble_scan_done and i == _ble_scan_selected_idx
            if selected:
                display.fill_rect(2, y - 1, WIDTH - 4, row_h - 1, Color.White)
                text_color = Color.Black
            else:
                text_color = Color.White
            display.text(row_label, 4, y, text_color)
            bar_x = WIDTH - 34
            bar_w = 28
            draw_progress_bar(bar_x, y + 1, bar_w, 6, _rssi_bar_frac(rssi), color=text_color)
            y += row_h

    if not _ble_scan_done:
        elapsed = time.ticks_diff(time.ticks_ms(), _ble_scan_started_at)
        remaining_s = max(0, (BLE_SCAN_DURATION_MS - elapsed) // 1000 + 1)
        draw_footer_hint("BACK cancel (%ds)" % remaining_s)
    else:
        draw_footer_hint("UP/DN sel BACK exit")


def _ble_scan_on_up():
    global _ble_scan_selected_idx
    if not _ble_scan_done or not _ble_scan_results:
        return
    _ble_scan_selected_idx = (_ble_scan_selected_idx - 1) % len(_ble_scan_results)
    _mark_dirty()


def _ble_scan_on_down():
    global _ble_scan_selected_idx
    if not _ble_scan_done or not _ble_scan_results:
        return
    _ble_scan_selected_idx = (_ble_scan_selected_idx + 1) % len(_ble_scan_results)
    _mark_dirty()


def draw_ble_control_screen():
    # Deliberately mirrors draw_clock_screen()'s layout (time + date,
    # connection badge) but drawn over draw_background_alternative()
    # instead of the normal clock_bg.spr background, so control mode is
    # visually distinct from the plain clock face at a glance. UP opens
    # the command picker (see _on_up_press); DOWN backs out of it.
    draw_background_alternative()
    draw_connection_badge()

    h, m, _s = get_local_time()
    time_str = "{:02d}:{:02d}".format(h, m)
    text_x = (WIDTH - len(time_str) * 16) // 2
    text_y = HEIGHT // 2 - 16
    _text_2x(time_str, text_x, text_y, Color.White)

    divider_y = text_y + 24
    divider_w = 40
    display.fill_rect((WIDTH - divider_w) // 2, divider_y, divider_w, 1, Color.White)

    year, month, day = get_local_date()
    date_y = divider_y + 8
    if year is not None:
        date_str = "{:02d}/{:02d}/{:04d}".format(day, month, year)
        date_x = (WIDTH - len(date_str) * 8) // 2
        display.text(date_str, date_x, date_y, Color.White)

    if _ble_control_last_cmd and time.ticks_diff(time.ticks_ms(), _ble_control_last_cmd_at) < BLE_CONTROL_CMD_FLASH_MS:
        sent_str = "Sent: %s" % _ble_control_last_cmd
        sent_y = date_y + 14 if year is not None else divider_y + 8
        display.text(sent_str, (WIDTH - len(sent_str) * 8) // 2, sent_y, Color.White)

    draw_footer_hint("UP commands BACK exit")


def draw_ble_cmd_picker_screen():
    display.fill(Color.Black)
    header_h = draw_header("SEND COMMAND", badge=False)

    row_h = 16
    y = header_h + 6
    for i, cmd in enumerate(_BLE_CMD_LIST):
        if i == _ble_cmd_picker_selected_idx:
            display.fill_rect(2, y - 2, WIDTH - 4, row_h - 2, Color.White)
            display.text(cmd, 6, y + 1, Color.Black)
        else:
            display.text(cmd, 6, y + 1, Color.White)
        y += row_h

    draw_footer_hint("SEL send BACK cancel")


def main_loop_ble_control_flash_tick():
    # Called from main_loop() so the "Sent: solve" confirmation clears
    # itself even with no further button presses.
    if _screen == SCREEN_BLE_CONTROL and _ble_control_last_cmd:
        if time.ticks_diff(time.ticks_ms(), _ble_control_last_cmd_at) >= BLE_CONTROL_CMD_FLASH_MS:
            _mark_dirty()


# ---------------------------------------------------------------------------
# Button handlers
# ---------------------------------------------------------------------------

def _on_up_press():
    global _screen, _selected_notif_idx, _BLE_NAV
    if bs:
        backlightO()
        return
    if _screen == SCREEN_SYNC_LOCK:
        return
    if _screen == SCREEN_SETTINGS:
        _settings_on_up()
        return
    if _screen == SCREEN_BLE_SCAN:
        _ble_scan_on_up()
        return
    if _screen == SCREEN_BLE_CONTROL:
        _enter_ble_cmd_picker()
        return
    if _screen == SCREEN_BLE_CMD_PICKER and _BLE_NAV:
        _ble_cmd_picker_on_up()
        return
    if _screen == SCREEN_BLE_BLOCKED:
        return
    if _screen == SCREEN_NOTIF_LIST and _notif_nav_mode:
        if _notifications:
            _selected_notif_idx = (_selected_notif_idx - 1) % len(_notifications)
            _mark_dirty()
        return
    if _screen == SCREEN_MEDIA and _media_control_mode:
        link.media_next()
        _mark_dirty()
        return
    _screen = (_screen - 1) % _NUM_SCREENS
    _mark_dirty()


def _on_down_press():
    global _screen, _selected_notif_idx, _BLE_NAV
    if bs:
        backlightO()
        return
    if _screen == SCREEN_SYNC_LOCK:
        return
    if _screen == SCREEN_SETTINGS:
        _settings_on_down()
        return
    if _screen == SCREEN_BLE_SCAN:
        _ble_scan_on_down()
        return
    if _screen == SCREEN_BLE_CMD_PICKER and _BLE_NAV:
        _ble_cmd_picker_on_down()
        return
    if _screen == SCREEN_BLE_CONTROL:
        return
    if _screen == SCREEN_BLE_BLOCKED:
        return
    if _screen == SCREEN_NOTIF_LIST and _notif_nav_mode:
        if _notifications:
            _selected_notif_idx = (_selected_notif_idx + 1) % len(_notifications)
            _mark_dirty()
        return
    if _screen == SCREEN_MEDIA and _media_control_mode:
        link.media_prev()
        _mark_dirty()
        return
    _screen = (_screen + 1) % _NUM_SCREENS
    _mark_dirty()


def _on_back_press():
    global _screen, _notif_nav_mode, _media_control_mode
    if bs:
        backlightO()
        return
    if _screen == SCREEN_SYNC_LOCK:
        return
    if _screen == SCREEN_SETTINGS:
        _settings_on_back()
        return
    if _screen == SCREEN_BLE_SCAN:
        _exit_ble_scan()
        return
    if _screen == SCREEN_BLE_CONTROL:
        _exit_ble_control()
        return
    if _screen == SCREEN_BLE_CMD_PICKER:
        _exit_ble_cmd_picker()
        return
    if _screen == SCREEN_BLE_BLOCKED:
        _screen = _ble_return_screen
        _mark_dirty()
        return
    if _screen == SCREEN_MEDIA:
        if _media_control_mode:
            _media_control_mode = False
        _screen = SCREEN_CLOCK
        _mark_dirty()
    elif _screen == SCREEN_NOTIF_LIST:
        if _notif_nav_mode:
            _notif_nav_mode = False
            _mark_dirty()
        else:
            _screen = SCREEN_CLOCK
            _mark_dirty()
    elif _screen == SCREEN_CLOCK:
        backlightF()


def _on_select_press():
    global _select_held, _select_hold_start, _select_press_woke_dark_screen
    _select_held = True
    _select_hold_start = time.ticks_ms()
    _select_press_woke_dark_screen = bs
    if bs:
        backlightO()
    elif _screen == SCREEN_CLOCK:
        global _slide_active, _slide_progress
        _slide_active = True
        _slide_progress = 0.0
        _mark_dirty()


def _on_select_release():
    global _select_held, _slide_active, _slide_progress
    if not _select_held:
        return 
    held_ms = time.ticks_diff(time.ticks_ms(), _select_hold_start)
    _select_held = False
    if _slide_active:
        _slide_active = False
        _slide_progress = 0.0
        _mark_dirty()
    if _select_press_woke_dark_screen:
        return  
    if _screen == SCREEN_SYNC_LOCK:
        return
    if held_ms < SETTINGS_HOLD_MS:
        _do_select_short_action()


def _do_select_short_action():
    global _media_state, _screen, _notif_nav_mode, _media_control_mode
    if _screen == SCREEN_SYNC_LOCK:
        return
    if _screen == SCREEN_SETTINGS:
        _settings_on_select()
        return
    if _screen == SCREEN_BLE_SCAN:
        return
    if _screen == SCREEN_BLE_CONTROL:
        return
    if _screen == SCREEN_BLE_CMD_PICKER:
        _ble_cmd_picker_confirm()
        return
    if _screen == SCREEN_BLE_BLOCKED:
        _ble_blocked_disconnect()
        return
    if _screen == SCREEN_MEDIA:
        if not _media_control_mode:
            _media_control_mode = True
        else:
            if _media_state == "playing":
                link.media_pause()
                _media_state = "paused"
            else:
                link.media_play()
                _media_state = "playing"
        _mark_dirty()
    elif _screen == SCREEN_PEDOMETER:
        pedometer.reset()
        _mark_dirty()
    elif _screen == SCREEN_NOTIF_LIST:
        if not _notif_nav_mode:
            _clamp_selected_idx()
            _notif_nav_mode = True
        else:
            _notif_nav_mode = False
        _mark_dirty()


buttons.on_press(Buttons.Up, _on_up_press)
buttons.on_press(Buttons.Down, _on_down_press)
buttons.on_press(Buttons.Back, _on_back_press)
buttons.on_press(Buttons.Select, _on_select_press)
buttons.on_release(Buttons.Select, _on_select_release)


_batt_level = battery.LEVEL_HALF
_charging = False
_charge_pin = None


def _init_charge_pin():
    global _charge_pin
    # cs.pins.CHARGE (2) is a *logical* pin index, not a raw GPIO number --
    # on this rev2 board it must go through cs.pins.get()/currentMap to
    # resolve to the real GPIO (36). Passing the raw logical index (2)
    # straight to machine.Pin() was opening the wrong physical pin, which
    # is why the charge line never reacted to plugging in.
    charge_gpio = cs.pins.get(cs.pins.CHARGE)
    _charge_pin = Pin(charge_gpio, Pin.IN, Pin.PULL_UP)


BATTERY_BLE_CUTOFF_PCT = 30
_ble_killed_for_battery = False


def _poll_battery():
    global _batt_level, _charging, _ble_killed_for_battery
    level, changed = battery.poll(cs.pins.BATT)
    if changed:
        _batt_level = level
        _mark_dirty()

    # GPIO36 (resolved logical CHARGE pin) reads 1 while charging, 0
    # when unplugged -- confirmed on-device, opposite of the initial
    # active-low assumption.
    charging_now = (_charge_pin.value() == 1)
    if charging_now != _charging:
        _charging = charging_now
        _mark_dirty()
        if charging_now:
            _ble_killed_for_battery = False

    if not _ble_killed_for_battery:
        _enforce_battery_ble_cutoff()


def _enforce_battery_ble_cutoff():
    global _ble_killed_for_battery
    if _charging:
        return
    pct = battery.get_battery_percentage()
    if pct < BATTERY_BLE_CUTOFF_PCT:
        _ble_killed_for_battery = True
        try:
            link.disconnect()
        except Exception as e:
            print("battery-cutoff disconnect error:", e)
        _mark_dirty()


def _draw_battery_icon_fallback(x, y, invert=False):
    outline = Color.White
    w, h = 14, 7
    tip_w, tip_h = 2, 3

    display.rect(x, y, w, h, outline)
    display.fill_rect(x + w, y + (h - tip_h) // 2, tip_w, tip_h, outline)

    inner_w = w - 2
    level = _batt_level
    if level <= battery.LEVEL_CRITICAL:
        fill_w = max(1, inner_w // 4)
        fill_color = Color.Red if hasattr(Color, "Red") else outline
    elif level == battery.LEVEL_LOW:
        fill_w = inner_w // 2
        fill_color = Color.Red if hasattr(Color, "Red") else outline
    elif level == battery.LEVEL_HALF:
        fill_w = (inner_w * 3) // 4
        fill_color = outline
    else:
        fill_w = inner_w
        fill_color = Color.Green if hasattr(Color, "Green") else outline

    if fill_w > 0:
        display.fill_rect(x + 1, y + 1, fill_w, h - 2, fill_color)

    if _charging:
        bolt_x = x + w // 2 - 1
        bolt_color = Color.Yellow if hasattr(Color, "Yellow") else Color.Black
        display.fill_rect(bolt_x, y - 1, 2, h + 2, bolt_color)


def draw_battery_icon(x, y, invert=False):
    if HAVE_BATT_ICONS:
        BATT_ICONS.draw(display, _batt_level, x - 5, y - 5, charging=_charging, transparent=True, black_overlay=True, overlay_color=0xFFE0)
    else:
        _draw_battery_icon_fallback(x, y, invert=invert)


def draw_connection_badge(y=3, invert=False):
    batt_x = WIDTH - 4 - 14 - 2
    if invert:
        patch_x = batt_x - 22
        display.fill_rect(patch_x, y - 3, WIDTH - patch_x, 14, Color.Black)
    draw_battery_icon(batt_x, y, invert=False)

    if not _ble_connected:
        return

    phone_x = batt_x - 18
    try:
        PHONE_ICONS.draw(display, "pair", phone_x, y, transparent=True)
    except Exception as e:
        print('phone icon err', e)


def _truncate(s, max_chars):
    return render.truncate(s, max_chars)


def draw_round_rect(x, y, w, h, r, color, fill=True, bg_color=None):
    render.draw_round_rect(display, x, y, w, h, r, color, fill=fill, bg_color=bg_color)


def _text_2x(s, x, y, color):
    render.text_2x(display, s, x, y, color)


def draw_header(title, badge=True):
    HEADER_H = 14
    display.fill_rect(0, 0, WIDTH, HEADER_H, Color.White)
    display.text(title, 4, 3, Color.Black)
    if badge:
        draw_connection_badge(y=3, invert=True)
    return HEADER_H


def draw_footer_hint(text):
    display.text(text, 4, HEIGHT - 12, Color.White)


def draw_progress_bar(x, y, w, h, frac, color=None):
    color = color or Color.White
    render.draw_progress_bar(display, x, y, w, h, frac, color)


_date_debug_printed = False


_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def draw_clock_screen():
    global _date_debug_printed
    draw_background()
    draw_connection_badge()

    h, m, _s = get_local_time()
    time_str = "{:02d}:{:02d}".format(h, m)

    text_x = (WIDTH - len(time_str) * 16) // 2
    text_y = HEIGHT // 2 - 16
    _text_2x(time_str, text_x, text_y, Color.White)

    divider_y = text_y + 24
    divider_w = 40
    display.fill_rect((WIDTH - divider_w) // 2, divider_y, divider_w, 1, Color.White)

    year, month, day = get_local_date()
    if not _date_debug_printed:
        print("DATE DEBUG raw:", "year=", year, "month=", month, "day=", day)
        _date_debug_printed = True
    if year is not None:
        date_str = "{:02d}/{:02d}/{:04d}".format(day, month, year)
        date_x = (WIDTH - len(date_str) * 8) // 2
        date_y = divider_y + 8
        display.text(date_str, date_x, date_y, Color.White)


def draw_media_screen():
    draw_background()
    header_h = draw_header("MEDIA")

    center_x = WIDTH // 2
    btn_y = header_h + 12
    btn_size = 40

    draw_round_rect(center_x - btn_size // 2, btn_y, btn_size, btn_size, 10, Color.White, fill=False, bg_color=Color.Black)

    if _media_state == "playing":
        bar_w, bar_h = 5, 18
        gap = 6
        bx = center_x - (bar_w * 2 + gap) // 2
        by = btn_y + (btn_size - bar_h) // 2
        display.fill_rect(bx, by, bar_w, bar_h, Color.White)
        display.fill_rect(bx + bar_w + gap, by, bar_w, bar_h, Color.White)
    else:
        tri_h = 18
        tri_w = 16
        tx = center_x - tri_w // 3
        ty = btn_y + (btn_size - tri_h) // 2
        for i in range(tri_h):
            row_w = int(tri_w * min(i, tri_h - i) / (tri_h / 2))
            display.fill_rect(tx, ty + i, max(1, row_w), 1, Color.White)

    if _media_control_mode:
        chevron_y = btn_y + btn_size // 2
        _draw_chevron(center_x - btn_size // 2 - 16, chevron_y, direction="left")
        _draw_chevron(center_x + btn_size // 2 + 16, chevron_y, direction="right")

    text_y = btn_y + btn_size + 10
    if not _ble_connected:
        display.text("Not connected", (WIDTH - len("Not connected") * 8) // 2, text_y, Color.White)
    else:
        title = _truncate(_media_title or "(untitled)", 15)
        artist = _truncate(_media_artist or "", 15)
        display.text(title, (WIDTH - len(title) * 8) // 2, text_y, Color.White)
        if artist:
            display.text(artist, (WIDTH - len(artist) * 8) // 2, text_y + 12, Color.White)
        state_label = {"playing": "> Playing", "paused": "|| Paused"}.get(_media_state, "- Stopped")
        display.text(state_label, (WIDTH - len(state_label) * 8) // 2, text_y + 26, Color.White)

    if _media_control_mode:
        display.text("UP next DN prev", 4, HEIGHT - 24, Color.White)
        draw_footer_hint("SEL play/pause")
    else:
        draw_footer_hint("SEL for controls")


def _draw_chevron(cx, cy, direction="right", size=6):
    render.draw_chevron(display, Color.White, cx, cy, direction=direction, size=size)


PEDOMETER_DAILY_GOAL = 10000


def draw_pedometer_screen():
    draw_background()
    header_h = draw_header("STEPS")

    steps = pedometer.get_steps()
    steps_str = str(steps)
    text_x = (WIDTH - len(steps_str) * 16) // 2
    text_y = header_h + 22
    _text_2x(steps_str, text_x, text_y, Color.White)

    bar_y = text_y + 26
    bar_w = WIDTH - 24
    bar_x = 12
    frac = steps / PEDOMETER_DAILY_GOAL
    draw_progress_bar(bar_x, bar_y, bar_w, 10, frac)

    goal_str = "%d / %d" % (steps, PEDOMETER_DAILY_GOAL)
    display.text(goal_str, (WIDTH - len(goal_str) * 8) // 2, bar_y + 14, Color.White)

    draw_footer_hint("SEL reset steps")


def _wrap_text(text, max_chars):
    return render.wrap_text(text, max_chars)


def draw_notif_list_screen():
    draw_background()
    count = len(_notifications)
    title = "NOTIFS (%d)" % count if count else "NOTIFS"
    header_h = draw_header(title)

    card_x, card_y = 4, header_h + 4
    card_w, card_h = WIDTH - 8, HEIGHT - header_h - 4 - 14
    draw_round_rect(card_x, card_y, card_w, card_h, 6, Color.White, fill=False, bg_color=Color.Black)

    if not count:
        msg1, msg2 = "No", "notification"
        display.text(msg1, card_x + (card_w - len(msg1) * 8) // 2, card_y + card_h // 2 - 14, Color.White)
        display.text(msg2, card_x + (card_w - len(msg2) * 8) // 2, card_y + card_h // 2 - 2, Color.White)
        draw_footer_hint("BACK exit")
        return

    notif = _notifications[_selected_notif_idx]

    title_bar_h = 14
    if _notif_nav_mode:
        display.fill_rect(card_x + 1, card_y + 1, card_w - 2, title_bar_h, Color.White)
        title_color = Color.Black
    else:
        title_color = Color.White
    label = _truncate(notif.get("title", "Notif"), 14)
    display.text(label, card_x + 6, card_y + 4, title_color)

    sep_y = card_y + title_bar_h + 2
    if not _notif_nav_mode:
        display.fill_rect(card_x + 4, sep_y, card_w - 8, 1, Color.White)

    msg = notif.get("message", "")
    body_max_chars = (card_w - 12) // 8
    lines = _wrap_text(msg, body_max_chars)
    y = sep_y + 6
    max_lines = max(0, (card_y + card_h - 6 - y) // 12)
    for line in lines[:max_lines]:
        display.text(line, card_x + 6, y, Color.White)
        y += 12

    if notif.get("truncated") and len(lines) > max_lines:
        display.text("...", card_x + 6, y, Color.White)

    if count > 1:
        pos_str = "%d/%d" % (_selected_notif_idx + 1, count)
        display.text(pos_str, card_x + card_w - len(pos_str) * 8 - 4, card_y + card_h - 12, Color.White)

    hint = "UP/DN nav SEL close" if _notif_nav_mode else "SEL to browse"
    draw_footer_hint(hint)


def draw_slide_overlay():
    x = _slide_x()
    y = _slide_y()
    if HAVE_SLIDER_TRACK_SPRITE:
        track_x = SLIDE_MARGIN
        track_y = HEIGHT - SLIDE_MARGIN - _SLIDER_TRACK_H
        sprite.blit_file(display, SLIDER_TRACK_SPRITE_PATH, track_x, track_y)
    else:
        display.fill_rect(SLIDE_MARGIN, _slide_y(), SLIDE_TRAVEL + SLIDE_BOX_W, SLIDE_BOX_H, Color.Black)

    if HAVE_SLIDER_SPRITE:
        sprite.blit_file(display, SLIDER_SPRITE_PATH, x, y)
    else:
        display.fill_rect(x, y, SLIDE_BOX_W, SLIDE_BOX_H, Color.White)


BATTERY_LOG_PATH = "battery_info_log.csv"
BATTERY_LOG_INTERVAL_MS = 15 * 60 * 1000  # 15 minutes


def _log_battery_info():
    try:
        voltage = battery.get_battery_voltage()
        percentage = battery.get_battery_percentage()
        capacity = battery.get_remaining_capacity_mah()
    except Exception as e:
        print("battery log read error:", e)
        return

    year, month, day = get_local_date()
    h, m, s = get_local_time()
    if year is not None:
        ts_str = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(year, month, day, h, m, s)
    else:
        ts_str = "t={}".format(time.ticks_ms())

    is_new_file = False
    try:
        with open(BATTERY_LOG_PATH, "r"):
            pass
    except OSError:
        is_new_file = True

    try:
        with open(BATTERY_LOG_PATH, "a") as f:
            if is_new_file:
                f.write("timestamp,voltage_v,percentage,capacity_mah,charging,batt_level\n")
            f.write("{},{:.3f},{},{},{},{}\n".format(
                ts_str, voltage, percentage, capacity,
                1 if _charging else 0, _batt_level,
            ))
    except OSError as e:
        print("battery log write error:", e)



def draw_frame():
    _f0 = time.ticks_ms()
 
    if _screen == SCREEN_SYNC_LOCK:
        draw_sync_lock_screen(full_redraw=not _sync_screen_battery_drawn)
        _fc0 = time.ticks_ms()
        display.commit()
        _fc1 = time.ticks_ms()
        print("draw_frame(SYNC_LOCK): commit=%dms TOTAL=%dms" % (
            time.ticks_diff(_fc1, _fc0), time.ticks_diff(_fc1, _f0)))
        return
 
    _f1 = time.ticks_ms()
    if _screen == SCREEN_CLOCK:
        draw_clock_screen()
    elif _screen == SCREEN_MEDIA:
        draw_media_screen()
    elif _screen == SCREEN_PEDOMETER:
        draw_pedometer_screen()
    elif _screen == SCREEN_NOTIF_LIST:
        draw_notif_list_screen()
    elif _screen == SCREEN_SETTINGS:
        draw_settings_screen()
    elif _screen == SCREEN_BLE_SCAN:
        draw_ble_scan_screen()
    elif _screen == SCREEN_BLE_CONTROL:
        draw_ble_control_screen()
    elif _screen == SCREEN_BLE_CMD_PICKER:
        draw_ble_cmd_picker_screen()
    elif _screen == SCREEN_BLE_BLOCKED:
        draw_ble_blocked_screen()
    _f2 = time.ticks_ms()
 
    if _slide_active and _screen != SCREEN_SETTINGS:
        draw_slide_overlay()
    _f3 = time.ticks_ms()
 
    display.commit()
    _f4 = time.ticks_ms()
 
    print("draw_frame(screen=%d): draw=%dms overlay=%dms commit=%dms TOTAL=%dms" % (
        _screen,
        time.ticks_diff(_f2, _f1),
        time.ticks_diff(_f3, _f2),
        time.ticks_diff(_f4, _f3),
        time.ticks_diff(_f4, _f0),
    ))
 



bs = False
last_activity = 0

FREQ_ACTIVE_HZ = 240_000_000
FREQ_IDLE_DISCONNECTED_HZ = 20_000_000
FREQ_IDLE_CONNECTED_HZ = 80_000_000


def backlightO():
    global bs, last_activity
    freq(FREQ_ACTIVE_HZ)
    cs.backlight.on()
    was_off = bs
    bs = False
    last_activity = time.ticks_ms()
    if was_off:
        _mark_dirty()


def backlightF():
    global bs
    if _screen == SCREEN_SYNC_LOCK:
        # Never let the lock screen go dark on idle -- the whole point is
        # the user sees "sync needed" until they do it; a blanked screen
        # while locked would look like the watch is off/broken instead of
        # waiting on them.
        return
    cs.backlight.off()
    bs = True
    idle_hz = FREQ_IDLE_CONNECTED_HZ if _ble_connected else FREQ_IDLE_DISCONNECTED_HZ
    freq(idle_hz)


def _refresh_idle_freq():
    if bs:
        idle_hz = FREQ_IDLE_CONNECTED_HZ if _ble_connected else FREQ_IDLE_DISCONNECTED_HZ
        freq(idle_hz)


def _update_active_ui(now, last_sync_anim, last_pedometer_steps):
    global _select_held, _select_hold_start, _slide_active, _slide_progress, last_activity

    if _screen == SCREEN_PEDOMETER:
        current_steps = pedometer.get_steps()
        if current_steps != last_pedometer_steps:
            last_pedometer_steps = current_steps
            _mark_dirty()

    if _screen == SCREEN_SYNC_LOCK and time.ticks_diff(now, last_sync_anim) >= SYNC_ANIM_INTERVAL_MS:
        last_sync_anim = now
        _sync_lock_tick_anim()

    if (_screen != SCREEN_SYNC_LOCK and _select_held and not _select_press_woke_dark_screen
            and _slide_active and _screen == SCREEN_CLOCK):
        held_ms = time.ticks_diff(now, _select_hold_start)
        _slide_progress = min(1.0, held_ms / SETTINGS_HOLD_MS)
        _mark_dirty()
        if held_ms >= SETTINGS_HOLD_MS:
            _select_held = False
            _slide_active = False
            _open_settings()
        last_activity = now

    if _screen == SCREEN_SETTINGS and _settings_selected_row == SETTINGS_ROW_GYRO and _settings_in_row:
        _mark_dirty()

    main_loop_ble_control_flash_tick()
    _ble_blocked_recheck()

    return last_sync_anim, last_pedometer_steps


def main_loop():
    global _dirty, last_activity
    global _select_held, _select_hold_start, _select_press_woke_dark_screen, _slide_active, _slide_progress
    global _screen, _synced
    global _sync_transition_pending_at, _sync_screen_battery_drawn
    last_second = -1
    last_pairing_poll = time.ticks_ms()
    last_battery_poll = time.ticks_ms()
    last_battery_log = time.ticks_ms()
    last_input_poll = time.ticks_ms()
    last_gyro_poll = time.ticks_ms()
    last_sync_anim = time.ticks_ms()
    last_activity = time.ticks_ms()
    last_screen = _screen
    last_pedometer_steps = pedometer.get_steps()

    _init_charge_pin()
    _poll_battery()

    if _check_rtc_synced_from_hw():
        _synced = True
    else:
        _screen = SCREEN_SYNC_LOCK

    prev_gx, prev_gy, prev_gz = cs.imu.get_gyro()
    MOTION_THRESHOLD = 15.0

    INPUT_POLL_OFF_MS = 200
    GYRO_POLL_ON_MS = 20
    GYRO_POLL_OFF_MS = 1000
    BLE_POLL_ON_MS = 150
    BLE_POLL_OFF_MS = 2000
    # NOTE: SYNC_ANIM_INTERVAL_MS lives at module scope (see the sync-lock
    # screen state block above), NOT as a local here -- a local of the
    # same name here previously shadowed it only inside this function,
    # leaving every other reader (like _update_active_ui) see an
    # undefined name and crash with NameError.

    while True:
        pedometer.poll()
        now = time.ticks_ms()

        if not bs:
            last_sync_anim, last_pedometer_steps = _update_active_ui(
                now, last_sync_anim, last_pedometer_steps
            )

        do_input_poll = (not bs) or (
            time.ticks_diff(now, last_input_poll) >= INPUT_POLL_OFF_MS
        )
        
        gyro_debug_open = (
            _screen == SCREEN_SETTINGS
            and _settings_selected_row == SETTINGS_ROW_GYRO
            and _settings_in_row
        )
        gyro_needed = _tilt_to_wake_enabled or (gyro_debug_open and not bs)

        gyro_poll_interval = GYRO_POLL_ON_MS if not bs else GYRO_POLL_OFF_MS
        do_gyro_poll = gyro_needed and (
            time.ticks_diff(now, last_gyro_poll) >= gyro_poll_interval
        )

        if do_gyro_poll:
            last_gyro_poll = now
            try:
                gx, gy, gz = cs.imu.get_gyro()
                delta_motion = abs(gx - prev_gx) + abs(gy - prev_gy) + abs(gz - prev_gz)
                prev_gx, prev_gy, prev_gz = gx, gy, gz

                if _tilt_to_wake_enabled and delta_motion > MOTION_THRESHOLD:
                    last_activity = now
                    if bs:
                        backlightO()
            except Exception:
                pass

        if do_input_poll:
            last_input_poll = now

            if buttons.scan() or _screen != last_screen:
                last_activity = now
                last_screen = _screen
                if bs:
                    backlightO()

        ble_poll_interval = BLE_POLL_OFF_MS if bs else BLE_POLL_ON_MS
        if time.ticks_diff(now, last_pairing_poll) >= ble_poll_interval:
            link.poll()
            last_pairing_poll = now

        # Delayed sync -> clock screen handoff. See SYNC_TRANSITION_DELAY_MS
        # note near _on_sync_acquired(): the actual screen switch happens
        # here, SYNC_TRANSITION_DELAY_MS after set_rtc() first landed, not
        # the instant it lands -- giving link.poll() a few cycles above to
        # drain any BLE burst still arriving before the first heavy
        # blit_file() (clock_bg.spr) of the session fires.
        if (_sync_transition_pending_at is not None
                and time.ticks_diff(now, _sync_transition_pending_at) >= SYNC_TRANSITION_DELAY_MS):
            _sync_transition_pending_at = None
            _screen = SCREEN_CLOCK
            _sync_screen_battery_drawn = False
            last_screen = _screen
            _mark_dirty()

        battery_row_open = (
            _screen == SCREEN_SETTINGS
            and _settings_selected_row == SETTINGS_ROW_BATTERY
            and _settings_in_row
            and not bs
        )
        battery_poll_interval = 1000 if battery_row_open else 15000
        if time.ticks_diff(now, last_battery_poll) >= battery_poll_interval:
            _poll_battery()
            last_battery_poll = now
            if battery_row_open:
                _mark_dirty()

        if time.ticks_diff(now, last_battery_log) >= BATTERY_LOG_INTERVAL_MS:
            _log_battery_info()
            last_battery_log = now

        veille_ms = VEILLE_OPTIONS_MS[_veille_idx]
        veille_exempt = _screen in (SCREEN_SETTINGS, SCREEN_SYNC_LOCK, SCREEN_BLE_CONTROL,
                                     SCREEN_BLE_CMD_PICKER, SCREEN_BLE_SCAN, SCREEN_BLE_BLOCKED)
        if (not bs and not veille_exempt
                and time.ticks_diff(now, last_activity) >= veille_ms):
            backlightF()

        _, m, _s = get_local_time()
        minute_changed = _screen == SCREEN_CLOCK and m != last_second
        if minute_changed:
            last_second = m

        if bs:
            if _dirty or minute_changed:
                _dirty = True
        else:
            if _dirty or minute_changed:
                draw_frame()
                _dirty = False

        if bs:   
            time.sleep_ms(100)
        else:
            time.sleep_ms(20)


if __name__ == "__main__":
    cs.rgb.set(0, 0, 0)
    _load_settings()
    main_loop()