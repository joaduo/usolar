import log
import uasyncio
import utime
import machine
import devices
import ujson


LOOP_TIC_SEC = 1
GC_PERIOD = 10
PANELS_PIN = 39
INVERTER_USB_PIN = 36
AC_ENABLED_PIN = 12
RESISTANCE_PIN = 22 #10W 56 Ohm resistence (connected to the panels output)


# 10W resistance to load PV when sunrise or sunset
resistance = devices.InvertedPin(RESISTANCE_PIN, machine.Pin.OUT)
# button logic (with a 220v relay) when inverter AC output is on
ac_enabled = devices.InvertedPin(AC_ENABLED_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
# PV voltage reading. Like 730 on 14v (may go up to 50v)
PANELS_MAX_V = 730 # integer measurement of ~14volts with resistance on (off is like 830)
panels = machine.ADC(machine.Pin(PANELS_PIN))
panels.atten(machine.ADC.ATTN_11DB)
# Invertr USB port voltage (from 1.5v (off) to 0.5v (on))
# integer value: like 30 for 0.5v and like 1700 to 1800 for 1.5v
INVERTER_USB_THRESHOLD = 1000 # integer measurement is ~1750 for 1.5v in inverter usb terminal 
inverter_usb = machine.ADC(machine.Pin(INVERTER_USB_PIN))
inverter_usb.atten(machine.ADC.ATTN_11DB)


class HistoryLog:
    def __init__(self, time_start=0):
        self.devices = dict(
                            ac_enabled=ac_enabled,
                            inverter_usb=inverter_usb,
                            panels=panels
                            )
        self.history = {n:[] for n in self.devices}
        self.detections = {}
        self.enabled = False
        self.max_size = 20
        self.period_tics = 1
        self.save_period_sec = 60
        self.allow_set = set(('enabled', 'max_size', 'period_tics', 'save_period_sec'))
        self.allow_get = self.allow_set | set(('history',))
        self.tics_count = -1 # So we start at zero on the first tic
        self.charger_threshold = INVERTER_USB_THRESHOLD
        self.sample_size = 10
        self.save_time = utime.time() - time_start
        self.memory_threshold = 30000

    def latest_read(self):
        voltages = {}
        for n, dev in self.devices.items():
            voltages[n] = self.history[n][-1][0] if self.history[n] and self.enabled else self._device_value(dev)
        return voltages

    def _device_value(self, dev):
        if isinstance(dev, machine.ADC):
            return dev.read()
        else:
            return dev.value()

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
            row = (self._device_value(dev), time)
            log.info('{}:{}',name,row)
            self.history[name].append(row)
            self.purge_old(name)
        self.detect()
        self.save_detections()

    def save_detections(self, force=False):
        if not self.detections:
            return
        _, time = self.history['inverter_usb'][-1]
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
        if len(self.history['inverter_usb']) <= 1:
            log.debug('No enough information')
            return
        current, time = self.history['inverter_usb'][-1]
        previous, _ = self.history['inverter_usb'][-2]
        event_type = None
        # Note that voltage is inverse 1.5 when off and 0.5 when on
        if current >= self.charger_threshold:
            if  previous < self.charger_threshold:
                # now above threshold (on and previous below (off))
                event_type = 'stop'
        elif previous >= self.charger_threshold:
            event_type = 'start'
        if event_type:
            log.info('Detected inverter_usb voltage change. {{current:{}, prev:{}, time:{}}}', current, previous, time)
            self.detections[time] = dict(inverter_usb=self.history['inverter_usb'][-self.sample_size:],
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
    while True:
        historylog.collect_data(utime.time() - start)
        await uasyncio.sleep(LOOP_TIC_SEC)
        seconds += LOOP_TIC_SEC
        if seconds // GC_PERIOD:
            seconds = seconds % GC_PERIOD
            log.garbage_collect()


def main():
    log.garbage_collect()
    log.LOG_LEVEL = log.INFO
    resistance.off()
    try:
        uasyncio.run(loop_tasks())
    finally:
        ...
        #_ = uasyncio.new_event_loop()


if __name__ == '__main__':
    main()

