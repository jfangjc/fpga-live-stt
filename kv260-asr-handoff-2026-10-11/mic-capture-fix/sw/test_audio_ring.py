"""Reader logic against a fake device (pytest, runs on the Mac)."""
from audio_ring import CTRL, DEPTH, ID, MAGIC, RCNT, RING, WCNT, AudioRing


class FakeRing:
    def __init__(self, depth=64):
        self.depth = depth
        self.mem = [0] * depth
        self.w = 0
        self.regs = {ID: MAGIC, DEPTH: depth, WCNT: 0, RCNT: 0, CTRL: 0}
        self.lap_during_read = 0

    def produce(self, n):
        for _ in range(n):
            i = self.w
            self.mem[i % self.depth] = ((-(i % 1000)) & 0xFFFF) << 16 | (i & 0x7FFF)
            self.w = (self.w + 1) & 0xFFFFFFFF
        self.regs[WCNT] = self.w

    def read32(self, off):
        return self.regs.get(off, 0)

    def write32(self, off, v):
        self.regs[off] = v

    def read_block(self, off, n):
        out = [self.mem[(off - RING) // 4 + k] for k in range(n)]
        if self.lap_during_read:
            self.produce(self.lap_during_read)
            self.lap_during_read = 0
        return out


def expected(i):
    return i & 0x7FFF, -(i % 1000)


def test_reads_in_order_and_publishes_read_count():
    dev = FakeRing()
    r = AudioRing(dev)
    dev.produce(10)
    left, right, lost = r.read()
    assert lost == 0 and len(left) == 10
    assert list(zip(left, right)) == [expected(i) for i in range(10)]
    assert dev.regs[RCNT] == 10


def test_wraps_around_the_ring():
    dev = FakeRing(depth=64)
    r = AudioRing(dev)
    dev.produce(50)
    r.read()
    dev.produce(40)                       # crosses the end of the ring
    left, right, lost = r.read()
    assert lost == 0
    assert list(zip(left, right)) == [expected(i) for i in range(50, 90)]


def test_falling_behind_counts_lost_frames():
    dev = FakeRing(depth=64)
    r = AudioRing(dev)
    dev.produce(200)
    left, right, lost = r.read()
    assert r.safety == 16
    assert lost == 200 - (64 - r.safety)
    assert len(left) == 64 - r.safety
    first = 200 - len(left)
    assert list(zip(left, right)) == [expected(i) for i in range(first, 200)]


def test_writer_lapping_during_read_is_dropped():
    dev = FakeRing(depth=64)
    r = AudioRing(dev)
    dev.produce(32)
    dev.lap_during_read = 40              # writer gets 40 frames ahead while we copy
    left, _, lost = r.read()
    assert lost == (32 + 40) - 64
    assert len(left) == 32 - lost


def test_counter_wraps_at_32_bits():
    dev = FakeRing(depth=64)
    dev.w = 0xFFFFFFF0
    dev.regs[WCNT] = dev.w
    r = AudioRing(dev)
    r.rcount = 0xFFFFFFF0
    dev.produce(32)
    left, _, lost = r.read()
    assert lost == 0 and len(left) == 32 and r.rcount == 0x10
