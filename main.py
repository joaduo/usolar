import uasyncio
import ujson
import machine
import utime
import log
import webserver
import solar


LIGHT_PIN = 2
light = machine.Pin(LIGHT_PIN, machine.Pin.OUT)
solar_manager = None


async def blink():
    light.off()
    await uasyncio.sleep(0.2)
    light.on()


async def serve_request(verb, path, request_trailer):
    log.debug(path)
    uasyncio.create_task(blink())
    content_type = 'application/json'
    status = 200
    if path == b'/devicesread':
        payload = ujson.dumps(solar_manager.latest_read())
    elif path == b'/history':
        if verb == webserver.POST:
            cfg = webserver.extract_json(request_trailer)
            solar_manager.set_json(cfg)
        payload = ujson.dumps(solar_manager.get_json())
    elif path == b'/resistance':
        value = solar_manager.get_resistance()
        if verb == webserver.POST:
            value = solar_manager.set_resistance(not value)
        payload = ujson.dumps(dict(value=value))
    elif path == b'/stopwebserver':
        if verb == webserver.POST:
            solar_manager.stop = True
            raise webserver.StopWebServer()
        payload = ujson.dumps('')
    elif path == b'/reset':
        if verb == webserver.POST:
            solar_manager.reset()
            log.log_history.clear()
            log.important('Resetting server status...')
        payload = ujson.dumps('')
    elif path == b'/loglevel':
        if verb == webserver.POST:
            level = webserver.extract_json(request_trailer)
            log.LOG_LEVEL = level
        payload = ujson.dumps(log.LOG_LEVEL)
    elif path == b'/loghistorycfg':
        if verb == webserver.POST:
            cfg = webserver.extract_json(request_trailer)
            log.LOG_HISTORY_LEVEL = cfg.get('level', log.LOG_HISTORY_LEVEL)
            log.LOG_HISTORY_SIZE = cfg.get('size', log.LOG_HISTORY_SIZE)
        payload = ujson.dumps(dict(level=log.LOG_HISTORY_LEVEL, size=log.LOG_HISTORY_SIZE))
    elif path == b'/log':
        if verb == webserver.POST:
            log.log_history.clear()
        payload = ujson.dumps(log.log_history)
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
    global solar_manager
    solar_manager = solar.SolarManager()
    gmt, localt = utime.gmtime(), utime.localtime()
    assert gmt == localt
    server = webserver.Server(serve_request)
    server.static_path = b'/static/'
    log.garbage_collect()
    log.LOG_LEVEL = log.INFO
    try:
        light.on()
        uasyncio.run(server.run())
        uasyncio.run(solar_manager.loop_tasks())
    finally:
        uasyncio.run(server.close())
        _ = uasyncio.new_event_loop()



if __name__ == '__main__':
    main()

