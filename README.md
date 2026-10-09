# ClockStar v2 — Custom MicroPython Firmware

A from-scratch MicroPython firmware for the [CircuitMess ClockStar v2](https://circuitmess.com/) smartwatch, built to replace the stock C++/ESP-IDF + LovyanGFX firmware while staying compatible with the **official CircuitMess Android app** over Bluetooth — no custom phone app required.

Runs on the ClockStar v2's ESP32-S3, 128x128 display.

## Features

- **Clock, media, notifications, and settings screens**, cycled with Up/Down
- **Faster install**: a speed test runs before every install and finds the fastest packet size that transfers error-free (checksum-verified on the watch)
- **Extensions any time**: extensions can be installed on their own later, without reflashing the firmware
- **Clock set at install**: the web installer writes this computer's local time to the watch RTC, so no "SYNC NEEDED" screen after flashing
- **Screen API + extensions**: add a screen in one function (`screens.py`), and install optional extensions (pedometer, metronome, ...) from the web installer
- **BLE integration with the stock CircuitMess app** via a from-scratch Nordic UART Service (NUS) implementation — time sync, notifications, call alerts, media control/state, and phone-find, all speaking the same protocol as the original firmware
- **Battery gauge** using a piecewise LiPo discharge curve (not a naive linear map), with charge detection and a low-battery BLE auto-disconnect (IS STILL HAVING ISSUES WITH IT SORRY)
- **Settings screen** (hold Back ~1.4s): idle/backlight timeout, tilt-to-wake toggle, live gyro debug readout, detailed battery info — all persisted to `settings.json`
- **RTC sync lock screen**: blocks the UI with a "SYNC NEEDED" prompt until the phone app provides a real time over BLE, so the watch never silently runs on a bogus 1900 date
- **Power management**: dynamic CPU frequency scaling (240MHz active / 60-80MHz idle depending on BLE state), throttled gyro/BLE/input polling while the screen is off

## Some info
- **The battery was tested to survive about 11h MAX** There a file that is a .csv containing battery data
- **I RECOMMEND that you install micropython 1.29.0 as it remove most off the issues** will be added later on the site when I fix my watch (power button broke :) )
 
## Repo Layout

```
main.py           Screen state machine, button handlers, main loop
phone_link.py      CircuitMess app protocol on top of the NUS transport
ble_nus.py         Generic Nordic UART Service BLE peripheral wrapper
battery.py         Voltage sampling, discharge-curve %, charge detection
screens.py         Screen/extension API (add a screen in one function)
extensions/        Optional add-ons offered by the installer (manifest.json + one folder each)
render.py          Shared drawing primitives (rounded rects, 2x text, progress bars, chevrons, text wrapping)
sprite.py          .spr sprite/icon loading and blitting
boot.py            Boot-time init
settings.json      Persisted user settings (created on first run)
icons/             Battery/phone/UI sprite assets
clock_bg.spr        Clock face background sprite
```

## Flashing

A browser-based installer (Web Serial API) is available for flashing this firmware without any local tooling — just Chrome/Edge, a USB-C cable, and the watch. It fetches every file from this repo, opens a MicroPython Raw REPL session over serial, and writes each file to the device.

**Requirements:** Chrome or Edge (Web Serial API support). Firefox/Safari are not supported.

## Extensions & adding a screen

A screen is one function in a module that exposes `register(api)` (full docs at the top of `python/screens.py`):

```python
# ext_hello.py
def register(api):
    ctx = api.ctx

    def draw():
        ctx.draw_background()
        ctx.draw_header("HELLO")
        ctx.draw_footer_hint("SEL click")

    api.add_screen("Hello", draw, on_select=lambda: print("clicked"))
```

It then shows up in the Up/Down cycle (or as a row in Settings with `in_settings=True`). Optional callbacks: `on_up`, `on_down`, `on_select`, `on_back`, `tick(now)`, `background(now)`, `on_enter`, `on_exit`, `veille_exempt`, `order`.

To offer it in the web installer, put the files under `python/extensions/<id>/` and add an entry to `python/extensions/manifest.json` (no change to `index.html` needed). The installer writes the chosen modules to `extensions.json` on the watch. A file whose `dest` matches a core file overrides it.

Bundled extensions:
- **Pedometer**: step counter screen in the Up/Down cycle (moved out of the core firmware).
- **Metronome**: page in Settings, 30-240 BPM (Up/Down, faster when pressed quickly), SEL start/stop. Installs a working `Clockstar_v2/piezo_mini.py` over the stock disabled one.

## Known Issues

- **BLE controller crash-reboot loop**: on some resets, native BLE init fails (`BLE_INIT: hci inits failed` / `nimble host init failed`) and the ESP32-S3 panics (`Guru Meditation Error`, heap-related). The firmware currently recovers from this on its own via its automatic reboot, but the underlying cause (heap fragmentation during BLE controller init) is not fully root-caused. A genuine physical USB power cycle is the only fix confirmed to clear it if auto-recovery doesn't kick in — a software `machine.reset()` does not reliably clear it.
-  Battery voltage still not working (Official firmware seem to not work too)
## Hardware Notes
- Battery does voltage seems unreadable and official repo doesn't to
 
## Credits

Protocol details (NUS UUIDs, handshake, command set) reverse-engineered from the public [Clockstar-v2-Firmware](https://github.com/CircuitMess/Clockstar-v2-Firmware) source. Using IA mostly sorry
