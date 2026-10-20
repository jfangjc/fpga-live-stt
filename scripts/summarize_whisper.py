"""Write the result runbook from completed, gated board evidence."""
import argparse
import json
from pathlib import Path
import wave
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    a = ap.parse_args()
    q = json.loads((a.work/'qualification.json').read_text())
    if not q['prototype_gates_passed']:
        raise RuntimeError('Prototype evidence gates have not passed')
    timing = json.loads((a.work/'latency_results/results.json').read_text())
    validation = json.loads((a.work/'validation_results/results.json').read_text())
    identity = q.get('model','openai/whisper-base')
    short = identity.removeprefix('openai/whisper-')
    reporting = 'whisper-turbo' if short=='large-v3-turbo' else 'whisper'
    reference_note = (['CPU accuracy references were reused after verifying identical CPU executables,',
        'shared libraries, model and WAV identities; hybrid accuracy was rerun after',
        'the final decoder-buffer optimization. Latency uses fresh paired runs.']
        if 'cpu_reference_reuse' in validation else ['All CPU and hybrid accuracy references use the final model and runtime.'])
    lines = [f'# Whisper {short} prototype results — {datetime.now(timezone.utc):%Y-%m-%d} UTC','',
        'The KV260 prototype passes its measured 2x processing-latency gate and the',
        f'small English accuracy gate. It uses multilingual Whisper {short} with Q8 source',
        'weights and physical INT8 encoder/attention matrix execution on the preserved',
        '`asr-v3-bulk` image at 100 MHz. Autoregressive decoding runs on the CPU.','',
        '## Repeated complete transcription','',
        f'{timing["repeats"]} measured runs per configuration per clip; {timing["warmup"]} excluded warmup run(s).',
        'FP16, Q8_0 and Q5_0 CPU runs are randomized with hybrid runs. All use four CPU',
        'threads, unfused attention, English greedy decoding, no temperature fallback',
        'and no timestamps. The CPU column selects the fastest measured CPU format',
        'separately for each clip.','',
        '| Audio | Best CPU | CPU p50 | Hybrid p50 | Speedup | CPU p95 | Hybrid p95 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for source,row in zip(timing['clips'],q['latency']):
        with wave.open(source['audio']) as wav:
            seconds = wav.getnframes()/wav.getframerate()
        model = ['FP16','Q8_0','Q5_0'][int(row['best_cpu'].split('_')[1])]
        lines.append(f'| {seconds:.3f} s | {model} | {row["cpu"]["p50_seconds"]:.3f} s | '
                     f'{row["hybrid"]["p50_seconds"]:.3f} s | {row["speedup_p50"]:.3f}x | '
                     f'{row["cpu"]["p95_seconds"]:.3f} s | {row["hybrid"]["p95_seconds"]:.3f} s |')
    accuracy = q['accuracy']
    lines += ['',
        'Timings include CLI process startup, model loading, WAV I/O, frontend,',
        'first-use weight preparation, CPU operations, FPGA weight transfers, DMA',
        'synchronization and token decoding. FPGA application activation/restoration',
        'is a separate deployment cost. p95 is descriptive with only three samples.',
        'These are measurements of the pinned whisper.cpp runtime; other CPU engines',
        'and different decoding policies were not compared.','',
        '## Ten-speaker accuracy sample','',
        f'The separate sample contains {accuracy["clips"]} speakers/clips and {accuracy["reference_words"]} reference words',
        'from LibriSpeech test-clean. Seeded selection excludes the speaker used for',
        'engineering optimization and the preserved calibration speaker. No speech',
        'calibration or training is required by the dynamic quantizer.',*reference_note,'',
        '| Execution | Word errors | Reference words | WER |','|---|---:|---:|---:|']
    for name,label in [('cpu_0_no_flash','FP16 CPU'),('cpu_1_no_flash','Q8_0 CPU'),('cpu_2_no_flash','Q5_0 CPU'),('hybrid','FPGA hybrid')]:
        if name not in accuracy['totals']:
            continue
        row = accuracy['totals'][name]
        lines.append(f'| {label} | {row["word_errors"]} | {row["reference_words"]} | {100*row["wer"]:.3f}% |')
    lines += ['',
        f'The prototype criterion permits at most {100*accuracy["maximum_allowed_increase"]:.1f} percentage point WER increase',
        f'over FP16; the measured increase is {100*accuracy["absolute_wer_increase"]:.3f} points. Normalization is',
        'lowercase alphanumeric words with internal apostrophes. This small sample',
        'does not qualify multilingual, noisy, microphone or production accuracy.','',
        '## Physical evidence and operation','',
        'Exact raw INT32 and per-column FP32 transport checks passed, including',
        'INT8 extremes, partial dimensions, packet batches, nearest-even ties, zero',
        'columns, strided buffers, four-worker output and NaN rejection before DMA.',
        'All measured hybrid runs require positive physical matrix and attention',
        'counters; failures propagate. The session records verify board restoration.','',
        f'- [Bound qualification report](../reports/{reporting}/qualification.json)',
        f'- [Repeated timings and transcripts](../reports/{reporting}/latency_results/results.json)',
        f'- [Ten-speaker timings and transcripts](../reports/{reporting}/validation_results/results.json)',
        f'- [Word-error counts](../reports/{reporting}/validation_wer.json)',
        f'- [Exact physical conformance](../reports/{reporting}/parallel_conformance.json)',
        f'- [Build, partition and board commands]({"WHISPER_TURBO.md" if short=="large-v3-turbo" else "WHISPER_MIGRATION.md"})','',
        'Whisper.cpp is pinned to `2eeeba56e9edd762b4b38467bab96c2517163158`.',
        'Model, binaries, shared libraries, WAVs and evidence have SHA256 identities.',
        'The runtime package additionally binds every distributed file in its manifest.',
        'The original Citrinet release and bitstreams remain preserved.','',
        'LibriSpeech attribution: Vassil Panayotov, Guoguo Chen, Daniel Povey and',
        'Sanjeev Khudanpur, ICASSP 2015. Data is distributed under CC BY 4.0;',
        'see [OpenSLR 12](https://www.openslr.org/12/) and packaged sample provenance.','']
    a.out.write_text('\n'.join(lines),encoding='utf-8')
    print(a.out)


if __name__ == '__main__':
    main()
