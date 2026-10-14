"""Summarize completed board screens without treating INT8 as the only CPU baseline."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    rows=[];proofs={}
    for size in (512,1024):
        suffix='safe_bulk_screen' if size==512 else 'bulk_screen'
        bulk=json.loads((ROOT/f'reports/fused/citrinet{size}_{suffix}.json').read_text())
        fp32=json.loads((ROOT/f'reports/fused/citrinet{size}_fp32_screen.json').read_text())
        assert bulk['complete'] and fp32['complete']
        directory='citrinet-512-ls' if size==512 else 'citrinet-1024-gamma-0.25'
        model_dir=ROOT/'research/export'/directory
        assert bulk['model_sha256']==sha(model_dir/'cpu-int8-safe.onnx')
        assert fp32['model_sha256']==sha(model_dir/'model.onnx')
        q=json.loads((model_dir/'cpu-int8-safe.json').read_text());assert q['regression_within_one_pp']
        assert q['model_sha256']==bulk['model_sha256'] and q['source_identity']['model.onnx']==fp32['model_sha256']
        for context in bulk['contexts']:
            c=context['context_seconds'];candidates=[]
            for label,report in [('INT8',bulk),('FP32',fp32)]:
                for policy in report['cpu_policies']:
                    r=next(r for r in policy['contexts'] if r['context_seconds']==c)
                    candidates.append((r['p50'],label,policy['threads']))
            candidates.append((context['cpu_p50'],'INT8 paired',context['threads']))
            fastest,precision,threads=min(candidates)
            rows.append({'model':size,'context_seconds':c,'fastest_tested_cpu_p50_ms':fastest*1000,
                         'cpu_precision':precision,'cpu_threads':threads,'fpga_bulk_p50_ms':context['fpga_p50']*1000,
                         'speedup_vs_fastest_tested_cpu':fastest/context['fpga_p50'],
                         'physical_oracle_bit_exact':context['physical_oracle_bit_exact'],
                         'cpu_fpga_transcript_equal':context['ort_cpu_same_text']})
        validation=json.loads((ROOT/'research/export'/directory/'nemo_validation.json').read_text())
        assert validation['status']=='pass' and validation['model_sha256']==fp32['model_sha256']
        proofs[str(size)]={'original_nemo_validation':validation,'physical_report':bulk,'fp32_report':fp32}
    report={'complete':True,'screening_only':True,'rows':rows,'evidence':proofs,
            'limitations':['FPGA path is existing 100 MHz bulk pointwise offload; qualified 256-channel fused path was not widened.',
                          'Only 15 warm pairs per length; CPU policy screen covers 1/2/4 threads without spinning.',
                          'Physical exactness is against the FPGA arithmetic oracle. Standard ORT INT8 logits may differ.',
                          'Five-clip regression is not representative WER qualification; user reference is incomplete/unconfirmed.',
                          'No live capture or streaming accuracy qualification.']}
    audits=json.loads((ROOT/'reports/fused/larger_citrinet_safe_graph_audit.json').read_text())
    assert all(not r['unsafe_quantized_bias_nodes'] and not r['unsafe_int32_accumulator_nodes'] for r in audits)
    report['safe_graph_audit']=audits
    source_paths=['scripts/acquire_larger_citrinet.py','scripts/audit_larger_citrinet.py',
                  'scripts/summarize_larger_citrinet.py','scripts/validate_larger_citrinet_batch.py','scripts/capture_larger_citrinet_board_state.py',
                  'software/model-tools/export_larger_citrinet.py','software/model-tools/quantize_larger_citrinet.py',
                  'software/model-tools/validate_larger_nemo.py','software/model-tools/larger_tokenizer.py',
                  'software/latency/benchmark_larger_citrinet.py']
    report['sources_sha256']={p:sha(ROOT/p) for p in source_paths}
    report['export_artifacts_sha256']={}
    for directory in ('citrinet-512-ls','citrinet-1024-gamma-0.25'):
        for name in ('model.onnx','cpu-int8-safe.onnx','frontend.npz','vocab.txt','tokenizer.model'):
            p=ROOT/'research/export'/directory/name
            if p.exists():report['export_artifacts_sha256'][p.relative_to(ROOT).as_posix()]=sha(p)
    state=json.loads((ROOT/'reports/fused/larger_citrinet_board_state.json').read_text())
    assert state['complete']
    for p in ('software/latency/benchmark_larger_citrinet.py','software/model-tools/larger_tokenizer.py'):
        assert state['sources_sha256'][p]==sha(ROOT/p)
    for proof in proofs.values():
        assert proof['physical_report']['library_sha256']==state['sources_sha256']['software/ort_fpga_bulk/libort_fpga.so']
        assert proof['physical_report']['firmware_sha256']==state['firmware_sha256']
    report['board_state']=state
    path=ROOT/'reports/fused/larger_citrinet_summary.json';path.write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Larger Citrinet board screening — 2026-10-15','',
           'Both requested model widths were tested on the KV260. These are screening measurements of the existing 100 MHz bulk pointwise FPGA path. The qualified Citrinet-256 retained-block implementation is unchanged.','',
           'The 512 checkpoint is NVIDIA `stt_en_citrinet_512_ls` (~36M exported initializer elements). The available 1024 checkpoint is `stt_en_citrinet_1024_gamma_0_25` (~141M); NVIDIA\'s inspected 1024-LS repository had no weights. Its different training and kernel configuration prevent treating this as a controlled width-only accuracy comparison.','',
           '| Model | Audio | Fastest tested CPU p50 | FPGA hybrid p50 | CPU / hybrid |',
           '|---|---:|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['model']} | {r['context_seconds']:g} s | {r['fastest_tested_cpu_p50_ms']:.1f} ms | {r['fpga_bulk_p50_ms']:.1f} ms | {r['speedup_vs_fastest_tested_cpu']:.3f}x |")
    lines+=['','A ratio greater than 1 means FPGA is faster. CPU selection includes FP32 and safe calibrated INT8, with 1/2/4 threads, plus alternating paired CPU timings. There are 15 paired warm samples per length. Each inference includes frontend, model, decoder, FPGA weight reloads, transfers and synchronization; file reading and session creation are excluded. The input is the same user-recording prefix for each length.','',
            'Result: the 512 bulk path is essentially tied with CPU at 2.5 seconds and slower on short inputs. The 1024 bulk path reduces latency by about 6.2% at 2.5 seconds but is slower on short inputs. Neither is a replacement for the optimized 256 implementation for the present low-latency goal. The next larger-model acceleration experiment should extend retained fused blocks, starting with 512 channels, rather than expanding individual-layer bulk offload.','',
            '## Correctness and limits','',
            'Both FP32 exports pass the complete original NeMo wrapper check on the user recording and one LibriSpeech recording: frontend, valid lengths, tokenizer mapping, frame predictions and decoded text. The 512 decoder is WordPiece; the 1024 decoder uses its exact SentencePiece model.','',
            'Both safe INT8 candidates have 2 word errors across 157 reference words in the five-clip LibriSpeech regression set, matching their FP32 comparators. This is not representative corpus qualification. The user-supplied reference is brief and completeness is unconfirmed.','',
            'Physical FPGA outputs are checked against the integer arithmetic oracle at all three input lengths and remain exact across timed repeats. Standard ORT INT8 logit differences and transcript comparisons are recorded separately; FPGA/oracle parity does not imply FP32 accuracy parity.','',
            'Both accepted INT8 graphs use a minimum real quantization range of 0.01 and pass conservative INT32 accumulator-bound checks. Initial quantization attempts are retained as rejected experiments, not deployment candidates.','',
            'The existing retained-block compiler and firmware explicitly require 256-channel stages. This test reuses the bulk engine for supported wider pointwise convolutions; depthwise convolutions, SE, masking and other regions stay on CPU. Wider fused retention, buffering and tiling require further implementation. The measured bulk results do not predict performance of a future fused 512/1024 implementation.','',
            '## Reproduction and evidence','',
            'Use `software/latency/benchmark_larger_citrinet.py --model-dir research/export/<model> --model research/export/<model>/cpu-int8-safe.onnx --physical --runs 15 --out <report>` under sudo on the accepted bulk firmware, 100 MHz clock, compatible driver and existing native library. CPU-only FP32 screening omits `--model` and `--physical`. Set `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4`; run board measurements sequentially.','',
            'The aggregate report is `reports/fused/larger_citrinet_summary.json`. Per-model board screens, graph/bias audits, source checkpoint acquisition records, export validation and original-NeMo validation are preserved alongside it. `scripts/summarize_larger_citrinet.py` checks model hashes before regenerating this report.','']
    (ROOT/'LARGER_CITRINET_RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
