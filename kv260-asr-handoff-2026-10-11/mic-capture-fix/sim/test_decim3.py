"""decim3_fir: bit-exact against golden.decim3 for random, tone and full-scale input."""
import math
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

from golden import decim3

SPACING = 200       # clk between input frames (hardware has 512 at 24.576 MHz / 48 kHz)


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst.value = 1
    dut.in_valid.value = 0
    dut.in_l.value = 0
    dut.in_r.value = 0
    await ClockCycles(dut.clk, 4)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def monitor(dut, out):
    while True:
        await RisingEdge(dut.out_valid)
        await ReadOnly()
        out.append((dut.out_l.value.to_signed(), dut.out_r.value.to_signed()))


async def drive(dut, left, right, spacing=SPACING):
    for l, r in zip(left, right):
        await FallingEdge(dut.clk)
        dut.in_l.value = l
        dut.in_r.value = r
        dut.in_valid.value = 1
        await FallingEdge(dut.clk)
        dut.in_valid.value = 0
        await ClockCycles(dut.clk, spacing - 1)
    await ClockCycles(dut.clk, 300)


async def run_case(dut, left, right):
    await setup(dut)
    out = []
    cocotb.start_soon(monitor(dut, out))
    await drive(dut, left, right)
    want = list(zip(decim3(left), decim3(right)))
    assert len(out) == len(want) == len(left) // 3
    bad = [i for i, (a, b) in enumerate(zip(out, want)) if a != b]
    assert not bad, f"{len(bad)} mismatches, first at {bad[0]}: got {out[bad[0]]} want {want[bad[0]]}"
    assert int(dut.overlap_err.value) == 0


@cocotb.test()
async def test_random(dut):
    rng = random.Random(1)
    n = 360
    await run_case(dut, [rng.randint(-(1 << 17), (1 << 17) - 1) for _ in range(n)],
                   [rng.randint(-(1 << 17), (1 << 17) - 1) for _ in range(n)])


@cocotb.test()
async def test_tones(dut):
    """1 kHz passes, 12 kHz (aliases to 4 kHz) is rejected; also checked bit-exact."""
    n = 480
    a = 100000
    left = [int(round(a * math.sin(2 * math.pi * 1000 * i / 48000))) for i in range(n)]
    right = [int(round(a * math.sin(2 * math.pi * 12000 * i / 48000))) for i in range(n)]
    await run_case(dut, left, right)
    yl, yr = decim3(left)[60:], decim3(right)[60:]          # skip the 96-tap fill transient
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
    pass_db = 20 * math.log10(rms(yl) / (a / math.sqrt(2)))
    stop_db = 20 * math.log10(max(rms(yr), 1e-9) / (a / math.sqrt(2)))
    dut._log.info(f"1 kHz gain {pass_db:.3f} dB, 12 kHz gain {stop_db:.1f} dB")
    assert abs(pass_db) < 0.05
    assert stop_db < -55


@cocotb.test()
async def test_full_scale(dut):
    """Extremes and DC at full scale: exercises accumulator width and output saturation."""
    hi, lo = (1 << 17) - 1, -(1 << 17)
    left = [hi] * 150 + [lo] * 150
    right = [hi if (i // 2) % 2 else lo for i in range(300)]
    await run_case(dut, left, right)


@cocotb.test()
async def test_overlap_flag(dut):
    """Inputs faster than one dot product per 3 frames must raise the sticky overlap flag."""
    await setup(dut)
    await drive(dut, [1000] * 12, [-1000] * 12, spacing=40)
    assert int(dut.overlap_err.value) == 1
