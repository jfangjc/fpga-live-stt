"""Audit current BD and freshness of artifacts. Incomplete build is never PASS."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    bd=ROOT/'Prototype_v2.srcs/sources_1/bd/asr_v2_system/asr_v2_system.bd'
    d=json.loads(bd.read_text())['design']; comp=d['components']; nets=d['nets']
    expect={'c_addr_width':'64','c_include_sg':'1','c_sg_length_width':'23',
            'c_m_axis_mm2s_tdata_width':'128','c_s_axis_s2mm_tdata_width':'128'}
    assert all(comp['tensor_dma']['parameters'][k]['value']==v for k,v in expect.items())
    for source,lane in [('voice/irq',0),('tensor_dma/mm2s_introut',1),('tensor_dma/s2mm_introut',2)]:
        assert any(source in n['ports'] and f'irq_concat/In{lane}' in n['ports'] for n in nets.values()),source
    assert any('irq_concat/dout' in n['ports'] and 'ps/pl_ps_irq0' in n['ports'] for n in nets.values())
    segments=d['addressing']['/ps']['address_spaces']['Data']['segments']
    registers={v['address_block']:int(v['offset'],16) for v in segments.values()}
    assert registers['/voice/S_AXI/reg0']==0xa0000000
    assert registers['/tensor_dma/S_AXI_LITE/Reg']==0xa0010000
    assert registers['/tile_control/S_AXI/Reg']==0xa0020000
    for v in d['addressing']['/tensor_dma']['address_spaces'].values():
        regs=v['segments']; assert int(regs['SEG_ps_HP0_DDR_HIGH']['offset'],16)==0x800000000
    sources=[p for base in ['rtl','hardware'] for p in (ROOT/base).rglob('*') if p.is_file()]
    sources += [bd, ROOT/'scripts/integrate_v2.tcl', ROOT/'scripts/build_v2.tcl',
                ROOT/'Prototype_v2.srcs/constrs_1/imports/Lab2b-Files/kria-constraints.xdc']
    newest=max(p.stat().st_mtime for p in sources)
    expected=['reports/cached_dma_timing.rpt','reports/cached_dma_drc.rpt',
              'reports/cached_dma_utilization.rpt','deployment/asr_v2.xsa',
              'Prototype_v2.runs/impl_1/asr_v2_top.bit']
    artifacts={}
    for name in expected:
        p=ROOT/name
        artifacts[name]=dict(exists=p.exists(),fresh=p.exists() and p.stat().st_mtime>=newest,
                             sha256=digest(p) if p.exists() else None)
    dtss=list((ROOT/'deployment').rglob('*.dts'))
    overlays=[]
    for p in dtss:
        text=p.read_text()
        checks=dict(audio='0xa0000000' in text.lower(),dma='0xa0010000' in text.lower(),gpio='0xa0020000' in text.lower(),
                    irq89=bool(re.search(r'interrupts\s*=\s*<0\s+89\s+4>',text)),
                    irq90=bool(re.search(r'interrupts\s*=\s*<0\s+90\s+4>',text)),
                    irq91=bool(re.search(r'interrupts\s*=\s*<0\s+91\s+4>',text)))
        overlays.append(dict(path=str(p.relative_to(ROOT)),checks=checks,sha256=digest(p)))
    timing=ROOT/'reports/cached_dma_timing.rpt'; drc=ROOT/'reports/cached_dma_drc.rpt'
    timing_pass=timing.exists() and 'All user specified timing constraints are met.' in timing.read_text()
    drc_error_lines=[line for line in drc.read_text().splitlines() if re.search(r'\|\s*(Error|Critical Warning)\s*\|',line)] if drc.exists() else None
    drc_pass=drc.exists() and not drc_error_lines
    result=dict(bd_validated=d['design_info']['validated'],dma_parameters_match=True,
        irq_concat_match=True,register_addresses=registers,
        expected_ps_irq0_device_tree_spis=[89,90,91],artifacts=artifacts,overlays=overlays,
        timing_pass=timing_pass,drc_pass=drc_pass,drc_error_lines=drc_error_lines,
        complete=timing_pass and drc_pass and all(v['exists'] and v['fresh'] for v in artifacts.values()) and bool(overlays) and all(all(x['checks'].values()) for x in overlays),
        sources_sha256={str(p.relative_to(ROOT)):digest(p) for p in sources},
        limits=['Timestamps detect obvious staleness, not provenance alone; source hashes must be frozen with completed reports','IRQ mapping uses verified previous platform PS IRQ0 SPI89; physical overlay application must validate running board symbols','Pass requires successful routed timing/DRC and deployment checks beyond JSON wiring'])
    (ROOT/'verification/v2_hardware_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
