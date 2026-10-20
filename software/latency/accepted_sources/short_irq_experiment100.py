"""Test DMA IRQ placement temporarily; restore original masks on every exit."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'software/fused'))
from common import sha, write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--core',type=int,choices=(0,3),default=3)
    ap.add_argument('--runs',type=int,default=100)
    a=ap.parse_args()
    lines=Path('/proc/interrupts').read_text().splitlines()
    irqs=[]
    for line in lines:
        if line.strip().endswith('xilinx-dma-controller'):
            irqs.append(int(re.match(r'\s*(\d+):',line).group(1)))
    assert len(irqs)==2, 'Expected exactly two active PL DMA interrupts'
    before={str(irq):(Path('/proc/irq')/str(irq)/'smp_affinity_list').read_text().strip() for irq in irqs}
    nodes=json.loads((ROOT/'reports/fused/context_cse_confirmation100.json').read_text())['nodes']
    outputs=[]
    try:
        for irq in irqs:(Path('/proc/irq')/str(irq)/'smp_affinity_list').write_text(str(a.core))
        effective={str(irq):(Path('/proc/irq')/str(irq)/'effective_affinity_list').read_text().strip() for irq in irqs}
        assert set(effective.values())=={str(a.core)}
        for label,context,spin,selected in [('half',.5,0,[nodes[1]]),('one',1,10,nodes)]:
            out=ROOT/f'reports/fused/short_irq{a.core}_{label}_confirmation{a.runs}.json'
            subprocess.run([sys.executable,str(ROOT/'software/latency/context_short_policy.py'),
                            '--runtime','bulk','--threads','4','--main-core','3','--spin-us',str(spin),
                            '--trim-padding','--contexts',str(context),'--runs',str(a.runs),
                            '--nodes',*selected,'--out',str(out)],check=True,cwd=ROOT)
            proof=json.loads(out.read_text())
            proof.update(dma_irq_effective_affinity=effective, dma_irq_original_requested_affinity=before,
                         irq_experiment_source_sha256=sha(__file__))
            write_json(out,proof); outputs.append(out.relative_to(ROOT).as_posix())
    finally:
        for irq,mask in before.items():(Path('/proc/irq')/irq/'smp_affinity_list').write_text(mask)
        restored={irq:(Path('/proc/irq')/irq/'smp_affinity_list').read_text().strip() for irq in before}
        assert restored==before
        write_json(ROOT/f'reports/fused/short_irq{a.core}_restoration.json',
                   {'complete':True,'original_requested_affinity':before,'restored_requested_affinity':restored,
                    'source_sha256':sha(__file__),'reports':outputs})
    print('Restored DMA IRQ affinity',flush=True)


if __name__=='__main__':main()
