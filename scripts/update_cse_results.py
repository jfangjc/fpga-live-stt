"""Render measured CSE results from completed physical reports."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / 'reports/fused' / name).read_text(encoding='utf-8'))


def main():
    long = read('context_cse_confirmation100.json')
    short = read('context_cse_short_confirmation100.json')
    smoke = read('cse_resident_smoke.json')
    assert long['complete'] and short['complete'] and smoke['complete']
    c = long['contexts'][0]
    rows = []
    for p in (short, long):
        for r in p['contexts']:
            lo, hi = r['mean_saving_95ci_seconds']
            rows.append(f"| {r['context_seconds']:g} s | {p['cpu_threads']} workers, {p['spin_duration_us']} us spin | "
                        f"{r['cpu_p50']*1000:.2f}/{r['cpu_p95']*1000:.2f} ms | "
                        f"{r['fpga_p50']*1000:.2f}/{r['fpga_p95']*1000:.2f} ms | {lo*1000:.2f} to {hi*1000:.2f} ms |")
    text = f'''# Validated graph and FPGA latency progress - 10 October 2026

The supplied 10-second recording now takes {c['fpga_p50']*1000:.2f} ms p50 and {c['fpga_p95']*1000:.2f} ms p95 on the physical FPGA hybrid. The matched optimized CPU takes {c['cpu_p50']*1000:.2f}/{c['cpu_p95']*1000:.2f} ms. The FPGA median advantage is {(1-c['fpga_p50']/c['cpu_p50'])*100:.2f}%. The stronger 20% reduction remains unmet.

## Independent physical confirmation

Each context has 100 randomized quartets: original CPU, original FPGA, simplified CPU and simplified FPGA. Three warmups precede measurement. CPU and FPGA use the same frontend, decoder, worker count, affinity and spin window. Main thread uses core 3; four-thread workers use 0/1/2. CPU screening tested one/two/four threads and zero/1,000-us spin for short inputs. These are the fastest measured CPU settings among tested configurations, not an exhaustive CPU optimization claim.

| Audio context | Policy, both paths | CPU p50/p95 | FPGA p50/p95 | Paired mean saving 95% CI |
|---|---|---|---|---|
{chr(10).join(rows)}

The half-second FPGA path remains slightly slower than CPU. Assess the one-second result from its independent report; neither prefix test establishes usable streaming accuracy. Citrinet remains noncausal and normalizes each input context. Prefixes are not scored against the full transcript.

Timing includes in-memory frontend, graph, WordPiece decode, all physical weight reloads, transfers and synchronization. Initialization, WAV reads, report writes and three-millisecond gaps between benchmark calls are outside the timer. CPU clocks remain at 1,333,333 kHz and FPGA clock reads 99,999,999 Hz. Raw environment/temperature and per-call counters are retained.

## Implemented optimization

The graph transformation proves shared symbolic shapes, deduplicates readonly initializers and eliminates exact duplicate pure operations. It reduces 5,109 nodes to 1,411 while retaining all 235 quantized convolutions. Quantization, weights, arithmetic, frontend and decoder remain unchanged. No hardware change is required.

Under the same independent 10-second quartet policy, original FPGA p50/p95 was {c['original_fpga_p50']*1000:.2f}/{c['original_fpga_p95']*1000:.2f} ms, versus {c['fpga_p50']*1000:.2f}/{c['fpga_p95']*1000:.2f} ms after simplification: {(1-c['fpga_p50']/c['original_fpga_p50'])*100:.2f}% lower median. CPU also improves from {c['original_cpu_p50']*1000:.2f} to {c['cpu_p50']*1000:.2f} ms; the shared software gain must not be attributed entirely to FPGA offload. Original/new CPU and original/new FPGA logits and lengths are exact in confirmation. FPGA initialization falls from {long['initialization_seconds']['original_fpga']:.2f} to {long['initialization_seconds']['fpga']:.2f} seconds.

Pinned scheduling removed the earlier one-second offload regression in screening. The public resident API now supports this validated graph, binds model/native/firmware/source/report identities, and restores caller affinity after initialization and every inference. CPU and FPGA each passed three measured API calls with matching text and encoded lengths; every FPGA call executed six physical operators and zero oracle operators. These calls are integration checks, not additional speed acceptance.

## Numerical and accuracy evidence

Host and ARM original/simplified CPU graphs produce exact logits and lengths on seven dynamic/batched cases. ARM verification also covers nine diagnostic WAV clips. Physical FPGA output matches the integer oracle exactly on all nine clips. CPU and FPGA both have 24 errors over 269 reference words, with zero percentage-point diagnostic degradation. This small diagnostic set is not a representative-corpus accuracy qualification.

The retained 512-MAC engine performs six native FPGA graph operators, with 12 ioctls per inference. On the 10-second input hardware active time is about 8.3 ms out of 464 ms total. Increasing MAC count cannot by itself deliver the needed whole-model saving.

## Rejected hardware experiment and next work

The separate 1,024-MAC build failed route_design with 1,288 node overlaps. No timing-closed bitstream or physical result exists; it was not activated. The verified 512-MAC, 100-MHz image remains deployed.

Next, define and validate complete retained depthwise/pointwise/mask/activation/residual blocks against the current UINT8/INT8 quantization contract, including global SE reductions, gate round trips and replay. Expand hardware only if a full block beats its optimized CPU equivalent with all transfers and synchronization included. Current results do not establish a 20% gain or low-latency live transcription. Capture remains deferred.

The historical 451-ms target came from an older CPU baseline on a different clip. A 20% reduction against this 10-second CPU result requires {c['cpu_p50']*.8*1000:.2f} ms p50 and {c['cpu_p95']*.8*1000:.2f} ms p95.

## Reproduction and preservation

Use software/latency/confirm_cse.py and scripts/run_cse_short_confirmation.sh. The resident API example in software/latency/README.md binds the completed long-input report. Restore the accepted six-operator base, then the separate CSE overlay; cse-package.json lists and verifies every file and archive hash. Earlier snapshots are preserved.

Primary evidence: reports/fused/context_cse_confirmation100.json, context_cse_short_confirmation100.json, cse_host_validation.json, cse_arm_validation.json, cse_physical_validation.json and cse_resident_smoke.json. The rejected hardware log is build/quad_system/Prototype_v3_quad.runs/impl_1/runme.log.
'''
    (ROOT / 'CSE_RESULTS.md').write_text(text, encoding='utf-8')
    intro = (f"Latest validated graph optimization: on the supplied 10-second input, physical FPGA p50/p95 is "
             f"{c['fpga_p50']*1000:.2f}/{c['fpga_p95']*1000:.2f} ms versus matched optimized CPU "
             f"{c['cpu_p50']*1000:.2f}/{c['cpu_p95']*1000:.2f} ms. The common graph optimization also benefits CPU. "
             "See CSE_RESULTS.md for independent short-context results, exact numerical checks, preservation and limitations. "
             "The 1,024-MAC build failed routing and was not deployed. Capture remains deferred; the stronger 20% goal is unmet.\n\n")
    for name in ('LATENCY_RESULTS.md', 'RESULTS_V3.md', 'PLAN_V3.md'):
        p = ROOT / name
        old = p.read_text(encoding='utf-8')
        p.write_text(intro + 'Earlier milestone retained below for history:\n\n' + old, encoding='utf-8')
    (ROOT / 'LIVE_PLAN.md').write_text('''# Current inference-performance scope - 10 October 2026

Capture is deferred. Optimize resident frontend, graph and decoder latency on identical audio already in memory. Prefix text remains provisional because this checkpoint is noncausal and normalizes each input context. Latest physical results and numerical evidence are in CSE_RESULTS.md.

The verified 512-MAC, 100-MHz image remains active. Six native graph operators execute physically. Hardware errors propagate. Accepted six-operator and earlier latency snapshots remain preserved.

Next work:

1. Use the simplified graph as the common CPU/FPGA baseline. Separate shared software gains from the incremental hardware advantage. Include weight reloads and transfers; track initialization separately. Screen CPU settings before independent physical confirmation.
2. Define complete retained depthwise/pointwise/mask/activation/residual blocks against the current UINT8 activation, INT8 weight and INT32 bias contract. Validate numerical behavior and diagnostic accuracy before RTL. Measure global SE reductions, gates and replay explicitly.
3. Build one complete physical block. Expand only after it beats optimized CPU including every transfer, synchronization and weight load, and projects sufficient total savings.
4. Reject the unrouted 1,024-MAC experiment for deployment. It failed with 1,288 node overlaps. FPGA active time is about 8.3 ms out of 464 ms total; more MACs alone cannot meet the stronger 20% reduction.
5. Re-screen a checkpoint if retained blocks cannot meet latency and accuracy together, using its own best measured CPU baseline.

Recompute thresholds from the current CPU and input; the historical 451-ms target belongs to a different clip and older implementation. No representative-corpus qualification or live-transcription result is claimed.
''', encoding='utf-8')


if __name__ == '__main__':
    main()
