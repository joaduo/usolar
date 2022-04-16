import log
import uasyncio
import utime
import machine
import devices

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
    def __init__(self):
        self.devices = dict(charger=charger, panels=panels)
        self.history = dict(charger=[], panels=[])
        self.enabled = False
        self.max_size = 10
        self.period_tics = 5
        self.allow_set = set(('enabled', 'max_size', 'period_tics'))
        self.allow_get = self.allow_set | set(('history',))
        self.tics_count = -1 # So we start at zero on the first tic

    def set_json(self, cfg):
        for name, value in cfg.items():
            if name in self.allow_set:
                setattr(self, name, value)

    def get_json(self):
        return {k:getattr(self,k) for k in self.allow_get}

    def collect_data(self):
        self.tics_count += 1
        if not self.enabled or self.tics_count % self.period_tics:
            if not self.enabled:
                log.debug('History disabled')
            return
        log.debug('Collecting devices...')
        for name, dev in self.devices.items():
            self.history[name].append((dev.read(), utime.localtime()))
            self.purge_old(name)
        
    def purge_old(self, name):
        hist_lst = self.history[name]
        if len(hist_lst) >= self.max_size:
            log.debug('Purging {name} with len={length}', name=name, length=len(hist_lst))
            # let's remove a third of the list
            hist_lst[:self.max_size//3] = []


historylog = HistoryLog()


async def loop_tasks(threshold=1):
    assert threshold > 0
    log.garbage_collect()
    seconds = 0
    while True:
        historylog.collect_data()
        await uasyncio.sleep(LOOP_TIC_SEC)
        seconds += LOOP_TIC_SEC
        if seconds // GC_PERIOD:
            seconds = seconds % GC_PERIOD
            log.garbage_collect()

