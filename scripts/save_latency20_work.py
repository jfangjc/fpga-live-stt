"""Immutable source/artifact/evidence snapshot; exclude generated build caches."""
import argparse,hashlib,json,os,zipfile
from pathlib import Path
from datetime import date
SNAPSHOT_DATE=date.today().isoformat()
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--destination',type=Path,required=True)
ap.add_argument('--result',type=Path,default=ROOT/'reports/fused/chain_latency_confirmation.json')
ap.add_argument('--allow-screen',action='store_true',help='Preserve a completed policy screen with an explicit unqualified label')
a=ap.parse_args();a.result=a.result.resolve();assert not a.destination.exists(),'Refusing to overwrite snapshot'
sha=lambda data:hashlib.sha256(data).hexdigest()
ext={'.py','.c','.cc','.cpp','.h','.hpp','.v','.sv','.vh','.svh','.tcl','.sh','.ps1','.bat','.xdc','.bd','.xci','.xpr',
     '.xml','.json','.jsonl','.yaml','.yml','.toml','.ini','.cfg','.md','.txt','.bif','.dts','.dtsi','.mem','.coe','.rpt'}
excluded={'__pycache__','.git','.Xil','uv-cache','linux-tools','site-packages','node_modules','xsim.dir'}
payload={}
def add(path):
    assert path.is_file(),str(path)
    payload[path.relative_to(ROOT).as_posix()]=path.read_bytes()
for folder in ('rtl','hardware','sim','software','scripts','deployment','verification','research','reports','Prototype_v2.srcs','kv260-asr-handoff-2026-10-11'):
    for directory,children,names in os.walk(ROOT/folder):
        children[:]=[n for n in children if n not in excluded and not n.startswith('.venv') and not n.endswith(('.cache','.gen','.runs','.sim','.ip_user_files'))]
        for name in names:
            path=Path(directory)/name
            if path.suffix.lower() in ext or name in ('Makefile','Kbuild','LICENSE'):add(path)
for path in ROOT.iterdir():
    if path.is_file() and path.suffix in ('.md','.xpr'):add(path)
# Preserve the complete, working managed project sources as well as RTL.
# These small files let the saved stream project regenerate its IP outputs.
for project in ('stream','adaptive','branch_bimodal','branch512_pipe166','branch512_slice166','branch512_outslice166','branch512_drop166','branch512_guard166','branch512_ab166','branch512_dma128166'):
    folder=ROOT/'build'/({'stream':'stream_system','adaptive':'adaptive_system_v2','branch_bimodal':'branch_bimodal_system','branch512_pipe166':'branch512_pipe166_system','branch512_slice166':'branch512_slice166_system','branch512_outslice166':'branch512_outslice166_system','branch512_drop166':'branch512_drop166_system','branch512_guard166':'branch512_guard166_system','branch512_ab166':'branch512_ab166_system','branch512_dma128166':'branch512_dma128166_system'}[project])
    name=f'Prototype_v3_{project}'
    if (folder/(name+'.xpr')).is_file():add(folder/(name+'.xpr'))
    for path in (folder/(name+'.srcs')).rglob('*'):
        if path.is_file() and path.suffix.lower() in ext:add(path)
for folder in ('software/ort_fpga_chain','software/ort_fpga_overlap','software/ort_fpga_overlap_session','software/ort_fpga_pipeline','software/ort_fpga_pipeline_pinned','software/ort_fpga_stream','software/ort_fpga_stream_exact','software/ort_fpga_stream_registered','software/ort_fpga_stream_branch','software/ort_fpga_stream_branch_transport','software/ort_fpga_stream_branch512','software/ort_fpga_stream_branch512_neon','software/latency'):
    for path in (ROOT/folder).glob('*.so'):add(path)
for folder in ('deployment/asr-v3-chain','deployment/asr-v3-chain-prefetch','deployment/asr-v3-stream','deployment/asr-v3-bulk','deployment/kernel-compat','deployment/experimental-chain','deployment/experimental-stream','deployment/experimental-stream-registered','deployment/experimental-stream-branch','deployment/asr-v3-adaptive','deployment/asr-v3-branch-bimodal','deployment/asr-v3-branch512-pipe166','deployment/asr-v3-branch512-slice166','deployment/asr-v3-branch512-outslice166','deployment/asr-v3-branch512-drop166','deployment/asr-v3-branch512-guard166','deployment/asr-v3-branch512-ab166','deployment/asr-v3-branch512-dma128166'):
    for path in (ROOT/folder).rglob('*'):
        if path.is_file() and path.suffix in ('.bit','.bin','.xsa','.dtbo','.ko'):add(path)
