"""Separate pinned-worker qualification and measured policy selection."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];directory=ROOT/'software/latency'
files=('pipeline_benchmark.py','validate_pipeline_oracle.py','validate_pipeline_physical.py','tune_pipeline_policy.py','confirm_pipeline_latency.py')
for name in files:
    text=(directory/name).read_text().replace('software/ort_fpga_pipeline','software/ort_fpga_pipeline_pinned')
    text=text.replace('pipeline_graph','pinned_graph').replace('pipeline_native_oracle','pinned_native_oracle').replace('pipeline_benchmark','pinned_benchmark')
    if name=='pipeline_benchmark.py':
        text=text.replace("'nested_cpu_threads':4","'default_nested_cpu_threads':3,'cpu_residual_worker_core':0")
        text+='''
from chain_benchmark import make_session as base_make_session
import copy
def make_session(graph,config,libraries=()):
    if any(n.domain=='prototype.fpga.pipeline.pinned' and n.op_type in ('FpgaResidualChain','OracleResidualChain') for n in graph.graph.node):
        graph=copy.deepcopy(graph)
        for node in graph.graph.node:
            if node.domain=='prototype.fpga.pipeline.pinned' and node.op_type in ('FpgaResidualChain','OracleResidualChain'):
                attrs=[a for a in node.attribute if a.name!='res_threads'];del node.attribute[:];node.attribute.extend(attrs)
                node.attribute.append(onnx.helper.make_attribute('res_threads',config.get('res_threads',3)))
    return base_make_session(graph,config,libraries)
'''
    if name=='tune_pipeline_policy.py':
        begin=text.index('policies=[');end=text.index('random.Random(20261012).shuffle(policies)',begin)
        text=text[:begin]+'''policies=[{'threads':4,'spin':s,'level':level,'irq_core':irq,'res_threads':r}
          for s,level,irq,r in ((10,'all',0,3),(10,'all',3,3),(0,'all',3,3),(10,'all',0,1),
                                (10,'all',3,1),(10,'all',3,4),(10,'extended',3,3))]
'''+text[end:]
    if name=='validate_pipeline_oracle.py':
        text=text.replace('from pinned_graph import fuse_residuals','from pinned_graph import fuse_residuals\nfrom pinned_benchmark import make_session')
        begin=text.index('    os.sched_setaffinity(0,{3});old=');end=text.index('finally:os.sched_setaffinity',begin)
        text=text[:begin]+'''    os.sched_setaffinity(0,{3});old=make_session(original,config,[boundary,parent])
    front=Frontend(ROOT/'research/export/citrinet-256-ls');audio=read_audio(ROOT/'research/eval/user-recording/speech.wav')
    for res_threads in (1,3,4):
        new=make_session(overlap,{**config,'res_threads':res_threads},[boundary,library])
        for seconds in (.25,.5,1,2.5):
            x,n=front(np.ascontiguousarray(audio[:round(seconds*16000)]));x=np.ascontiguousarray(x[:,:,:int(n[0])]);feed={'features':x,'feature_lengths':n}
            expected=old.run(None,feed);actual=new.run(None,feed)
            for left,right in zip(actual,expected):np.testing.assert_array_equal(left,right)
            row={'seconds':seconds,'res_threads':res_threads,'all_outputs_bit_exact':True};rows.append(row);print(json.dumps(row),flush=True)
        del new;gc.collect()
'''+text[end:]
    (directory/name.replace('pipeline','pinned')).write_text(text)
print('Created separate pinned-worker checks and seven-policy screen')
