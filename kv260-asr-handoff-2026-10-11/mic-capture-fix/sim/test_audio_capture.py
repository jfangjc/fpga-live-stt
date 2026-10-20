"""audio_capture_axi end to end: two mics -> 48 kHz I2S -> FIR -> DC/gain -> CDC -> ring -> AXI-Lite.

Both real clocks run (24.576 MHz audio, 100 MHz AXI). Ring contents are compared bit for bit
with golden.pipeline() applied to exactly the samples the mic models transmitted.
"""
import math
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, Timer

from axil import OKAY, SLVERR, AxiLiteMaster
from golden import pipeline
from sph0645_bfm import Sph0645Bus, sample_stream

ID, CTRL, STATUS, DEPTH, WCNT, RCNT, FILL, OVR, SAT, CDC, THR, PARAMS = range(0, 48, 4)
RING = 0x8000
EN, IRQ_EN, CLEAR = 1 << 0, 1 << 1, 1 << 31


def ctrl(gain=4, enable=True, irq=False, clear=False):
    return (EN if enable else 0) | (IRQ_EN if irq else 0) | (gain << 8) | (CLEAR if clear else 0)


def speech_like(n, seed, dc):
    """Tones + noise + a large DC offset, as 18-bit samples (DC as on the real mic)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        t = i / 48000
        v = dc + 3000 * math.sin(2 * math.pi * 440 * t) + 1500 * math.sin(2 * math.pi * 2500 * t)
        v += 2000 * math.sin(2 * math.pi * 14000 * t) + rng.gauss(0, 300)   # 14 kHz must be filtered
        out.append(max(-(1 << 17), min((1 << 17) - 1, int(round(v)))))
    return out


async def setup(dut):
    cocotb.start_soon(Clock(dut.s_axi_aclk, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.aud_clk, 40690, unit="ps").start())
    dut.s_axi_aresetn.value = 0
    dut.aud_locked.value = 1
    dut.mic_data.value = 0
    axi = AxiLiteMaster(dut, dut.s_axi_aclk)
    await ClockCycles(dut.s_axi_aclk, 20)
    await FallingEdge(dut.s_axi_aclk)
    dut.s_axi_aresetn.value = 1
    await ClockCycles(dut.s_axi_aclk, 5)
    return axi


async def rd(axi, addr):
    data, resp = await axi.read(addr)
    assert resp == OKAY, f"read 0x{addr:x} returned SLVERR"
    return data


async def wait_frames(axi, n):
    while (await rd(axi, WCNT)) < n:
        await Timer(200, unit="us")


def start_mics(dut, n=4000, tdc_ns=40.0):
    return Sph0645Bus(dut.mic_bclk, dut.mic_ws, dut.mic_data,
                      left=sample_stream(speech_like(n, 1, dc=-13107)),     # -0.1 FS
                      right=sample_stream(speech_like(n, 2, dc=6000)),
                      tdc_ns=tdc_ns).start()


@cocotb.test()
async def test_registers(dut):
    axi = await setup(dut)
    assert await rd(axi, ID) == 0x41554431
    assert await rd(axi, DEPTH) == 8192
    assert await rd(axi, PARAMS) == (96 << 24) | (3 << 16) | (9 << 8) | 1
    assert await rd(axi, CTRL) == 4 << 8, "reset: disabled, gain 4"
    assert await rd(axi, THR) == 4000
    assert await axi.write(RCNT, 123) == OKAY and await rd(axi, RCNT) == 123
    assert await axi.write(THR, 77) == OKAY and await rd(axi, THR) == 77
    assert await axi.write(WCNT, 1) == SLVERR, "read-only register must reject writes"
    assert await axi.write(RING, 1) == SLVERR, "ring window is read-only"
    assert await axi.write(CTRL, 1, strb=0x1) == SLVERR, "partial writes rejected"
    assert (await axi.read(0x2))[1] == SLVERR, "unaligned read rejected"
    assert (await axi.read(0x100))[1] == SLVERR, "unmapped register space"
    assert int(dut.mic_bclk.value) == 0, "BCLK stopped while disabled"


@cocotb.test()
async def test_end_to_end_bit_exact(dut):
    """Ring words equal the golden pipeline of the transmitted samples, both channels, gain 4."""
    bus = start_mics(dut)
    axi = await setup(dut)
    await axi.write(CTRL, ctrl(gain=4))
    await wait_frames(axi, 48)
    w = await rd(axi, WCNT)
    words = [await rd(axi, RING + 4 * i) for i in range(w)]
    sent_l, sent_r = bus.sent[0], bus.sent[1]
    nfr = min(len(sent_l), len(sent_r))
    want, sats = pipeline(sent_l[:nfr], sent_r[:nfr], gain_shift=4)
    assert len(want) >= w
    bad = [i for i in range(w) if words[i] != want[i]]
    assert not bad, f"{len(bad)}/{w} mismatches, first at frame {bad[0]}: 0x{words[bad[0]]:08x} vs 0x{want[bad[0]]:08x}"
    assert await rd(axi, SAT) == sum(sats[:w])
    assert await rd(axi, CDC) == 0
    status = await rd(axi, STATUS)
    assert status & 0b100110 == 0, f"STATUS flags set: 0x{status:x}"   # overrun, cdc, fir_overlap
    assert bus.contention == 0
    dut._log.info(f"{w} stereo frames at 16 kHz matched bit-for-bit")


@cocotb.test()
async def test_irq_fill_and_overrun(dut):
    """IRQ on FILL >= threshold, cleared by advancing READ_CNT; overrun counted and sticky."""
    start_mics(dut)
    axi = await setup(dut)
    await axi.write(THR, 8)
    await axi.write(CTRL, ctrl(irq=True))
    await wait_frames(axi, 10)
    assert int(dut.irq.value) == 1
    assert await rd(axi, FILL) >= 8
    w = await rd(axi, WCNT)
    await axi.write(RCNT, w)
    await ClockCycles(dut.s_axi_aclk, 2)
    assert (await rd(axi, FILL)) < 8 and int(dut.irq.value) == 0

    # Pretend software is a whole ring behind: the next frame overwrites unread data.
    w = await rd(axi, WCNT)
    await axi.write(RCNT, (w - 8192) & 0xFFFFFFFF)
    await wait_frames(axi, w + 2)
    assert await rd(axi, OVR) >= 1
    assert (await rd(axi, STATUS)) & 0b10
    assert int(dut.irq.value) == 1, "overrun raises IRQ even below threshold"

    await axi.write(CTRL, ctrl(irq=True, clear=True))
    assert await rd(axi, OVR) == 0 and (await rd(axi, STATUS)) & 0b10 == 0
    assert await rd(axi, WCNT) <= 1


@cocotb.test()
async def test_disable_restart(dut):
    """Disabling stops BCLK and the producer; re-enabling restarts cleanly with no CDC drops."""
    start_mics(dut)
    axi = await setup(dut)
    await axi.write(CTRL, ctrl())
    await wait_frames(axi, 5)
    await axi.write(CTRL, ctrl(enable=False))
    await Timer(5, unit="us")
    w0 = await rd(axi, WCNT)
    await Timer(300, unit="us")
    assert await rd(axi, WCNT) == w0
    assert int(dut.mic_bclk.value) == 0
    await axi.write(CTRL, ctrl())
    await wait_frames(axi, w0 + 5)
    assert await rd(axi, CDC) == 0
