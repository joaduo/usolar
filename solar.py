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


# PV input is connected to a optocoupler.
# We have gradient between 10 and 16V (below 0, above saturated)
# This range is fine for our purposes. We want to release the resistance if above 16V
PV_10V = 80
PV_10V_LOAD = 10
PV_16V = 1200
PV_16V_LOAD = 1100
# Invertr USB port voltage (from 1.5v (off) to 0.5v (on))
# integer value: like 30 for 0.5v and like 1700 to 1800 for 1.5v
INVERTER_USB_THRESHOLD = 1000 # integer measurement is ~1750 for 1.5v in inverter usb terminal 


class ResistanceTracker:
    HOLD_SWITCH_DELTA = 60 * 60

    OSCILLATING = 'oscillating'
    SUNRISE = 'sunrise'
    SUNSET = 'sunset'
    HIGHVOLTAGE = 'highvoltage'
    HIGHVOLTAGE_OSC = 'highvoltage_oscillating'

    def __init__(self, manager, panels_tracker, inverter_tracker):
        self.manager = manager
        self.resistance = manager.devices['resistance']
        self.panels_tracker = panels_tracker
        self.inverter_tracker = inverter_tracker
        self.switch_time = 0
        self.status_reason = ''

    def run_tic(self, time):
        if not self.is_on():
            if self.inverter_tracker.is_oscillating(time):
                delta = time - self.switch_time
                if not self.switch_time or delta < self.HOLD_SWITCH_DELTA:
                    log.info('Turning resistance on delta={}', delta)
                    self.resistance.on()
                    self.status_reason = self.OSCILLATING
                    self.switch_time = time
                else:
                    log.error('Oscillating even with resistance ON {} secs ago', delta)
        else:
            voltage = self.panels_tracker.get_voltage()
            if voltage > PV_16V_LOAD:
                reason = self.SUNRISE
                if voltage > PV_16V:
                    log.warning('Voltage high even with load...')
                    reason = self.HIGHVOLTAGE
                if self.inverter_tracker.is_oscillating(time):
                    log.warning('Release with high voltage, nevertheless inverter still oscillating')
                    reason = self.HIGHVOLTAGE_OSC
                log.info('Releasing resistance, there is enough power. reason={}', reason)
                self.resistance.off()
                self.status_reason = reason
                self.switch_time = time
            elif voltage < PV_10V and time - self.switch_time > self.HOLD_SWITCH_DELTA:
                log.info('Releasing resistance, seems its night')
                self.resistance.off()
                self.status_reason = self.SUNSET
                self.switch_time = time

    def is_on(self):
        return self.resistance.value()


class PanelsTracker:
    def __init__(self, manager):
        self.manager = manager
        self.sample_size = 10

    def run_tic(self, time):
        pass

    def get_voltage(self, force_read=False):
        if not force_read and self.manager.enabled and self.manager.history['panels']:
            return self.manager.history['panels'][-1][0]
        else:
            value = self.manager.devices['panels'].read()
            return  value

    def voltage_delta(self, min_history=10):
        if not self.manager.enabled or not len(self.manager.history['panels']) >= min_history:
            log.debug('History log disabled or not enough info...')
            return 0
        panels_hist = [v for v,_ in self.manager.history['panels'][-self.sample_size:]]
        negative_count = 0
        positive_count = 0
        cur = panels_hist[0]
        for nxt in panels_hist[1:]:
            delta = nxt - cur
            positive_count += int(delta > 0)
            negative_count += int(delta < 0)
        total_delta = panels_hist[-1] - panels_hist[0]
        if positive_count > negative_count and total_delta > 0:
            return total_delta
        elif positive_count < negative_count and total_delta < 0:
            return total_delta
        else:
            return 0


