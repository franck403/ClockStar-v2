import esp32
import machine
import sys

print("at boot:", esp32.idf_heap_info(esp32.HEAP_DATA))

# Check for pending OTA update at boot
try:
    import ota_update
    if ota_update.check_for_pending_update():
        print("boot: WARNING - pending OTA update found, consider recovery")
except Exception as e:
    print("boot: OTA check error:", e)

# Try to import main and capture any syntax/import errors
print("boot: importing main...")
try:
    import main
except SyntaxError as e:
    print("boot: ERROR - main.py has syntax error:")
    print("  File:", e.filename)
    print("  Line:", e.lineno, "-", e.text)
    print("  ", e.msg)
except ImportError as e:
    print("boot: ERROR - main.py import failed:", e)
except Exception as e:
    print("boot: ERROR - main.py error:", type(e).__name__, "-", e)

#
#import bluetooth
#import time

#ble = bluetooth.BLE()

#try:
#    ble.active(False)
#    time.sleep_ms(100)
#except Exception:
#    pass
#
#try:
#    ble.active(True)
#except Exception:
#    machine.reset()
