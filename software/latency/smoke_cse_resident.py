"""Exercise the deployed resident API and verify caller affinity restoration."""
import json
import os
from pathlib import Path
from resident import ResidentTranscriber, ROOT, read_audio, sha


def main():
    proof = ROOT / 'reports/fused/context_cse_confirmation100.json'
    audio = read_audio(ROOT / 'research/eval/user-recording/speech.wav')
    initial = os.sched_getaffinity(0)
    results = {}
    for backend in ('cpu', 'fpga'):
        runner = ResidentTranscriber(proof, backend)
        assert os.sched_getaffinity(0) == initial
        for _ in range(3):
            runner.transcribe(audio)
        rows = []
        for _ in range(3):
            row = runner.transcribe(audio)
            assert os.sched_getaffinity(0) == initial
            if backend == 'fpga':
                assert row['fpga_counters']['physical_calls'] == len(runner.nodes)
                assert row['fpga_counters']['oracle_calls'] == 0
            rows.append(row)
        results[backend] = {'initialization_seconds': runner.initialization_seconds, 'calls': rows}
        del runner
    assert {r['text'] for b in results.values() for r in b['calls']}.__len__() == 1
    assert len({r['encoded_length'] for b in results.values() for r in b['calls']}) == 1
    report = {'complete': True, 'scope': 'Resident API smoke test; not speed acceptance',
              'caller_affinity_restored': True, 'caller_affinity': sorted(initial),
              'benchmark_sha256': sha(proof), 'resident_source_sha256': sha(Path(__file__).with_name('resident.py')),
              'smoke_source_sha256': sha(__file__), 'results': results}
    out = ROOT / 'reports/fused/cse_resident_smoke.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'results'}), flush=True)


if __name__ == '__main__':
    main()