class InverterTracker:
    # Deltas between starts and stops
    DELTA_MIN = 20 #seconds
    DELTA_MAX = 120 #seconds
    START_TYPE = 'start'
    STOP_TYPE = 'stop'

    def __init__(self, manager):
        self.manager = manager
        self.detections = []
        self.sample_size = 4
        self.max_size = 10

    def run_tic(self, time):
        usb_hist = self.manager.history['inverter_usb']
        if len(usb_hist) <= 1:
            log.debug('No enough information')
            return
        current, event_time = usb_hist[-1]
        previous, _ = usb_hist[-2]
        event_type = None
        # Note that voltage is inverse: 1.5 when off and 0.5 when on
        if current >= INVERTER_USB_THRESHOLD:
            if  previous < INVERTER_USB_THRESHOLD:
                # now above threshold (on and previous below (off))
                event_type = self.STOP_TYPE
        elif previous >= INVERTER_USB_THRESHOLD:
            event_type = self.START_TYPE
        if event_type:
            log.info('inverter_usb voltage change.'
                     ' current={}, prev={}, time={}, event_type={}',
                     current, previous, time, event_type)
            self.detections.append(dict(inverter_usb=usb_hist[-self.sample_size:],
                                        panels=self.manager.history['panels'][-self.sample_size:],
                                        ac_enabled=self.manager.history['ac_enabled'][-self.sample_size:],
                                        resistance=self.manager.history['resistance'][-self.sample_size:],
                                        event_type=event_type,
                                        event_time=event_time,
                                        time=time,
                                        ))
        self.purge_old(self.max_size)

    def purge_old(self, max_size):
        if len(self.detections) >= max_size:
            log.debug('Purging detections with len={}', len(self.detections))
            # let's remove a third of the list
            self.detections[:max_size//3] = []

    def is_oscillating(self, time):
        if len(self.detections) <= 1:
            log.debug('No enough information')
            return
        prev1 = self.detections[-1]
        prev2 = self.detections[-2]
        if prev1['event_type'] == prev2['event_type']:
            log.error('2 even_types equal. Something may be wrong!')
            return
        since_detect = time - prev1['time']
        if since_detect <= self.DELTA_MAX:
            delta_events = prev1['time'] - prev2['time']
            is_stop = prev1['event_type'] == self.STOP_TYPE
            if delta_events <= self.DELTA_MAX:
                if is_stop and delta_events < self.DELTA_MIN:
                    log.error('Something may be wrong, less than {} seconds between events', self.DELTA_MIN)
                    return
                return True
        log.debug('Outside oscillating range since_detect={} secs', since_detect)

    def is_on(self, force_read=False):
        if not force_read and self.manager.enabled and self.detections:
            return self.detections[-1]['event_type'] == self.START_TYPE
        else:
            value = self.manager.devices['inverter_usb'].read()
            if not value:
                log.warning('Inverter USB cable seems disconnected...')
            # if value es cero, then it's disconnected
            return  0 < value < INVERTER_USB_THRESHOLD


class SolarManager:
    start_time = utime.time()

    def __init__(self):
        self.init_devices()
        self.init_trackers()
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
        self.save_time = utime.time() - self.start_time
        self.memory_threshold = 30000

    def init_devices(self):
        # 10W resistance to load PV when sunrise or sunset
        resistance = devices.InvertedPin(RESISTANCE_PIN, machine.Pin.OUT)
        resistance.off()
        # button logic (with a 220v relay) when inverter AC output is on
        ac_enabled = devices.InvertedPin(AC_ENABLED_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        # ADC measurement of PV voltage (behing optocoupler)
        panels = machine.ADC(machine.Pin(PANELS_PIN))
        panels.atten(machine.ADC.ATTN_11DB)
        # Invertr USB port voltage (from 1.5v (off) to 0.5v (on))
        # integer value: like 30 for 0.5v and like 1700 to 1800 for 1.5v 
        inverter_usb = machine.ADC(machine.Pin(INVERTER_USB_PIN))
        inverter_usb.atten(machine.ADC.ATTN_11DB)
        self.devices = dict(
                    ac_enabled=ac_enabled,
                    inverter_usb=inverter_usb,
                    panels=panels,
                    resistance=resistance,
                    )

    def init_trackers(self):
        inverter_tracker = InverterTracker(self)
        panels_tracker = PanelsTracker(self)
        resistance_tracker = ResistanceTracker(self, panels_tracker, inverter_tracker)
        self.trackers = [inverter_tracker, panels_tracker, resistance_tracker]

    async def loop_tasks(self, threshold=1):
        assert threshold > 0
        log.garbage_collect()
        seconds = 0
        runners = [self] + self.trackers
        while True:
            if self.enabled:
                time = utime.time() - self.start_time
                for r in runners:
                    r.run_tic(time)
            else:
                log.debug('SolarManager disabled')
            await uasyncio.sleep(LOOP_TIC_SEC)
            seconds += LOOP_TIC_SEC
            if seconds // GC_PERIOD:
                seconds = seconds % GC_PERIOD
                log.garbage_collect()

    def run_tic(self, time):
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
            self.purge_old(name, self.max_size)

    def get_values(self):
        values = {}
        for n, dev in self.devices.items():
            values[n] = (self.history[n][-1][0]
                           if self.history[n] and self.enabled
                           else self._device_value(dev))
        return values

    def _device_value(self, dev):
        if isinstance(dev, machine.ADC):
            return dev.read()
        else:
            return dev.value()

    def set_json(self, cfg):
        for name, value in cfg.items():
            if name in self.allow_set:
                setattr(self, name, value)

    def get_json(self):
        return {k:getattr(self,k) for k in self.allow_get}

    def set_resistance(self, value):
        if value:
            self.devices['resistance'].on()
        else:
            self.devices['resistance'].off()
        return self.devices['resistance'].value()

    def purge_old(self, name, max_size):
        hist_lst = self.history[name]
        if len(hist_lst) >= max_size:
            log.debug('Purging {} with len={}', name, len(hist_lst))
            # let's remove a third of the list
            hist_lst[:max_size//3] = []


def main():
    log.garbage_collect()
    log.LOG_LEVEL = log.INFO
    manager = SolarManager()
    manager.enabled = True
    try:
        uasyncio.run(manager.loop_tasks())
    finally:
        ...
        #_ = uasyncio.new_event_loop()


if __name__ == '__main__':
    main()


