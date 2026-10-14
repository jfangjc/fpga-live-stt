#!/usr/bin/env python3
"""Record ten seconds of raw PCM24; run beside kv260_voice.py on the board."""
import argparse
import math
import time
import wave
from kv260_voice import UIOMMIO, VoiceAccelerator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/uio4')
    parser.add_argument('--output', default='speech.wav')
    args = parser.parse_args()
    samples = []
    with UIOMMIO(args.device) as mmio:
        core = VoiceAccelerator(mmio)
        core.read_audio(1024)  # Discard the old setup backlog.
        before = core.audio_status()
        started = time.monotonic()
        while len(samples) < 160000:
            if time.monotonic() - started > 20:
                raise RuntimeError('Timed out waiting for ten seconds of audio')
            samples.extend(core.read_audio(min(1024, 160000 - len(samples))))
            time.sleep(0.001)
        elapsed = time.monotonic() - started
        after = core.audio_status()
    drops = (after['dropped'] - before['dropped']) & 0xffffffff
    with wave.open(args.output, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(3)
        output.setframerate(16000)
        output.writeframes(b''.join(s.to_bytes(3, 'little', signed=True) for s in samples))
    mean = sum(samples) / len(samples)
    rms = math.sqrt(sum((s - mean) ** 2 for s in samples) / len(samples))
    dbfs = 20 * math.log10(rms / (1 << 23)) if rms else float('-inf')
    print(f'Saved {args.output}: {len(samples)} samples in {elapsed:.3f}s')
    print(f'New dropped frames: {drops}; range: {min(samples)} .. {max(samples)}')
    print(f'DC mean: {mean:.1f}; AC RMS: {dbfs:.1f} dBFS')
    print('Listen to the WAV to verify speech. No gain or DC correction was applied.')
    if drops:
        raise SystemExit('Recording contains discontinuities from dropped frames')


if __name__ == '__main__':
    main()
