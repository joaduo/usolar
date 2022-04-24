import uasyncio
import ujson
import machine
import utime
import log
import webserver
import solar


LIGHT_PIN = 2
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
        payload = ujson.dumps(solar.historylog.latest_read())
    elif path == b'/history':
        if verb == webserver.POST:
            cfg = webserver.extract_json(request_trailer)
            solar.historylog.set_json(cfg)
        payload = ujson.dumps(solar.historylog.get_json())
    elif path == b'/relays':
        ...
    elif path == b'/resiston':
        solar.resistance.on()
        payload = ujson.dumps(dict(result='on'))
    elif path == b'/resistoff':
        solar.resistance.off()
        payload = ujson.dumps(dict(result='off'))
    else:
        content_type = 'text/html'
        if path == b'/':
            resp = webserver.response(status, content_type, '')
            return resp, webserver.serve_file('/client.html')
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
    log.LOG_LEVEL = log.DEBUG
    try:
        light.on()
        uasyncio.run(server.run())
        uasyncio.run(solar.loop_tasks())
    finally:
        uasyncio.run(server.close())
        _ = uasyncio.new_event_loop()



if __name__ == '__main__':
    solar.resistance.off()
    main()

