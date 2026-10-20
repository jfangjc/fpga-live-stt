"""Bus-functional model of up to two Knowles SPH0645LM4H mics sharing one I2S DATA line.

Datasheet behaviour modelled:
- SELECT=0 mic drives DATA while WS=0, SELECT=1 mic while WS=1; tri-state otherwise.
- After WS enters a mic's level, the first rising BCLK edge is the I2S delay bit; the next 24
  rising edges launch bits 23..0 (MSB first), each t_DC after the edge; then zeros.
- 18-bit precision: an 18-bit sample is sent as sample << 6.
- The shared line has a pull-down (datasheet recommends 100 k), so an undriven line reads 0.
Bus contention (two mics driving at once) is counted and must stay zero.
"""
import cocotb
from cocotb.triggers import RisingEdge, Timer


class Sph0645Bus:
    def __init__(self, bclk, ws, data, left=None, right=None, tdc_ns=30.0):
        self.bclk, self.ws, self.data = bclk, ws, data
        self.src = {0: left, 1: right}          # iterators of 18-bit signed ints, or None
        self.sent = {0: [], 1: []}               # samples actually latched for transmission
        self.contention = 0
        self.tdc_ns = tdc_ns
        self._bit = {0: None, 1: None}
        self._word = {0: 0, 1: 0}
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self):
        if self._task is not None:
            self._task.cancel()

    def _drive_value(self, sel, ws, entered):
        if self.src[sel] is None or ws != sel:
            self._bit[sel] = None
            return None
        if entered:                               # delay-bit period: latch the next sample
            sample = next(self.src[sel])
            self.sent[sel].append(sample)
            self._word[sel] = (sample << 6) & 0xFFFFFF
            self._bit[sel] = 23
            return 0
        b = self._bit[sel]
        if b is None or b < 0:
            return 0
        self._bit[sel] = b - 1
        return (self._word[sel] >> b) & 1

    async def _run(self):
        prev_ws = None
        while True:
            await RisingEdge(self.bclk)
            ws = int(self.ws.value)
            entered = prev_ws is not None and ws != prev_ws
            drives = [v for v in (self._drive_value(0, ws, entered), self._drive_value(1, ws, entered)) if v is not None]
            if len(drives) > 1:
                self.contention += 1
            value = drives[0] if drives else 0
            prev_ws = ws
            if self.tdc_ns > 0:
                await Timer(self.tdc_ns, unit="ns")
            self.data.value = value


def sample_stream(values):
    """Turn a list into an endless iterator (pads with zeros after the list)."""
    for v in values:
        yield v
    while True:
        yield 0
