#!/usr/bin/env python3
"""Short physical-board test, after loader verifies clock/AFI/UIO bindings."""
import sys
import time
from kv260_voice import UIOMMIO, VoiceAccelerator


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 board_smoke.py /dev/uioX")
    with UIOMMIO(sys.argv[1]) as mmio:
        core = VoiceAccelerator(mmio)
        result = core.dot([-128, 127, -1], [127, -128, -128])
        if result != -32384:
            raise RuntimeError(f"Signed dot mismatch: {result}, expected -32384")
        print("PASS: physical accelerator signed dot =", result)
        before = core.audio_status()
        # Drain setup backlog, then service the FIFO for a short sample window.
        core.read_audio(1024)
        samples = []
        deadline = time.monotonic() + 0.5
        while len(samples) < 160 and time.monotonic() < deadline:
            samples.extend(core.read_audio(160 - len(samples)))
            time.sleep(0.001)
        after = core.audio_status()
        captured = (after["captured"] - before["captured"]) & 0xffffffff
        if len(samples) != 160 or captured == 0:
            raise RuntimeError(f"Capture engine did not advance: {len(samples)} samples, {captured} frames")
        print("PASS: capture engine delivered 160 PCM24 samples")
        print("PCM24 range:", min(samples), max(samples))
        print("First 16 samples:", samples[:16])
        print("Audio status:", after)
        if before["overflow"] or after["overflow"]:
            print("Setup overflow is sticky until reload/reset. This short test is not an audio-loss measurement.")
        print("Microphone wiring/speech quality and full QuartzNet ASR remain separate tests.")


if __name__ == "__main__":
    main()