for name in ('research/fused/cpu-int8-cse.onnx','research/export/citrinet-256-ls/model.onnx','research/export/citrinet-256-ls/frontend.npz'):
    add(ROOT/name)
for path in (ROOT/'research/eval').rglob('*.wav'):add(path)
for path in (ROOT/'reports/fused').glob('*'):
    if path.suffix=='.log' and path.name.startswith(('chain_','pinned_','overlap_','pipeline_','tail_','residual_','prefetch_','stream_','registered_','latency20_','frontend_thread','adaptive_','branch_','branch512_')):add(path)
    if path.suffix=='.onnx' and path.name.startswith(('chain_','tail_','prefetch_','stream_','registered_','adaptive_','branch_','branch512_')):add(path)
freeze=json.loads((ROOT/'reports/fused/shortwide_source_freeze.json').read_text())
for name,expected in freeze['sources_sha256'].items():assert sha((ROOT/name).read_bytes())==expected,name
proof_paths=list((ROOT/'reports/fused').glob('chain*firmware_evidence.json'))
stream_proof=ROOT/'reports/fused/stream_firmware_evidence.json'
if stream_proof.is_file():proof_paths.append(stream_proof)
registered_proof=ROOT/'reports/fused/registered_transport_evidence.json'
if registered_proof.is_file():proof_paths.append(registered_proof)
for name in ('adaptive_firmware_evidence.json','branch_bimodal_firmware_evidence.json','branch512_pipe166_firmware_evidence.json','branch512_slice166_firmware_evidence.json','branch512_outslice166_firmware_evidence.json','branch512_drop166_firmware_evidence.json','branch512_guard166_firmware_evidence.json','branch512_ab166_firmware_evidence.json','branch512_dma128166_firmware_evidence.json'):
    if (ROOT/'reports/fused'/name).is_file():proof_paths.append(ROOT/'reports/fused'/name)
for name,key in (('branch_bimodal_regression_evidence.json','sources_sha256'),('branch_driver_validation.json','sources_sha256'),('branch512_regression_evidence.json','sources_sha256'),('branch512_slice_regression_evidence.json','sources_sha256'),('branch512_outslice_regression_evidence.json','sources_sha256'),('branch512_neon_evidence.json','sources_sha256'),('residual_tail_candidates_evidence.json','sources_sha256'),('branch512_drop166_incremental_license_failure.json','sources_sha256')):
    report=ROOT/'reports/fused'/name
    if report.is_file():
        proof=json.loads(report.read_text());assert proof['complete']
        for path,value in proof[key].items():
            assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
for name in ('branch512_guard_regression_evidence.json','branch512_header_guard_equivalence.json',
             'branch512_drop166_fullroute_failure.json','branch512_drop166_postroute_evidence.json',
             'branch512_drop166_postroute_aggressive_evidence.json','branch512_guard166_fullroute_failure.json',
             'branch512_ab_regression_evidence.json','branch512_dma128166_fullroute_failure_evidence.json','branch512_dma128166_postroute_aggressive_evidence.json'):
    report=ROOT/'reports/fused'/name
    if report.is_file():
        proof=json.loads(report.read_text());assert proof['complete']
        for path,value in proof['sources_sha256'].items():
            assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
reciprocal=ROOT/'reports/fused/residual_tail_recip64_experiment_evidence.json'
if reciprocal.is_file():
    evidence=json.loads(reciprocal.read_text());assert evidence['complete'] and not evidence['adopted']
    for path,value in evidence['sources_sha256'].items():
        assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
drop=ROOT/'reports/fused/branch512_drop_regression_evidence.json'
if drop.is_file():
    evidence=json.loads(drop.read_text());assert evidence['complete']
    for path,value in evidence['sources_sha256'].items():
        assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
reference=ROOT/'reports/fused/branch512_drop166_incremental_reference.json'
if reference.is_file():
    evidence=json.loads(reference.read_text());assert evidence['complete']
    for path,value in evidence['sources_sha256'].items():
        assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
for name in ('branch512_slice166_timing_failure.json','branch512_outslice166_timing_failure.json'):
    failure=ROOT/'reports/fused'/name
    if failure.is_file():
        evidence=json.loads(failure.read_text());assert evidence['complete'] and not evidence['qualified']
        for path,value in evidence['sources_and_reports_sha256'].items():
            assert sha((ROOT/path).read_bytes())==value,path;add(ROOT/path)
