import uasyncio
import ujson
import machine
import utime
import log
import webserver
import solar
import config


def stream_web_log():
    for l in reversed(log.web_log_history):
        msg = l[2].format(*l[3], **l[4])
        yield '{}:{}: {}\n'.format(l[0], log.INT_TO_LABEL[l[1]], msg)

def stream_web_log_frequency():
    for k in sorted(log.web_log_frequency):
        v = log.web_log_frequency[k]
        yield '{}:{}: {}: {}\n'.format(v['last_seen'], log.INT_TO_LABEL[v['level']], k, v['count'])

wifi_tracker = solar.WifiTracker(config.AP_WIFI_ESSID, config.AP_WIFI_PASSWORD)
solar_manager = solar.SolarManager(wifi_tracker)
app = webserver.Server(static_path='/static/',
                       auth_token=config.AUTH_TOKEN,
                       pre_request_hook=lambda: uasyncio.create_task(wifi_tracker.blink()))

@app.json()
def devicesread(verb, _):
    return solar_manager.latest_read()

@app.json()
def history(verb, cfg):
    if verb == webserver.POST:
        solar_manager.set_json(cfg)
    return solar_manager.get_json()

@app.json()
def resistance(verb, _):
    value = solar_manager.get_resistance()
    if verb == webserver.POST:
        value = solar_manager.set_resistance(not value)
    return dict(value=value)

@app.json()
def reset(verb, _):
    if verb == webserver.POST:
        solar_manager.reset()
        log.web_log_history.clear()
        log.web_log_frequency.clear()
        log.important('Resetting server status...')
    return ''

@app.json()
def logcfg(verb, cfg):
    if verb == webserver.POST:
        log.LOG_LEVEL = cfg.get('log_level', log.LOG_LEVEL)
        log.WEB_LOG_LEVEL = cfg.get('web_log_level', log.WEB_LOG_LEVEL)
        log.WEB_LOG_SIZE = cfg.get('web_log_size', log.WEB_LOG_SIZE)
    return dict(log_level=log.LOG_LEVEL,
                web_log_level=log.WEB_LOG_LEVEL,
                web_log_size=log.WEB_LOG_SIZE)

@app.json()
def wifioff(verb, _):
    v = False
    if verb == webserver.POST:
        wifi_tracker.schedule_toggle = True
        v = True
    return dict(wifioff=v)

@app.plain()
def logs(verb, _):
    return stream_web_log()

@app.plain()
def logfrequency(verb, _):
    return stream_web_log_frequency()

@app.html('/')
def index(verb, _):
    return webserver.serve_file('/client.html', {'@=SERVER_ADDRESS=@':'',
                                                 '@=AUTH_TOKEN=@':config.AUTH_TOKEN})

def main():
    gmt, localt = utime.gmtime(), utime.localtime()
    assert gmt == localt
    log.garbage_collect()
    log.LOG_LEVEL = log.INFO
    try:
        wifi_tracker.on()
        uasyncio.run(app.run())
        uasyncio.run(solar_manager.loop_tasks())
    finally:
        uasyncio.run(app.close())
        _ = uasyncio.new_event_loop()
    wifi_tracker.off()

if __name__ == '__main__':
    main()

