"""Paired complete-processing FPGA versus CPU INT8 performance proof."""
import argparse,json,random,time
from pathlib import Path
import numpy as np
import ctypes
import onnx
from probe import ROOT,candidate,session,stats
from common import Frontend,read_audio,decode,environment,sha,write_json,identity,corpus,errors


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nodes',nargs='+',required=True)
    p.add_argument('--model',type=Path,default=ROOT/'research/fused/cpu-int8.onnx')
    p.add_argument('--library',type=Path,default=Path(__file__).with_name('libort_fpga.so'))
    p.add_argument('--manifests',nargs='+',type=Path,required=True)
    p.add_argument('--runs',type=int,default=50);p.add_argument('--warmups',type=int,default=5)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.runs<20 or args.warmups<3:p.error('Acceptance requires at least 20 pairs and 3 warmups')
    directory=ROOT/'research/export/citrinet-256-ls'
    proof=json.loads(args.model.with_suffix('.json').read_text())
    if sha(args.model)!=proof['model_sha256'] or identity(directory)!=proof['source_identity']:
        raise ValueError('CPU model/frontend/decoder identity mismatch')
    records=[]
    for manifest in args.manifests:records.extend(corpus(manifest,('evaluation','test')))
    if set(proof['calibration_audio_sha256'])&{r['audio_sha256'] for r in records}:
        raise ValueError('Calibration/evaluation overlap')
    model=onnx.load(str(args.model));args.out.parent.mkdir(parents=True,exist_ok=True)
    graph=candidate(model,args.nodes,quant=True)
    graph_path=args.out.with_suffix('.onnx');onnx.save(graph,str(graph_path))
    repacked_graph=onnx.load_from_string(graph.SerializeToString())
    for n in repacked_graph.graph.node:
        if n.op_type=='FpgaPrepackedPointwise':n.op_type='FpgaBulkPointwise'
    lib=ctypes.CDLL(str(args.library.resolve()))
    initialization={};runners={}
    for name,m,library in [('cpu',model,None),('fpga',graph,args.library),
                            ('oracle',candidate(model,args.nodes,True,True),args.library),
                            ('fpga_repack',repacked_graph,args.library)]:
        start=time.perf_counter();runners[name]=session(m,library)
        initialization[name]=time.perf_counter()-start
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    clock_path=Path('/sys/bus/platform/devices/asr-v3-bulk-clock/set_rate')
    firmware=Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin')
    if not clock_path.exists() or not firmware.exists():raise ValueError('Matching experimental application must be active')

    def measured_environment():
        result=environment();result['pl_clock_hz']=int(clock_path.read_text().strip())
        if not 99000000<=result['pl_clock_hz']<=101000000:raise ValueError('Unexpected FPGA clock')
        return result

    def call(name,path):
        before=measured_environment();counters=stats(lib)
        start=time.perf_counter()
        audio=read_audio(path);x,length=frontend(audio)
        logits,encoded=runners[name].run(None,{'features':x,'feature_lengths':length})
        text=decode(logits[0],encoded[0],vocab)
        elapsed=time.perf_counter()-start
        after=stats(lib)
        if not np.all(np.isfinite(logits)):raise ValueError('Nonfinite output')
        delta={k:after[k]-counters[k] for k in after}
        if name in ('fpga','fpga_repack') and delta['physical_calls']!=len(args.nodes):raise AssertionError('Missing physical FPGA execution')
        if name=='cpu' and (delta['physical_calls'] or delta['oracle_calls']):raise AssertionError('CPU baseline called accelerator')
        return {'seconds':elapsed,'text':text,'encoded_length':int(encoded[0]),
                'environment_before':before,'environment_after':measured_environment(),
                'fpga_counters':delta},logits,encoded

    rows=[];rng=random.Random(10092026);summary=[];cold=[]
    for r in records:
        reference,expected,length=call('oracle',r['path'])
        first,physical,actual_length=call('fpga',r['path'])
        cold.append({'id':r['id'],'first_call_after_session_creation':not cold,**first})
        repacked_first,repacked_logits,repacked_length=call('fpga_repack',r['path'])
        np.testing.assert_array_equal(expected,repacked_logits)
        np.testing.assert_array_equal(length,repacked_length)
        np.testing.assert_array_equal(expected,physical)
        np.testing.assert_array_equal(length,actual_length)
        for _ in range(args.warmups):call('cpu',r['path']);call('fpga',r['path']);call('fpga_repack',r['path'])
        selected=[]
        for i in range(args.runs):
            order=['cpu','fpga','fpga_repack'];rng.shuffle(order);pair={}
            for name in order:pair[name]=call(name,r['path'])[0]
            if len({pair[v]['encoded_length'] for v in ('cpu','fpga','fpga_repack')})!=1:raise AssertionError('Length mismatch')
            selected.append(pair);rows.append({'id':r['id'],'repeat':i,'order':order,'results':pair})
        cpu=np.array([v['cpu']['seconds'] for v in selected]);fpga=np.array([v['fpga']['seconds'] for v in selected])
        # Paired bootstrap of mean saving, independent from candidate selection.
        samples=np.random.default_rng(99026).integers(0,args.runs,(10000,args.runs))
        boot=(cpu-fpga)[samples].mean(axis=1)
        repack=np.array([v['fpga_repack']['seconds'] for v in selected]);pack_boot=(repack-fpga)[samples].mean(axis=1)
        cpu_texts={v['cpu']['text'] for v in selected};fpga_texts={v['fpga']['text'] for v in selected}
        repack_texts={v['fpga_repack']['text'] for v in selected}
        if repack_texts!=fpga_texts:raise AssertionError('Repack/prepack transcript mismatch')
        if len(cpu_texts)!=1 or len(fpga_texts)!=1:raise AssertionError('Nondeterministic transcripts')
        ct=next(iter(cpu_texts));ft=next(iter(fpga_texts));text=r.get('reference',r.get('text'))
        ce,words=errors(text,ct);fe,_=errors(text,ft)
        clip={'id':r['id'],'audio_sha256':r['audio_sha256'],'cpu_p50':float(np.median(cpu)),
              'fpga_p50':float(np.median(fpga)),'cpu_p95':float(np.percentile(cpu,95)),
              'fpga_p95':float(np.percentile(fpga,95)),
              'mean_saving_95ci_seconds':[float(v) for v in np.percentile(boot,[2.5,97.5])],
              'repack_p50':float(np.median(repack)),'repack_p95':float(np.percentile(repack,95)),
              'prepack_vs_repack_mean_saving_95ci_seconds':[float(v) for v in np.percentile(pack_boot,[2.5,97.5])],
              'cpu_text':ct,'fpga_text':ft,'cpu_errors':ce,'fpga_errors':fe,'reference_words':words,
              'physical_oracle_bit_parity':True}
        summary.append(clip)
        report={'hardware_execution':True,'timing_scope':'WAV read, original frontend, single graph inference and decoder; resident warm sessions',
                'nodes':args.nodes,'cpu_threads':4,'worker_spinning':False,
                'initialization_seconds':initialization,'first_physical_per_clip':cold,
                'model_sha256':sha(args.model),'fpga_graph_sha256':sha(graph_path),
                'library_sha256':sha(args.library),'warmups':args.warmups,'runs':args.runs,
                'firmware_sha256':sha(firmware),
                'driver_sha256':sha(ROOT/'deployment/experimental-bulk/qn_tile.ko'),
                'requested_recording_ids':[r['id'] for r in records],
                'complete':len(summary)==len(records),
                'sources_sha256':{p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in ('.py','.cc','.c','.h','.sh')},
                'clips':summary,'paired_runs':rows,'repack_comparator':'Identical physical engine and native arithmetic with weight packing repeated on each LOAD',
                'representative_corpus_claimed':False,
                'sustained_capture_validated':False}
        write_json(args.out,report)
        print(r['id'],'CPU',clip['cpu_p50'],'FPGA',clip['fpga_p50'],'saving CI',clip['mean_saving_95ci_seconds'],flush=True)


if __name__=='__main__':main()
