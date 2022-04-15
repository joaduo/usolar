import uasyncio
import ujson
import machine
import utime
import log
import webserver
# import devices


LIGHT_PIN=2
#light = devices.InvertedPin(LIGHT_PIN, machine.Pin.OUT)
light = machine.Pin(LIGHT_PIN, machine.Pin.OUT)


async def blink():
    light.off()
    await uasyncio.sleep(0.2)
    light.on()


async def serve_request(verb, path, request_trailer):
    log.info(path)
    uasyncio.create_task(blink())
    content_type = 'application/json'
    status = 200
    if path == b'/voltages':
        payload = ujson.dumps(dict(charger=0))
    else:
        content_type = 'text/html'
        if path == b'/':
            resp = webserver.response(status, content_type, '')
            return resp, webserver.serve_file('/static/client.html')
        else:
            status = 404
            payload = webserver.web_page('404 Not found')
    return webserver.response(status, content_type, payload)


def main():
    gmt, localt = utime.gmtime(), utime.localtime()
    assert gmt == localt
    server = webserver.Server(serve_request)
    server.static_path = b'/static/'
    log.garbage_collect()
    try:
        light.on()
        uasyncio.run(server.run())
        uasyncio.get_event_loop().run_forever()
        #uasyncio.run(riego.loop_tasks())
    finally:
        uasyncio.run(server.close())
        _ = uasyncio.new_event_loop()



if __name__ == '__main__':
    main()

