"""Prepare full 256-channel block quantization before streaming RTL work."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'software/ort_fpga_stream';dest.mkdir(parents=True,exist_ok=True)
source=(ROOT/'software/ort_fpga_chain/pointwise.cc').read_text()
source=source.replace('width>=11 && width<=21','width>=1 && width<=41')
source=source.replace('kernel>=11&&kernel<=21','kernel>=1&&kernel<=41')
source=source.replace('count>0&&count<=32','count>0&&count<=8')
start=source.index('  }else{',source.index('struct Chain {'))
end=source.index('\n  }\n }\n};',start)
source=source[:start]+'''  }else{
   throw std::runtime_error("Streamed FPGA backend is not implemented/qualified yet");'''+source[end:]
source=source.replace('prototype.fpga.chain','prototype.fpga.stream')
(dest/'pointwise.cc').write_text(source)
for name in ('qnc.h','qnc_transport.c','build.sh'):shutil.copyfile(ROOT/'software/ort_fpga_chain'/name,dest/name)
shutil.copytree(ROOT/'software/ort_fpga_chain/include',dest/'include',dirs_exist_ok=True)
graph=(ROOT/'software/ort_fpga_shortwide/graph.py').read_text()
graph=graph[:graph.index('\ndef candidate(')]
graph=graph.replace('wd.shape[2] in (11,13,15,17,19,21)', '(1<=wd.shape[2]<=41 and wd.shape[2]%2==1)')
graph=graph.replace("domain='prototype.fpga.pair'", "domain='prototype.fpga.stream.pair'")
graph=graph.replace("v.domain=='prototype.fpga.pair'", "v.domain=='prototype.fpga.stream.pair'").replace("make_opsetid('prototype.fpga.pair'", "make_opsetid('prototype.fpga.stream.pair'")
graph+='''
def candidate(model,oracle=True):
    g=copy.deepcopy(model);producers={o:n for n in model.graph.node for o in n.output};selected=[];rejected=[]
    for pw in model.graph.node:
        if pw.op_type!='QLinearConv':continue
        try:
            q=producers[pw.input[0]];where=producers[q.input[0]];dq=producers[where.input[2]];dw=producers[dq.input[0]]
            if dw.op_type!='QLinearConv':continue
            g=one_pair(g,dw.name,pw.name,oracle);selected.append((dw.name,pw.name))
        except (AssertionError,KeyError,IndexError):rejected.append(pw.name)
    assert len(selected)>32, 'No extra pairs selected'
    return g,selected
'''
(dest/'pair_graph.py').write_text(graph)
compiler=(ROOT/'software/ort_fpga_chain/chain_graph.py').read_text()
compiler=compiler.replace('assert len(chain)<=32','assert len(chain)<=8')
compiler=compiler.replace("domain='prototype.fpga.chain'", "domain='prototype.fpga.stream'")
compiler=compiler.replace("make_opsetid('prototype.fpga.chain'", "make_opsetid('prototype.fpga.stream'")
compiler=compiler.replace('==len(pairs)==32','==len(pairs)')
(dest/'stream_graph.py').write_text(compiler)
print('Created isolated full-block graph/oracle; physical backend refuses execution')
