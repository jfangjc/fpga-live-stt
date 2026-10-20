"""i2s_rx_stereo: clock spec, stereo capture across the t_DC range, sampling-point margin."""
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from sph0645_bfm import Sph0645Bus, sample_stream

AUD_PERIOD_PS = 40690          # 24.576 MHz
N_FRAMES = 12


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, AUD_PERIOD_PS, unit="ps").start())
    dut.rst.value = 1
    dut.mic_data.value = 0
    await ClockCycles(dut.clk, 4)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def collect(dut, n):
    frames = []
    while len(frames) < n:
        await RisingEdge(dut.valid)
        await ReadOnly()
        frames.append((dut.left.value.to_signed(), dut.right.value.to_signed()))
    return frames


def rand18(rng, n):
    return [rng.randint(-(1 << 17), (1 << 17) - 1) for _ in range(n)]


@cocotb.test()
async def test_clock_spec(dut):
    """BCLK must sit inside the datasheet's 2.048-4.096 MHz window with ~50 % duty; WS = BCLK/64."""
    await setup(dut)
    rises = []
    for _ in range(9):
        await RisingEdge(dut.mic_bclk)
        rises.append(get_sim_time(unit="ps"))
    await FallingEdge(dut.mic_bclk)
    fall = get_sim_time(unit="ps")
    period = (rises[-1] - rises[0]) / 8
    f_mhz = 1e6 / period
    duty = (fall - rises[-1]) / period
    dut._log.info(f"BCLK {f_mhz:.4f} MHz, duty {duty:.3f}")
    assert 2.048 <= f_mhz <= 4.096, f"BCLK {f_mhz} MHz outside SPH0645 datasheet range"
    assert abs(f_mhz - 3.072) < 0.01
    assert abs(duty - 0.5) < 0.01
    await FallingEdge(dut.mic_ws)
    t0 = get_sim_time(unit="ps")
    await FallingEdge(dut.mic_ws)
    ws_period = get_sim_time(unit="ps") - t0
    assert abs(ws_period / period - 64) < 1e-6, "WS must be BCLK/64 (fixed 64x oversampling)"
    dut._log.info(f"frame rate {1e12 / ws_period:.1f} Hz")


@cocotb.test()
@cocotb.parametrize(tdc_ns=[0.0, 30.0, 66.0, 100.0, 150.0])
async def test_stereo_capture(dut, tdc_ns):
    """Two mics (SELECT=0/1) on one DATA line; every frame captured exactly for t_DC 0..150 ns."""
    rng = random.Random(int(tdc_ns) + 1)
    bus = Sph0645Bus(dut.mic_bclk, dut.mic_ws, dut.mic_data,
                     left=sample_stream(rand18(rng, 64)), right=sample_stream(rand18(rng, 64)),
                     tdc_ns=tdc_ns).start()
    await setup(dut)
    got = await collect(dut, N_FRAMES)
    bus.stop()
    want = list(zip(bus.sent[0], bus.sent[1]))[:N_FRAMES]
    assert bus.contention == 0, "two mics drove DATA at once"
    assert got == want, f"t_DC={tdc_ns} ns: first mismatch at {next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)}"
    assert int(dut.frames.value) >= N_FRAMES


@cocotb.test()
async def test_sampling_point_margin(dut):
    """Data that changes after the sampling point (t_DC = 200 ns > 162.8 ns) must be mis-captured.

    This pins the sampling instant: the design samples 162.8 ns after the BCLK rise, so it
    tolerates t_DC up to ~160 ns, against a datasheet maximum of ~66 ns.
    """
    rng = random.Random(7)
    bus = Sph0645Bus(dut.mic_bclk, dut.mic_ws, dut.mic_data,
                     left=sample_stream(rand18(rng, 64)), right=sample_stream(rand18(rng, 64)),
                     tdc_ns=200.0).start()
    await setup(dut)
    got = await collect(dut, 6)
    bus.stop()
    want = list(zip(bus.sent[0], bus.sent[1]))[:6]
    assert got != want, "capture should fail when DATA changes after the sampling point"


@cocotb.test()
async def test_single_mic_left(dut):
    """Only the SELECT=0 mic fitted: left is exact, right reads the pull-down (0)."""
    rng = random.Random(3)
    bus = Sph0645Bus(dut.mic_bclk, dut.mic_ws, dut.mic_data,
                     left=sample_stream(rand18(rng, 32)), right=None, tdc_ns=40.0).start()
    await setup(dut)
    got = await collect(dut, 8)
    bus.stop()
    assert [g[0] for g in got] == bus.sent[0][:8]
    assert all(g[1] == 0 for g in got)
