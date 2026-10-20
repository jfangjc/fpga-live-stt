"""dc_gain: bit-exact against golden.dc_gain; DC rejection; gain clamp; saturation."""
import math
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from golden import dc_gain


async def setup(dut, gain):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.x.value = 0
    dut.gain_shift.value = gain
    await ClockCycles(dut.clk, 4)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def run(dut, xs, gain):
    await setup(dut, gain)
    out = []

    async def mon():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if int(dut.out_valid.value):
                out.append((dut.y.value.to_signed(), int(dut.sat.value)))

    cocotb.start_soon(mon())
    for x in xs:
        await FallingEdge(dut.clk)
        dut.x.value = x
        dut.in_valid.value = 1
        await FallingEdge(dut.clk)
        dut.in_valid.value = 0
    await ClockCycles(dut.clk, 4)
    want = dc_gain(xs, gain)
    assert len(out) == len(want)
    bad = [i for i, (a, b) in enumerate(zip(out, want)) if a != b]
    assert not bad, f"{len(bad)} mismatches, first at {bad[0]}: got {out[bad[0]]} want {want[bad[0]]}"
    return [y for y, _ in out]


@cocotb.test()
@cocotb.parametrize(gain=[0, 4, 8, 12])
async def test_random_bit_exact(dut, gain):
    rng = random.Random(gain)
    await run(dut, [rng.randint(-(1 << 19), (1 << 19) - 1) for _ in range(400)], gain)


@cocotb.test()
async def test_dc_rejection(dut):
    """A -0.1 FS offset (as on the snapshot's recording) plus a 1 kHz tone: DC gone after settling.

    Time constant is 2^K = 512 samples (32 ms at 16 kHz). The tail window starts at 12.5 tau,
    where the step has decayed to ~0.01 LSB, so what remains is the fixed-point bias.
    """
    dc = -int(0.1 * (1 << 17))
    xs = [dc + int(round(2000 * math.sin(2 * math.pi * 1000 * i / 16000))) for i in range(8000)]
    ys = await run(dut, xs, 0)
    tail = ys[-1600:]                              # 1600 samples = 100 whole tone periods
    mean = sum(tail) / len(tail)
    dut._log.info(f"residual DC after {len(xs)} samples: {mean:.3f} LSB (input offset {dc / 4:.0f} LSB at 16-bit scale)")
    assert abs(mean) < 0.5


@cocotb.test()
async def test_saturation(dut):
    xs = [0] * 4 + [(1 << 19) - 1] * 4 + [-(1 << 19)] * 4
    ys = await run(dut, xs, 8)
    assert 32767 in ys and -32768 in ys
