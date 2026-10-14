"""Discover PL DMA IRQs and explicitly configure or verify their CPU placement."""
import argparse
import json
from pathlib import Path
import re


def snapshot():
    result={}
    for line in Path('/proc/interrupts').read_text().splitlines():
        if line.strip().endswith('xilinx-dma-controller'):
            irq=int(re.match(r'\s*(\d+):',line).group(1))
            root=Path('/proc/irq')/str(irq)
            result[str(irq)]={'requested':(root/'smp_affinity_list').read_text().strip(),
                              'effective':(root/'effective_affinity_list').read_text().strip()}
    if len(result)!=2:raise RuntimeError('Expected exactly two PL DMA IRQs')
    return result


def verify(core):
    current=snapshot()
    if any(v['effective']!=str(core) for v in current.values()):
        raise RuntimeError(f'DMA IRQ placement differs from the measured profile; configure core {core} explicitly')
    return current


def configure(core):
    if core not in (0,3):raise ValueError('Supported DMA cores are 0 and 3')
    before=snapshot()
    try:
        for irq in before:(Path('/proc/irq')/irq/'smp_affinity_list').write_text(str(core))
        after=verify(core)
    except BaseException:
        for irq,value in before.items():(Path('/proc/irq')/irq/'smp_affinity_list').write_text(value['requested'])
        raise
    return {'before':before,'after':after}


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--core',type=int,choices=(0,3),required=True)
    args=ap.parse_args(); print(json.dumps(configure(args.core)))
