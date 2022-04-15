import machine
import utime


class InvertedPin(machine.Pin):
    def on(self):
        if super().value():
            return super().off()
    def off(self):
        if not super().value():
            return super().on()
    def value(self, v=None):
        if v is not None:
            if v:
                self.on()
            else:
                self.off()
        return not bool(super().value())


