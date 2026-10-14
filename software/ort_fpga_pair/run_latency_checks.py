"""Run pair/block benchmarks with temporary measured IRQ policies; restore masks."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/latency'))
sys.path.insert(0,str(ROOT/'software/fused'))
from dma_irq import snapshot,configure
from common import sha,write_json


def main():
    before=snapshot();outputs=[]
    try:
        for seconds,core,label in [(.5,0,'half'),(1,3,'one')]:
            configure(core)
            for script,runs,kind in [('benchmark_block.py',200,'block'),('benchmark.py',100,'total')]:
                out=ROOT/f'reports/fused/pair_{kind}_{label}.json'
                context_flag='--seconds' if kind=='block' else '--contexts'
                subprocess.run([sys.executable,str(Path(__file__).with_name(script)),context_flag,str(seconds),
                                '--runs',str(runs),'--out',str(out)],check=True,cwd=ROOT)
                proof=json.loads(out.read_text())
                proof.update(dma_irq_core=core,dma_irq_affinity=snapshot(),
                             latency_wrapper_source_sha256=sha(__file__))
                write_json(out,proof);outputs.append(out.relative_to(ROOT).as_posix())
    finally:
        for irq,value in before.items():
            (Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])
        after=snapshot()
        assert {i:v['requested'] for i,v in after.items()}=={i:v['requested'] for i,v in before.items()}
        write_json(ROOT/'reports/fused/pair_irq_restoration.json',
                   {'complete':True,'before':before,'after':after,'source_sha256':sha(__file__),'reports':outputs})


if __name__=='__main__':main()
