"""Private exact header simplification of the DW-pipelined candidate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text,newline='\n')
old=(ROOT/'rtl/experimental/qn_branch512_drop_inner.sv').read_text()
guard='hk*((ht+15)>>4)<=4096 && '
assert old.count(guard)==1
assert 'hk==256 && hm==256 && ht>0 && ht<=256 &&' in old
new=old.replace('qn_branch512_drop_inner','qn_branch512_guard_inner').replace(guard,'')
save('rtl/experimental/qn_branch512_guard_inner.sv',new)
axis=(ROOT/'rtl/experimental/qn_branch512_drop_axis.sv').read_text().replace('qn_branch512_drop_inner','qn_branch512_guard_inner')
save('rtl/experimental/qn_branch512_guard_axis.sv',axis)
for kind in ('axis','reset','payload_reset'):
    tb=(ROOT/f'sim/tb_qn_branch512_drop_{kind}.sv').read_text().replace('branch512_drop','branch512_guard')
    save(f'sim/tb_qn_branch512_guard_{kind}.sv',tb)
    variant='fast' if kind=='axis' else kind
    tcl=(ROOT/f'scripts/branch512_drop_{variant}_sim.tcl').read_text().replace('branch512_drop','branch512_guard')
    save(f'scripts/branch512_guard_{variant}_sim.tcl',tcl)
print('Prepared private redundant-header-guard removal; all datapath and handshake RTL unchanged')
