"""Private DSP input-register retiming with the original two-cycle MAC latency."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text,newline='\n')
core=(ROOT/'rtl/experimental/qn_branch512_slice_pw_core.v').read_text()
core=core.replace('qn_branch512_slice_pw_core','qn_branch512_ab_pw_core')
changes={'.AREG(0),.ACASCREG(0),.BREG(0),.BCASCREG(0)':'.AREG(1),.ACASCREG(1),.BREG(1),.BCASCREG(1)',
         '.MREG(1),.PREG(1)':'.MREG(0),.PREG(1)',
         ".CEA2(1'b0),.CEB1(1'b0),.CEB2(1'b0)": ".CEA2(read_valid),.CEB1(1'b0),.CEB2(read_valid)",
         ".RSTA(1'b0),.RSTB(1'b0)":'.RSTA(!aresetn),.RSTB(!aresetn)'}
for old,new in changes.items():assert core.count(old)==1;core=core.replace(old,new)
save('rtl/experimental/qn_branch512_ab_pw_core.v',core)
save('sim/fast/qn_branch512_ab_pw_core.v',core.replace('DSP48E2 #(','qn_mac_ab_model #('))
inner=(ROOT/'rtl/experimental/qn_branch512_guard_inner.sv').read_text().replace('qn_branch512_guard_inner','qn_branch512_ab_inner').replace('qn_branch512_slice_pw_core','qn_branch512_ab_pw_core')
save('rtl/experimental/qn_branch512_ab_inner.sv',inner)
axis=(ROOT/'rtl/experimental/qn_branch512_guard_axis.sv').read_text().replace('qn_branch512_guard_inner','qn_branch512_ab_inner')
save('rtl/experimental/qn_branch512_ab_axis.sv',axis)
for kind in ('axis','reset','payload_reset'):
    tb=(ROOT/f'sim/tb_qn_branch512_guard_{kind}.sv').read_text().replace('branch512_guard','branch512_ab')
    save(f'sim/tb_qn_branch512_ab_{kind}.sv',tb)
    variant='fast' if kind=='axis' else kind
    tcl=(ROOT/f'scripts/branch512_guard_{variant}_sim.tcl').read_text().replace('branch512_guard','branch512_ab').replace('qn_branch512_slice_pw_core','qn_branch512_ab_pw_core').replace('qn_mac_model','qn_mac_ab_model')
    save(f'scripts/branch512_ab_{variant}_sim.tcl',tcl)
print('Prepared private A/B-input-register MAC; controller latency and datapath arithmetic unchanged')