for proof_path in proof_paths:
    proof=json.loads(proof_path.read_text());assert proof['complete']
    for name,expected in proof['sources_and_evidence_sha256'].items():
        path=ROOT/name;assert sha(path.read_bytes())==expected,name;add(path)
for name in ('build/stream_sim/stream_sim.sim/sim_1/behav/xsim/simulate.log','build/exact_requant_sim/exact_requant_sim.sim/sim_1/behav/xsim/simulate.log'):
    if (ROOT/name).is_file():add(ROOT/name)
result=json.loads(a.result.read_text());assert result['complete'] and result['hardware_execution']
screen='contexts' not in result
if screen:
    assert a.allow_screen and result['selected'] and 'Policy screen' in result['scope']
    contexts=result['selected'];measurement_kind='Policy screen; independent confirmation required'
else:
    assert result['runs_per_context']>=100
    contexts=result['contexts'];measurement_kind='Independent paired warm confirmation'
summary=[{k:c[k] for k in ('context_seconds','cpu_p50','fpga_p50','cpu_p95','fpga_p95','latency_reduction_percent','paired_bootstrap_95ci_percent','meets_20_percent','meets_30_percent','meets_50_percent') if k in c} for c in contexts]
readme=f'''# FPGA ASR retained-chain work — 2026-10-12

Saved from {ROOT.as_posix()}. Original work and experimental variants are
preserved. This package includes authored sources, routed chain firmware,
kernel-1036 drivers, ARM64 libraries, CPU/export models, frontend constants,
diagnostic WAVs and raw qualification evidence. Vivado 2026.1, board Ubuntu
dependencies and tool installations are external prerequisites.

The selected measured report is {a.result.relative_to(ROOT).as_posix()}.
Measurement status: {measurement_kind}.
20% across all tested contexts accepted: {result['timing_acceptance']}.
30% across all tested contexts accepted: {result.get('thirty_percent_acceptance',False)}.
2x speed across all tested contexts accepted: {result.get('twofold_speed_acceptance',False)}.
Current development target: FPGA hybrid time <= half optimized CPU time.
These are warm full audio-path measurements against an optimized CPU on the
same board. First-inference timing is reported separately. Streamed designs
transfer and load their weights inside every timed inference. Consult LATENCY20_PROGRESS.md
for decisions and limitations. Bound: 256 feature frames / about 2.55 s;
checkpoint is noncausal. Diagnostic parity is not representative WER proof.

The original retained-chain app is asr-v3-chain, 512 pointwise MACs,
64 depthwise lanes and 100 MHz. The prefetch and streamed apps have separate
firmware and drivers; their corresponding run_*_board.sh helpers activate
them and restore asr-v3-bulk with the kernel-compatible driver after testing.
Only complete routed, physical and timing
reports qualify a candidate. Do not infer deployment readiness from sources.

Extract to a separate directory. Vivado project files can contain absolute
paths; the working stream project's .xpr/.srcs are included and its build
helpers regenerate IP outputs. Adaptive builds clone that working project.
SOURCE_MANIFEST.json binds all files. Package metadata includes archive SHA
and readback verification. Credentials and generated build caches are excluded.
'''
payload['LATENCY20_SNAPSHOT_README.md']=readme.encode()
manifest={'source_root':str(ROOT),'snapshot_date':SNAPSHOT_DATE,'source_only':False,'selected_report':a.result.relative_to(ROOT).as_posix(),
          'summary':summary,'timing_acceptance':result['timing_acceptance'],'files':{n:sha(d) for n,d in sorted(payload.items())}}
payload['SOURCE_MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
a.destination.mkdir(parents=True)
archive=a.destination/'fpga-asr-latency-work.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name,data in sorted(payload.items()):z.writestr(name,data)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None and set(z.namelist())==set(payload)
    for name,data in payload.items():assert sha(z.read(name))==sha(data),name
metadata={'archive':str(archive),'sha256':sha(archive.read_bytes()),'files':len(payload),'bytes':archive.stat().st_size,'verified':True,'measurement_kind':measurement_kind,
          'selected_report':str(a.result),'timing_acceptance':result['timing_acceptance'],'summary':summary}
(a.destination/'package.json').write_text(json.dumps(metadata,indent=2)+'\n')
(a.destination/'LATENCY20_SNAPSHOT_README.md').write_text(readme)
print(json.dumps(metadata))
