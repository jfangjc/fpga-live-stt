"""Validate experimental exact scale-split retention against unchanged CPU logits."""
import sys,ctypes
from tail_benchmark import *
sys.path.insert(0,str(ROOT/'software/ort_fpga_stream_branch512'))
# Explicit import avoids selecting a compiler from an earlier sys.path entry.
from branch_graph import compile_branches
from pair_graph import candidate as pairs
original=onnx.load(ROOT/'research/fused/cpu-int8-cse.onnx')
from split_scale_pairs import expand
from retain_stride_pointwise import retain
from se_pool import transform as pool
expanded,split_records=expand(original)
paired,selected=pairs(expanded,True)
assert len(selected)==104
transformed,tail_records=retain(transform(paired)[0],True)
graph,records,bounds=compile_branches(transformed,True)
transactions=sum(n.domain=='prototype.fpga.stream.branch512' for n in graph.graph.node)
graph,_=tails(graph)
graph,pool_records=pool(graph)
assert len(pool_records)==21
library=ROOT/'software/ort_fpga_stream_branch512/libort_fpga.so'
config={'threads':4,'spin':10,'level':'extended'}
reference=make_session(original,config)
runner=make_session(graph,config,[ROOT/'software/latency/libboundary_lut.so',library,ROOT/'software/latency/libse_pool.so'])
lib=ctypes.CDLL(str(library));frontend=Frontend(ROOT/'research/export/citrinet-256-ls')
vocab=(ROOT/'research/export/citrinet-256-ls/vocab.txt').read_text().splitlines()
from probe import stats
audio_records=[];clips=[]
for folder in ('user-recording','librispeech-mini','user-stress-ac'):
    audio_records+=corpus(ROOT/'research/eval'/folder/'evaluation.jsonl',('evaluation','test'))
for record in audio_records:
    audio=read_audio(record['path'])
    for seconds in (.25,.5,1,2):
        x,n=frontend(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])])
        feed={'features':x,'feature_lengths':n};expected=reference.run(None,feed)
        before=stats(lib);actual=runner.run(None,feed);after=stats(lib)
        assert after['oracle_calls']-before['oracle_calls']==128
        assert after['physical_calls']==before['physical_calls']==0
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
        assert decode(actual[0][0],actual[1][0],vocab)==decode(expected[0][0],expected[1][0],vocab)
        clips.append({'id':record['id'],'seconds':seconds,'all_logits_bit_exact':True})
        print('PASS',record['id'],seconds,flush=True)
write_json(ROOT/'reports/fused/branch512_more_pool_oracle.json',{'complete':True,'hardware_execution':False,
    'physical_branch_implemented':True,'residual_projections':21,'body_pairs':107,'total_pairs':128,'transactions':transactions,
    'accelerated_real_convolutions':228,'extra_identity_convolutions':7,'stride_tail_records':tail_records,
    'stride_tail_source_sha256':sha(ROOT/'software/latency/retain_stride_pointwise.py'),
    'se_pool_library_sha256':sha(ROOT/'software/latency/libse_pool.so'),'se_pool_transform_sha256':sha(ROOT/'software/latency/se_pool.py'),'se_pool_regions':len(pool_records),'split_records':split_records,
    'latency_measured':False,'scale_split_source_sha256':sha(ROOT/'software/latency/split_scale_pairs.py'),
    'all_cpu_logits_bit_exact':True,'clips':clips,'all_unbiased_uint8_accumulators_fit_int32':True,
    'bias_addition_semantics':'INT32 modulo wrap, followed by ARM float32 requantization',
    'rows_requiring_bias_wrap':sum(b['int32_bias_wrap_required'] for b in bounds),'residual_bounds':bounds,
    'records':records,'library_sha256':sha(library),'runtime_source_sha256':sha(ROOT/'software/ort_fpga_stream_branch512/pointwise.cc'),
    'compiler_sha256':sha(ROOT/'software/ort_fpga_stream_branch512/branch_graph.py'),'source_sha256':sha(__file__),
    'cpu_model_sha256':sha(ROOT/'research/fused/cpu-int8-cse.onnx')})
print('PASS:',len(clips),'CPU-exact prefixes with 128 hardware pairs in',transactions,'software blocks',flush=True)
