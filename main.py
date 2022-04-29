import uasyncio
import ujson
import machine
import utime
import log
import webserver
import solar
import config


async def serve_request(verb, path, request_trailer):
    log.debug(path)
    uasyncio.create_task(wifi_tracker.blink())
    content_type = 'application/json'
    status = 200
    if path == '/devicesread':
        payload = ujson.dumps(solar_manager.latest_read())
    elif path == '/history':
        if verb == webserver.POST:
            cfg = await webserver.extract_json(request_trailer)
            solar_manager.set_json(cfg)
        payload = ujson.dumps(solar_manager.get_json())
    elif path == '/resistance':
        value = solar_manager.get_resistance()
        if verb == webserver.POST:
            value = solar_manager.set_resistance(not value)
        payload = ujson.dumps(dict(value=value))
    elif path == '/reset':
        if verb == webserver.POST:
            solar_manager.reset()
            log.web_log_history.clear()
            log.web_log_frequency.clear()
            log.important('Resetting server status...')
        payload = ujson.dumps('')
    elif path == '/logcfg':
        if verb == webserver.POST:
            cfg = await webserver.extract_json(request_trailer)
            log.LOG_LEVEL = cfg.get('log_level', log.LOG_LEVEL)
            log.WEB_LOG_LEVEL = cfg.get('web_log_level', log.WEB_LOG_LEVEL)
            log.WEB_LOG_SIZE = cfg.get('web_log_size', log.WEB_LOG_SIZE)
        payload = ujson.dumps(dict(log_level=log.LOG_LEVEL,
                                   web_log_level=log.WEB_LOG_LEVEL,
                                   web_log_size=log.WEB_LOG_SIZE))
    elif path == '/log':
        if verb == webserver.POST:
            log.web_log_history.clear()
            log.web_log_frequency.clear()
        payload = ujson.dumps(dict(log=log.web_log_history, frequency=log.web_log_frequency))
    elif path == '/wifioff':
        v = False
        if verb == webserver.POST:
            wifi_tracker.schedule_toggle = True
            v = True
        payload = ujson.dumps(dict(wifioff=v))
    else:
        content_type = 'text/html'
        if path == '/':
            resp = webserver.response(status, content_type, '')
            return resp, webserver.serve_file('/client.html', {'@=SERVER_ADDRESS=@':''})
        else:
            status = 404
            payload = webserver.web_page('404 Not found')
    return webserver.response(status, content_type, payload)


solar_manager = None
wifi_tracker = None
def main():
    global solar_manager, wifi_tracker
    wifi_tracker = solar.WifiTracker(config.AP_WIFI_ESSID, config.AP_WIFI_PASSWORD)
    solar_manager = solar.SolarManager(wifi_tracker)
    gmt, localt = utime.gmtime(), utime.localtime()
    assert gmt == localt
    server = webserver.Server(serve_request)
    server.static_path = '/static/'
    log.garbage_collect()
    log.LOG_LEVEL = log.INFO
    try:
        wifi_tracker.on()
        uasyncio.run(server.run())
        uasyncio.run(solar_manager.loop_tasks())
    finally:
        uasyncio.run(server.close())
        _ = uasyncio.new_event_loop()
    wifi_tracker.off()



if __name__ == '__main__':
    main()

