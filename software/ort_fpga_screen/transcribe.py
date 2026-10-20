"""Transcribe local WAV files with a benchmark-bound physical FPGA graph."""
import argparse,ctypes,json,time
from pathlib import Path
import onnx
from probe import ROOT,session,stats
from common import Frontend,read_audio,decode,sha,identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark',type=Path,required=True)
    p.add_argument('--wav',type=Path,nargs='+',required=True)
    p.add_argument('--library',type=Path,default=Path(__file__).with_name('libort_fpga.so'))
    p.add_argument('--cpu',action='store_true',help='Use the matched CPU INT8 baseline')
    args=p.parse_args();proof=json.loads(args.benchmark.read_text())
    directory=ROOT/'research/export/citrinet-256-ls'
    cpu_model=ROOT/'research/fused/cpu-int8.onnx'
    cpu_proof=json.loads(cpu_model.with_suffix('.json').read_text())
    if identity(directory)!=cpu_proof['source_identity']:raise ValueError('Frontend/decoder identity mismatch')
    graph=cpu_model if args.cpu else args.benchmark.with_suffix('.onnx')
    expected=proof['model_sha256'] if args.cpu else proof['fpga_graph_sha256']
    if sha(graph)!=expected:raise ValueError('Graph identity mismatch')
    if not args.cpu:
        if sha(args.library)!=proof['library_sha256']:raise ValueError('Native operator identity mismatch')
        if sha(Path('/lib/firmware/xilinx/asr-v3-bulk/asr-v3-bulk.bit.bin'))!=proof['firmware_sha256']:
            raise ValueError('Firmware identity mismatch')
    lib=None if args.cpu else ctypes.CDLL(str(args.library.resolve()))
    runner=session(onnx.load(str(graph)),None if args.cpu else args.library)
    frontend=Frontend(directory);vocab=(directory/'vocab.txt').read_text().splitlines()
    for path in args.wav:
        before=stats(lib) if lib else None;start=time.perf_counter()
        audio=read_audio(path);x,length=frontend(audio)
        logits,encoded=runner.run(None,{'features':x,'feature_lengths':length})
        text=decode(logits[0],encoded[0],vocab);elapsed=time.perf_counter()-start
        counters={k:v-before[k] for k,v in stats(lib).items()} if lib else None
        if counters and counters['physical_calls']!=len(proof['nodes']):raise AssertionError('Missing physical FPGA execution')
        print(json.dumps({'wav':str(path),'text':text,'seconds':elapsed,
                          'backend':'cpu-int8' if args.cpu else 'physical-fpga',
                          'fpga_counters':counters}),flush=True)
if __name__=='__main__':main()
