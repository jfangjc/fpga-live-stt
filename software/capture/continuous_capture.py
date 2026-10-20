"""Independent bounded capture process; never run inference on the FIFO reader."""
import argparse
import json
import queue
import threading
import time
import wave
from pathlib import Path
from kv260_voice import UIOMMIO, VoiceAccelerator


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', required=True)
    p.add_argument('--seconds', type=int, default=300)
    p.add_argument('--chunk-seconds', type=int, default=10)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.seconds <= 0 or a.chunk_seconds <= 0:
        p.error('durations must be positive')
    a.output.mkdir(parents=True, exist_ok=False)
    jobs = queue.Queue(maxsize=4)
    failures = []
    written = []

    def writer():
        while True:
            job = jobs.get()
            try:
                if job is None:
                    return
                index, data = job
                path = a.output / f'capture-{index:05d}.wav'
                with wave.open(str(path), 'wb') as f:
                    f.setnchannels(1)
                    f.setsampwidth(3)
                    f.setframerate(16000)
                    f.writeframes(data)
                written.append(path.name)
            except Exception as e:
                failures.append(str(e))
            finally:
                jobs.task_done()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    total = 0
    software_drops = 0
    data = bytearray()
    index = 0
    start = time.monotonic()
    with UIOMMIO(a.device) as mmio:
        core = VoiceAccelerator(mmio)
        core.read_audio(1024)
        before = core.audio_status()
        while total < a.seconds * 16000:
            if time.monotonic() - start > a.seconds + 30:
                failures.append('capture deadline exceeded')
                break
            samples = core.read_audio(min(1024, a.seconds * 16000 - total))
            total += len(samples)
            for sample in samples:
                data.extend(sample.to_bytes(3, 'little', signed=True))
            if len(data) >= a.chunk_seconds * 16000 * 3:
                chunk_bytes = a.chunk_seconds * 16000 * 3
                try:
                    jobs.put_nowait((index, bytes(data[:chunk_bytes])))
                except queue.Full:
                    software_drops += chunk_bytes // 3
                del data[:chunk_bytes]
                index += 1
            time.sleep(0.001)
        after = core.audio_status()
    if data:
        jobs.put((index, bytes(data)))
    jobs.put(None)
    jobs.join()
    thread.join()
    drops = (after['dropped'] - before['dropped']) & 0xffffffff
    report = dict(samples=total, sample_rate=16000,
                  elapsed_seconds=time.monotonic() - start,
                  before=before, after=after, newly_dropped_samples=drops,
                  software_dropped_samples=software_drops, errors=failures,
                  files=written, hardware_execution=True)
    report['passed'] = total == a.seconds * 16000 and not (drops or software_drops or failures)
    (a.output / 'capture.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
