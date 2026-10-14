"""Bind actual reports/artifacts into a final-gate sidecar; fail on missing proof."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''): h.update(block)
    return h.hexdigest()


def require(condition,message):
    if not condition: raise ValueError(message)


def positive_dma(stats):
    return isinstance(stats,dict) and all(type(stats.get(k)) in (int,float) and
        math.isfinite(stats[k]) and stats[k]>0 for k in ['loads','runs','ioctls','tx_bytes','rx_bytes'])


def thermal(snapshot):
    readings=snapshot.get('thermal_millicelsius',{})
    values=[]
    for value in readings.values():
        try: number=float(value)/1000
        except (ValueError,TypeError): continue
        if math.isfinite(number): values.append(number)
    require(bool(values),'No finite measured thermal readings in benchmark snapshot')
    return max(values)


def collect(benchmark,original,physical,capture,manifest,root,firmware,driver,reviewed,audit):
    require(reviewed,'Explicit --references-reviewed is required')
    require(isinstance(audit,str) and len(audit.strip())>=20,'Supply a meaningful --runner-audit statement confirming optimized CPU, full processing, resident warm state and concurrent capture')
    paths=[benchmark,original,physical,capture,manifest,firmware,driver]
    bench,orig,phy,cap=[json.loads(Path(p).read_text()) for p in paths[:4]]
    require(bench.get('measured_on_physical_board') is True,'Benchmark is not physical board evidence')
    cm,fm=bench['metadata']['cpu'],bench['metadata']['fpga']
    require(cm.get('hardware_execution') is False and fm.get('hardware_execution') is True,'CPU/FPGA execution identity mismatch')
    identity=['model_sha256','tokenizer_sha256','preprocessing_id','decoder_id']
    for key in identity:
        require(cm.get(key) and cm[key]==fm.get(key)==orig.get(key)==phy.get('metadata',{}).get(key),'Identity mismatch: '+key)
    require(orig.get('status')=='pass' and orig.get('complete_original_nemo_wrapper_validated') is True and bool(orig.get('tests')),'Complete original NeMo report did not pass')
    require(cm.get('original_model_output_parity_validated') is True and fm.get('original_model_output_parity_validated') is True,'Benchmark runners were not bound to original parity validation')
    require(cm.get('original_model_output_parity_report_sha256')==sha(original)==fm.get('original_model_output_parity_report_sha256'),'Original parity report hash mismatch')
    proof=phy.get('physical_vs_numerical_int8_implementation_parity') or {}
    flags=['passed','positive_physical_dma_work','shapes_equal','finite','encoded_lengths_equal','encoded_lengths_valid','logits_within_tolerance','transcripts_match']
    require(phy.get('hardware_execution') is True and phy.get('mode')=='fpga' and all(proof.get(k) is True for k in flags) and positive_dma(phy.get('dma')),'Physical-vs-INT8 parity or counted DMA work did not pass')
    require(proof.get('absolute_tolerance')==1e-4 and proof.get('relative_tolerance')==1e-5,'Unexpected physical parity tolerances')
    require(fm.get('physical_quantized_graph_parity_validated') is True and fm.get('physical_quantized_graph_parity_report_sha256')==sha(physical),'Benchmark runner not bound to physical parity report')
    require(fm.get('native_library_sha256')==phy['metadata'].get('native_library_sha256'),'Physical native binary mismatch')
    root=Path(root).resolve(); source={}
    require(fm.get('source_sha256') and fm['source_sha256']==phy['metadata'].get('source_sha256'),'Runtime source provenance mismatch')
    for relative,recorded in fm['source_sha256'].items():
        p=(root/relative).resolve()
        require(p.is_relative_to(root),'Runtime source escapes project root: '+relative)
        require(p.is_file() and sha(p)==recorded,'Source changed after measured execution: '+relative)
        source[relative]=recorded
    model_dir=root/'research/export/citrinet-256-ls'
    for name,key in [('model.onnx','model_sha256'),('vocab.txt','tokenizer_sha256')]:
        require(sha(model_dir/name)==fm[key],'Current model/tokenizer differs from measured artifact')
        source[str((model_dir/name).relative_to(root))]=sha(model_dir/name)
    frontend=sha(model_dir/'frontend.npz');cpu_source=sha(root/'software/model-tools/citrinet_cpu.py')
    require(hashlib.sha256((frontend+cpu_source).encode()).hexdigest()==fm['preprocessing_id'] and cpu_source==fm['decoder_id'],'Frontend/decoder source or constants changed')
    require(frontend==orig.get('frontend_npz_sha256') and cpu_source==orig.get('citrinet_cpu_source_sha256'),'Original parity frontend provenance mismatch')
    source['research/export/citrinet-256-ls/frontend.npz']=frontend
    require(sha(root/'software/model-tools/validate_nemo.py')==orig.get('validate_nemo_source_sha256'),'Original validation implementation changed')
    source['software/model-tools/validate_nemo.py']=sha(root/'software/model-tools/validate_nemo.py')
    lib=root/'software/native/libqnc.so';require(sha(lib)==fm.get('native_library_sha256'),'Native binary changed')
    source['software/native/libqnc.so']=sha(lib)
    for p in [firmware,driver]:source[str(Path(p).resolve())]=sha(p)
    require(cap.get('passed') is True and cap.get('hardware_execution') is True and cap.get('sample_rate')==16000 and type(cap.get('samples')) is int and cap['samples']>0 and not cap.get('errors'),'Capture evidence did not pass')
    for k in ['newly_dropped_samples','software_dropped_samples']:
        require(type(cap.get(k)) is int and cap[k]==0,'Capture loss: '+k)
    require(sha(manifest)==bench['manifest_sha256'],'Reviewed manifest differs from benchmark')
    records=[json.loads(line) for line in Path(manifest).read_text().splitlines() if line.strip()]
    require([(r['id'],r['text']) for r in records]==[(r['id'],r['text']) for r in bench['corpus']],'Reference content differs')
    require(bench.get('samples'),'No benchmark samples')
    for s in bench['samples']:
        require(s['environment_before'].get('machine') in ('aarch64','arm64'),'Non-ARM64 benchmark snapshot')
        thermal(s['environment_before']);thermal(s['environment_after'])
        if s['mode']=='fpga':require(s['runner_details'].get('hardware_execution') is True and positive_dma(s['runner_details'].get('dma')),'Missing physical counted work in measured call')
    calibration=fm.get('calibration_audio_sha256')
    require(isinstance(calibration,list) and not set(calibration)&{r['audio_sha256'] for r in bench['corpus']},'Calibration/evaluation audio overlap')
    return dict(board='KV260',preprocessing_sha256=fm['preprocessing_id'],decoder_sha256=fm['decoder_id'],
        source_provenance_sha256=source,original_model_output_parity_validated=True,
        original_model_parity_report_sha256=sha(original),physical_quantized_graph_parity_validated=True,
        physical_quantized_graph_parity_report_sha256=sha(physical),
        thermal_before_c=thermal(bench['samples'][0]['environment_before']),
        thermal_after_c=thermal(bench['samples'][-1]['environment_after']),
        calibration_ids=calibration,full_processing_timing=True,warm_state_resident=True,cpu_optimized=True,
        capture_newly_dropped_samples=cap['newly_dropped_samples'],capture_software_dropped_samples=cap['software_dropped_samples'],
        reference_transcripts_reviewed=True,reference_transcripts_sha256=sha(manifest),
        runner_audit=audit,benchmark_report_sha256=sha(benchmark),capture_report_sha256=sha(capture))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['benchmark','original','physical','capture','manifest','firmware','driver','output']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--references-reviewed',action='store_true',required=True)
    p.add_argument('--runner-audit',required=True)
    a=p.parse_args()
    try: result=collect(a.benchmark,a.original,a.physical,a.capture,a.manifest,a.root,a.firmware,a.driver,a.references_reviewed,a.runner_audit)
    except (ValueError,KeyError,TypeError,OSError) as e:p.exit(2,'Evidence rejected: '+str(e)+'\n')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print('Evidence bound: '+str(a.output))

if __name__=='__main__':main()
