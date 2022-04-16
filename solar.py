import log
import uasyncio
import utime
import machine
import devices
import ujson

LOOP_TIC_SEC = 1
GC_PERIOD = 10
PANELS_PIN = 36
CHARGER_PIN = 39
PANELS_RESISTANCE = 22

resistance = devices.InvertedPin(PANELS_RESISTANCE, machine.Pin.OUT)

panels = machine.ADC(machine.Pin(PANELS_PIN))
panels.atten(machine.ADC.ATTN_11DB)
charger = machine.ADC(machine.Pin(CHARGER_PIN))
charger.atten(machine.ADC.ATTN_11DB)


class HistoryLog:
    def __init__(self, time_start=0):
        self.devices = dict(charger=charger, panels=panels)
        self.history = dict(charger=[], panels=[])
        self.detections = {}
        self.enabled = False
        self.max_size = 20
        self.period_tics = 1
        self.allow_set = set(('enabled', 'max_size', 'period_tics'))
        self.allow_get = self.allow_set | set(('history',))
        self.tics_count = -1 # So we start at zero on the first tic
        self.charger_threshold = 2000
        self.sample_size = 10
        self.save_period_sec = 60
        self.save_time = utime.time() - time_start
        self.memory_threshold = 30000

    def latest_read(self):
        chargerv = self.history['charger'][-1][0] if self.history['charger'] and self.enabled else charger.read()
        panelsv =  self.history['panels'][-1][0] if self.history['panels'] and self.enabled else panels.read()
        return dict(charger=chargerv, panels=panelsv)

    def set_json(self, cfg):
        for name, value in cfg.items():
            if name == 'enabled' and value != self.enabled:
                self.save_detections(force=True)
                self.detections.clear()
            if name in self.allow_set:
                setattr(self, name, value)

    def get_json(self):
        return {k:getattr(self,k) for k in self.allow_get}

    def collect_data(self, time):
        self.tics_count += 1
        if not self.enabled or self.tics_count % self.period_tics:
            if not self.enabled:
                log.debug('History disabled')
            return
        log.debug('Collecting devices...')
        for name, dev in self.devices.items():
            row = (dev.read(), time)
            log.debug('{}:{}',name,row)
            self.history[name].append(row)
            self.purge_old(name)
        self.detect()
        self.save_detections()

    def save_detections(self, force=False):
        if not self.detections:
            return
        _, time = self.history['charger'][-1]
        now_free = log.garbage_collect(self.memory_threshold)
        if (force
            or now_free < self.memory_threshold
            or time - self.save_time > self.save_period_sec):
            fname = 'detections_{}.json'.format(time)
            log.debug('Saving {} ...', fname)
            with open(fname, 'w') as fp:
                ujson.dump(self.detections, fp)
            self.save_time = time
            self.detections.clear()
            if (now_free < self.memory_threshold
                and log.garbage_collect(self.memory_threshold) > self.memory_threshold):
                log.error('Memory pressure problem.')

    def detect(self):
        if len(self.history['charger']) <= 1:
            log.debug('No enough information')
            return
        current, time = self.history['charger'][-1]
        previous, _ = self.history['charger'][-2]
        event_type = None
        if current <= self.charger_threshold:
            if  previous > self.charger_threshold:
                event_type = 'stop'
        elif previous <= self.charger_threshold:
            event_type = 'start'
        if event_type:
            log.info('Detected charger voltage change. {{current:{}, prev:{}, time:{}}}', current, previous, time)
            self.detections[time] = dict(charger=self.history['charger'][-self.sample_size:],
                                         panels=self.history['panels'][-self.sample_size:],
                                         event_type=event_type,
                                        )

    def purge_old(self, name):
        hist_lst = self.history[name]
        if len(hist_lst) >= self.max_size:
            log.debug('Purging {name} with len={length}', name=name, length=len(hist_lst))
            # let's remove a third of the list
            hist_lst[:self.max_size//3] = []


start = utime.time()
historylog = HistoryLog(start)
async def loop_tasks(threshold=1):
    assert threshold > 0
    log.garbage_collect()
    seconds = 0
    historylog.enabled = True
    while True:
        historylog.collect_data(utime.time() - start)
        await uasyncio.sleep(LOOP_TIC_SEC)
        seconds += LOOP_TIC_SEC
        if seconds // GC_PERIOD:
            seconds = seconds % GC_PERIOD
            log.garbage_collect()


def main():
    log.garbage_collect()
    log.LOG_LEVEL = log.DEBUG
    try:
        uasyncio.run(loop_tasks())
    finally:
        ...
        #_ = uasyncio.new_event_loop()


if __name__ == '__main__':
    main()
