import esp32

print("at boot:", esp32.idf_heap_info(esp32.HEAP_DATA))
#
#import bluetooth
#import machine
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
