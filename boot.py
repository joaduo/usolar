import esp ; esp.osdebug(None)
import gc; gc.collect() ; print(gc.mem_free())

# As AP (router) (sometimes it's recorded permanently, depending the hardware)
import network
ap = network.WLAN(network.AP_IF)
print(ap.ifconfig())
ap.config(essid='usolar', authmode=network.AUTH_WPA_WPA2_PSK, password='', channel=4)
network.phy_mode(network.MODE_11B)
ap.active(True)


# import webrepl; webrepl.start()
