"""Generate short-input results from the final physical deployment proofs."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def read(name):return json.loads((ROOT/'reports/fused'/name).read_text(encoding='utf-8'))


def main():
    profiles=[read('short_half_second_deployment.json'),read('short_one_second_irq3_deployment.json')]
    assert all(p['complete'] for p in profiles)
    old=read('context_cse_short_confirmation100.json')
    table=[]
    for p in profiles:
        c=p['contexts'][0]; seconds=c['context_seconds']
        previous=next(r for r in old['contexts'] if r['context_seconds']==seconds)
        table.append(f"| {seconds:g} s | {previous['fpga_p50']*1000:.2f}/{previous['fpga_p95']*1000:.2f} ms | "
                     f"{c['fpga_p50']*1000:.2f}/{c['fpga_p95']*1000:.2f} ms | "
                     f"{c['cpu_p50']*1000:.2f}/{c['cpu_p95']*1000:.2f} ms | {p['runs']} |")
    text=f'''# Short-input latency milestone - 10 October 2026

The resident FPGA path is faster on short inputs after removing padded feature frames and selecting an offload profile for each context. The verified 512-MAC, 100-MHz firmware and native library remain unchanged. Capture remains deferred.

| Audio length | Previous FPGA p50/p95 | New FPGA p50/p95 | Matched CPU p50/p95 | Independent pairs |
|---|---|---|---|---|
{chr(10).join(table)}

The previous/new FPGA comparison uses separate cohorts; the CPU/FPGA comparisons within each new cohort are randomized paired measurements. The half-second median FPGA improvement is approximately 4.0%; the one-second improvement is approximately 3.7%. These include shared software improvements that also benefit CPU. The additional FPGA advantage is small: approximately 0.35% at half a second and 1.33% at one second. The one-second p95 is effectively tied with CPU and is 0.033 ms higher; do not claim a tail-latency FPGA win there. A separate CPU-only half-second policy test reached 68.56 ms p50, nearly tied with the 68.53-ms FPGA result. No substantial short-input hardware speedup or 20% reduction is established.

## Implemented profiles

Both profiles use the existing exact waveform frontend, checkpoint, INT8 quantization and WordPiece decoder. After frontend normalization, frames beyond the valid length are verified zero and removed. The half-second input changes from 64 padded frames to 51 valid frames; one second changes from 112 to 101. The inference graph remains dynamic, so the resident interface can handle other input lengths without compiling a graph each call. The source frontend and checkpoint are preserved.

The half-second profile offloads only /encoder/encoder.1/mconv.6/conv/Conv_quant. The FPGA retains its weights across consecutive calls: one physical call, one ioctl, zero warm loads and zero oracle calls. This replaces six physical calls, 12 ioctls and six weight reloads. Residency can be displaced by another FPGA graph; the first call and any resulting reload remain real costs and are not hidden. Use one active profile for repeated short windows.

The one-second profile keeps the accepted six physical layers. CPU and FPGA use the same four threads, main core 3, worker cores 0/1/2, 10-microsecond worker spin window and backoff 8. DMA interrupts are explicitly placed on core 3 at startup. This profile requires that configuration, which the API verifies during initialization. The interrupt experiment restored its original settings afterwards. Configuration is a startup action, outside warm processing time; it is not changed during each call.

The half-second profile uses four pinned threads without spinning and the original DMA configuration. Worker screening compared 0/10/25/50/100/250/500 microseconds and separately confirmed 0 versus 10 on trimmed inputs with 100 randomized CPU runs. Shorter/longer windows were not assumed beneficial. One/two/four worker counts were screened in the preceding milestone; four were fastest for these contexts among tested policies.

## Validation and measurement limits

Each selected offload profile passed nine full diagnostic clips and 27 prefixes at 0.25/0.5/1 second. Original and trimmed CPU valid logits differ by at most 5.73e-6, within rtol 1e-5 and atol 1e-4. CPU transcript and encoded length are unchanged. Physical FPGA and its integer oracle match exactly. The original CPU, trimmed CPU and FPGA all have 24 errors over 269 full-clip reference words, with zero diagnostic WER degradation. Prefixes are not scored against full transcripts; the corpus is not representative accuracy qualification.

The half-second confirmation has 100 randomized CPU/FPGA pairs. Its paired mean saving 95% confidence interval is 0.124 to 0.811 ms. The selected one-second profile received a fresh 300-pair confirmation after interrupt-placement screening; its interval is 0.975 to 1.639 ms. Clocks, temperatures, phase times, transfer bytes and hardware counters are retained per report. Three warmups precede measurement. Three-millisecond inter-call idle gaps, input file reads, initialization and report writes are outside the timer. Processing includes frontend, trimming, graph, decoder, all weight reloads, transfers and synchronization.

The public resident API checks graph/model/native/firmware/validation identities, applies the measured worker policy, and restores caller affinity. Integration tests exercise 0.25/0.5/1-second input, CPU/FPGA text and length agreement, hardware residency, invalid-input rejection and compatibility with the prior long-input profile. These API calls are smoke checks, not speed acceptance.

Fixed shapes alone were rejected because latency regressed. Freezing exact feature lengths also failed to show useful improvement and introduced tiny floating-point differences. Interrupt placement did not establish an additional half-second benefit. No unvalidated static graph replaces the dynamic deployment.

## Use and preservation

Use reports/fused/short_half_second_deployment.json for repeated half-second processing. For one-second processing, configure DMA core 3 explicitly and use short_one_second_irq3_deployment.json. See software/latency/README.md for commands. The benchmark determines the worker/padding/hardware policy; backend selection is explicit and hardware errors propagate.

The existing six-operator and CSE snapshots remain immutable. The new Downloads milestone is an overlay: extract the six-operator base, then the CSE overlay, then this short-input overlay. Its manifest binds every source, graph, raw report and archive hash. The active hardware remains the verified bulk image; the failed 1,024-MAC design is not used.

The checkpoint remains noncausal and normalizes each input context. These measurements support lower resident processing latency for future work; they do not establish stable live transcription, capture behavior or representative prefix accuracy. The next substantial hardware opportunity remains complete retained convolution blocks, including depthwise operations and explicit global SE handling.
'''
    (ROOT/'SHORT_INPUT_RESULTS.md').write_text(text,encoding='utf-8')
    path=ROOT/'LIVE_PLAN.md'
    old_plan=path.read_text(encoding='utf-8')
    path.write_text('Latest short-input milestone: physical FPGA p50 is 68.53 ms at 0.5 s and 103.18 ms at 1 s. '
                    'CPU receives the same padding and scheduling optimization; hardware gains remain small. '
                    'One-second p95 is tied with CPU. See SHORT_INPUT_RESULTS.md for profiles, 100/300-pair proofs and startup configuration.\n\n'+old_plan,encoding='utf-8')


if __name__=='__main__':main()
