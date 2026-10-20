"""Check metadata sharing against unchanged CPU logits, including dynamic masks."""
import argparse,json,sys,time
from pathlib import Path
import numpy as np
import onnx
import onnxruntime as ort
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import Frontend,read_audio,decode,corpus,sha,write_json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--manifests',type=Path,nargs='*',default=[])
p.add_argument('--out',type=Path,required=True);a=p.parse_args()
original=ROOT/'research/fused/cpu-int8.onnx';changed=ROOT/'research/fused/cpu-int8-shared-shapes.onnx'
proof=json.loads(changed.with_suffix('.json').read_text())
assert proof['parent_model_sha256']==sha(original) and proof['model_sha256']==sha(changed)
def session(path):
    opt=ort.SessionOptions();opt.intra_op_num_threads=4;opt.inter_op_num_threads=1
    opt.add_session_config_entry('session.intra_op.allow_spinning','0')
    opt.add_session_config_entry('session.inter_op.allow_spinning','0')
    return ort.InferenceSession(str(path),opt,providers=['CPUExecutionProvider'])
runners=[session(original),session(changed)];rng=np.random.default_rng(100102026);checks=[]
for batch,frames,lengths in [(1,32,[1]),(1,64,[51]),(1,112,[101]),(1,208,[199]),
                              (1,400,[399]),(1,1008,[1001]),(2,64,[13,63])]:
    x=rng.standard_normal((batch,80,frames),dtype=np.float32);n=np.array(lengths,dtype=np.int64)
    old,old_length=runners[0].run(None,{'features':x,'feature_lengths':n})
    new,new_length=runners[1].run(None,{'features':x,'feature_lengths':n})
    np.testing.assert_array_equal(old_length,new_length);np.testing.assert_array_equal(old,new)
    checks.append({'batch':batch,'frames':frames,'valid_lengths':lengths,'logits_bit_exact':True})
    print('PASS dynamic mask',batch,frames,lengths,flush=True)
directory=ROOT/'research/export/citrinet-256-ls';frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
clips=[]
for manifest in a.manifests:
    for r in corpus(manifest,('evaluation','test')):
        x,n=frontend(read_audio(r['path']))
        old,old_length=runners[0].run(None,{'features':x,'feature_lengths':n})
        new,new_length=runners[1].run(None,{'features':x,'feature_lengths':n})
        np.testing.assert_array_equal(old_length,new_length);np.testing.assert_array_equal(old,new)
        text=decode(new[0],new_length[0],vocab)
        clips.append({'id':r['id'],'audio_sha256':r['audio_sha256'],'logits_bit_exact':True,'text':text})
        print('PASS waveform',r['id'],flush=True)
write_json(a.out,{'scope':'Numerical metadata-rewrite verification; not a latency benchmark',
    'hardware_fpga_execution':False,'complete':True,'original_model_sha256':sha(original),
    'shared_model_sha256':sha(changed),'transformation_source_sha256':proof['transform_source_sha256'],
    'validator_sha256':sha(__file__),'ort_version':ort.__version__,
    'all_logits_bit_exact':True,'dynamic_shape_checks':checks,'clips':clips})
