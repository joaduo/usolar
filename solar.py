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
PV_10V = 120
PV_12V = 460
PV_13V = 630
PV_16V = 1200
# Invertr USB port voltage (from 1.5v (off) to 0.5v (on))
# integer value: like 30 for 0.5v and like 1700 to 1800 for 1.5v
INVERTER_USB_THRESHOLD = 850 # integer measurement is ~1750 for 1.5v in inverter usb terminal


class TrackerBase:
    def run_tic(self, time):
        pass

    def reset(self):
        pass


class ResistanceTracker(TrackerBase):
    # How much to hold with the resistance off (since last time on)
    HOLD_DISABLED = 60 * 3
    # How much to hold with the resistance on (since last time off)
    HOLD_ENABLED = 60 * 60

    OSCILLATING = 'oscillating'
    SUNRISE = 'sunrise'
    SUNRISE_PREVENT = 'sunrise_prevent'
    SUNSET = 'sunset'
    HIGHVOLTAGE = 'highvoltage'
    HIGHVOLTAGE_OSC = 'highvoltage_oscillating'

    def __init__(self, manager, panels_tracker, inverter_tracker):
        self.manager = manager
        self.resistance = manager.devices['resistance']
        self.panels_tracker = panels_tracker
        self.inverter_tracker = inverter_tracker
        self.reset()

    def reset(self):
        self.status_reason = ''
        self.switch_time = 0

    def run_tic(self, time):
        if not self.is_on():
            if self.inverter_tracker.is_oscillating(time, self.switch_time):
                delta = time - self.switch_time
                if not self.switch_time or delta > self.HOLD_DISABLED:
                    log.info('Turning resistance on due to oscillations')
                    self.resistance.on()
                    self.status_reason = self.OSCILLATING
                    self.switch_time = time
                else:
                    log.error('Oscillating even with resistance ON {} secs ago (HOLD_DISABLED={} secs)',
                              delta, self.HOLD_DISABLED)
            elif not self.inverter_tracker.is_on():
                voltage = self.panels_tracker.get_voltage()
                if PV_10V < voltage < PV_12V:
                    log.info('Turning resistance to prevent oscillations')
                    self.resistance.on()
                    self.status_reason = self.SUNRISE_PREVENT
                    self.switch_time = time
        else:
            voltage = self.panels_tracker.get_voltage()
            if voltage > PV_12V:
                reason = self.SUNRISE
                if voltage > PV_16V:
                    log.warning('Voltage high even with load...')
                    reason = self.HIGHVOLTAGE
                if self.inverter_tracker.is_oscillating(time, self.switch_time):
                    log.warning('Release with high voltage, nevertheless inverter still oscillating')
                    reason = self.HIGHVOLTAGE_OSC
                log.info('Releasing resistance, there is enough power. reason={}', reason)
                self.resistance.off()
                self.status_reason = reason
                self.switch_time = time
            elif voltage < PV_10V and time - self.switch_time > self.HOLD_ENABLED:
                log.info('Releasing resistance, seems its night')
                self.resistance.off()
                self.status_reason = self.SUNSET
                self.switch_time = time

    def is_on(self):
        return self.resistance.value()


class PanelsTracker(TrackerBase):
    def __init__(self, manager):
        self.manager = manager
        self.sample_size = 10

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


class InverterTracker(TrackerBase):
    # Deltas between starts and stops
    DELTA_MIN = 2 #seconds
    DELTA_MAX = 120 #seconds
    START_TYPE = 'start'
    STOP_TYPE = 'stop'
    # Max detections size
    detections_size = 10

    def __init__(self, manager):
        self.manager = manager
        self.detections = []
        self.sample_size = 4

    def reset(self):
        self.detections.clear()

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
        self.purge_old(self.detections_size)

    def purge_old(self, detections_size=10):
        if len(self.detections) >= detections_size:
            log.debug('Purging detections with len={}', len(self.detections))
            # let's remove a third of the list
            self.detections[:detections_size//3] = []

    def is_oscillating(self, time, check_since=None):
        check_since = check_since or time - self.DELTA_MAX
        if len(self.detections) <= 1:
            log.debug('No enough information')
            return
        prev1 = self.detections[-1]
        prev2 = self.detections[-2]
        if prev1['event_type'] == prev2['event_type']:
            log.error('2 even_types equal. Something may be wrong!')
            return
        if prev1['time'] >= check_since:
            delta_events = prev1['time'] - prev2['time']
            is_stop = prev1['event_type'] == self.STOP_TYPE
            if delta_events <= self.DELTA_MAX:
                if is_stop and delta_events < self.DELTA_MIN:
                    log.error('Something may be wrong, less than {} seconds between events', self.DELTA_MIN)
                    return
                return True
        log.debug('Latest event outside scope. Event time={} secs event_type={}', prev1['time'], prev1['event_type'])

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
        self.history_size = 20
        self.period_tics = 1
        self.allow_set = set(('enabled', 'history_size', 'period_tics',
                              'inverter_tracker__detections_size'))
        self.allow_get = self.allow_set | set(('history',))
        self.tics_count = -1 # So we start at zero on the first tic
        self.charger_threshold = INVERTER_USB_THRESHOLD
        self.sample_size = 10
        self.save_time = utime.time() - self.start_time
        self.memory_threshold = 30000
        self.stop = False

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
        self.inverter_tracker = inverter_tracker
        self.resistance_tracker = resistance_tracker

    async def loop_tasks(self, threshold=1):
        assert threshold > 0
        log.garbage_collect()
        seconds = 0
        runners = [self] + self.trackers
        while not self.stop:
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
            self.purge_old(name, self.history_size)

    def reset(self):
        for v in self.history.values():
            v.clear()
        for t in self.trackers:
            t.reset()

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
            obj = self
            if name in self.allow_set:
                attrs = name.split('__')
                for n in attrs[:-1]:
                    obj = getattr(obj, n)
                setattr(obj, attrs[-1], value)

    def get_json(self):
        json_dict = {}
        for name in self.allow_get:
            obj = self
            attrs = name.split('__')
            for n in attrs[:-1]:
                obj = getattr(obj, n)
            json_dict[name] = getattr(obj, attrs[-1])
        return json_dict

    def get_resistance(self):
        return bool(self.devices['resistance'].value())

    def set_resistance(self, value):
        if value:
            self.devices['resistance'].on()
        else:
            self.devices['resistance'].off()
        return self.get_resistance()

    def purge_old(self, name, history_size):
        hist_lst = self.history[name]
        length = len(hist_lst)
        if length >= history_size:
            log.debug('Purging {} with len={}', name, length)
            # let's remove a third of the list
            hist_lst[:max(history_size//3, length - history_size)] = []

    def latest_read(self):
        reads = {}
        for n, dev in self.devices.items():
            reads[n] = self.history[n][-1][0] if self.history[n] and self.enabled else self._device_value(dev)
        return reads


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


