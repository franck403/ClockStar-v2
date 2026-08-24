# Clockstar v2 Smartwatch Firmware (sorry its ia will be corrected in the next days)

An interactive MicroPython application written for the Clockstar v2 smartwatch platform. This firmware features custom watch face rendering, real-time clock (RTC) synchronization, Bluetooth notification handling, media playback controls, a step counter (pedometer), and an on-device settings menu.

## Features

* **Watchface & Custom UI:** Multi-screen interface with background sprite support, custom 2x typography, and dynamic status badges.
* **BLE Phone Link:** Synchronizes date/time with a paired mobile app, receives incoming notifications, and manages media play/pause/track navigation.
* **RTC Auto-Correction:** Handles epoch shifting between standard Unix (1970) and MicroPython (2000) base dates to ensure multi-field date accuracy.
* **Notification Center:** Stores up to 20 recent phone notifications with pagination and detail navigation.
* **Pedometer:** Tracks daily step count with progress monitoring against standard goals.
* **Settings & Persistence:** Adjust screen veille (idle backlight timeout), toggle tilt-to-wake, view battery stats, and monitor live IMU/gyro data. Settings automatically persist to `settings.json`.
* **Gesture Controls:** Slide-to-unlock gesture via long-press on the Select button.
* **Offical app supoprt:** The new app is a replacement for the original firmware will keeping what it could do.

---

## Required Hardware & Dependencies

### Hardware

* **Clockstar v2** Smartwatch platform (ESP32 / MicroPython MCU with BM8563 RTC, IMU, and ST7789 or compatible display).

### Python Modules

Ensure the following drivers and helper scripts exist on the device's root filesystem alongside `main.py`:

* `Clockstar_v2.py` (Board support package for display, RTC, buttons, piezo, IMU)
* `phone_link.py` (BLE communication handler)
* `battery.py` (ADC voltage reader and capacity calculator)
* `sprite.py` (File-based binary sprite reader and blitter)
* `pedometer.py` (Step counting routines using internal IMU)

### Visual Assets (Icons & Sprites)

The code attempts to load the following optional asset files from the filesystem. If absent, the interface falls back to line-drawn UI primitives.

```text
/
├── clock_bg.spr
└── icons/
    ├── batt_full.spr
    ├── batt_half.spr
    ├── batt_low.spr
    ├── batt_critical.spr
    ├── batt_charging.spr
    ├── phone_connected.spr
    ├── settings_slider.spr
    └── settings_slider_track.spr

```

---

## Installation & Setup

### 1. Flash MicroPython

Ensure your device is running a MicroPython firmware build compatible with the `Clockstar_v2` BSP.

### 2. Upload Files to Device

Using `ampy`, `rshell`, or the **Thonny IDE**, upload all dependency modules, sprite assets, and this script (renamed to `main.py` for auto-boot) into the root directory of your device:

```bash
# Example using ampy
ampy --port /dev/ttyUSB0 put Clockstar_v2.py
ampy --port /dev/ttyUSB0 put phone_link.py
ampy --port /dev/ttyUSB0 put battery.py
ampy --port /dev/ttyUSB0 put sprite.py
ampy --port /dev/ttyUSB0 put pedometer.py
ampy --port /dev/ttyUSB0 put icons /icons
ampy --port /dev/ttyUSB0 put main.py

```

### 3. First Boot

Reset or power-cycle the board. On startup, `Clockstar_v2.begin()` initializes hardware peripherals, loads persistent settings from `settings.json` (or creates default settings if missing), and launches into the main **Clock Screen**.

---

## Navigation & Controls

| Screen / Mode | Button | Action |
| --- | --- | --- |
| **Global** | `Up` / `Down` | Cycle through main screens (Clock → Media → Steps → Notifications). |
| **Global** | `Back` | Return to Clock screen / Turn off backlight (from Clock screen). |
| **Clock Screen** | `Hold Select` (1.4s) | Fill progress slider gesture to open **Settings**. |
| **Media Control** | `Select` | Toggle playback control mode. |
|  | `Up` / `Down` | Next Track / Previous Track (in control mode). |
|  | `Select` | Play / Pause current track (in control mode). |
| **Pedometer** | `Select` | Reset daily step counter. |
| **Notifications** | `Select` | Toggle Notification Navigation Mode. |
|  | `Up` / `Down` | Scroll through notification stack (in nav mode). |
| **Settings** | `Up` / `Down` | Move selector / Adjust selected value. |
|  | `Select` | Drill into row options / Toggle state. |
|  | `Back` | Exit sub-menu / Close Settings. |
