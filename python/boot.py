import esp32
import machine

print("at boot:", esp32.idf_heap_info(esp32.HEAP_DATA))

# Check for pending OTA update at boot
try:
    import ota_update
    if ota_update.check_for_pending_update():
        print("boot: WARNING - pending OTA update found, consider recovery")
except Exception as e:
    print("boot: OTA check error:", e)

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
