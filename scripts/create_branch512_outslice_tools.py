"""Prepare isolated build/proof tooling for the registered output candidate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists(): assert path.read_text()==text,path
    else: path.write_text(text,newline='\n')

bind=(ROOT/'scripts/bind_branch512_slice_regression.py').read_text()
bind=bind.replace('branch512_slice_fast','branch512_outslice_fast').replace('branch512_slice_reset','branch512_outslice_reset').replace('PASS: 4 full-pipeline reset/replay cases','PASS: 6 full-pipeline reset/replay cases')
bind=bind.replace("('qn_branch512_slice_axis.sv','qn_branch512_slice_inner.sv'", "('qn_branch512_outslice_axis.sv','qn_branch512_slice_inner.sv'")
bind=bind.replace('tb_qn_branch512_slice_axis.sv','tb_qn_branch512_outslice_axis.sv').replace('tb_qn_branch512_slice_reset.sv','tb_qn_branch512_outslice_reset.sv')
bind=bind.replace("'create_branch512_slice.py','create_branch512_slice_reset.py','branch512_slice_fast_sim.tcl','branch512_slice_reset_sim.tcl'", "'create_branch512_outslice.py','create_branch512_outslice_tools.py','branch512_outslice_fast_sim.tcl','branch512_outslice_reset_sim.tcl'")
bind=bind.replace('bind_branch512_slice_regression.py','bind_branch512_outslice_regression.py').replace('branch512_slice_regression_evidence.json','branch512_outslice_regression_evidence.json').replace("'full_pipeline_reset_replay_cases':4","'full_pipeline_reset_replay_cases':6").replace('four stream/quantizer resets','six output/stream/quantizer resets')
bind=bind.replace("'create_branch512_slice.py','create_branch512_outslice_reset.py'", "'create_branch512_outslice.py','create_branch512_outslice_tools.py'")
bind=bind.replace("('voice_inference','PASS: 77 AXI accesses')", "('branch512_outslice_payload_reset','PASS: 2 full output-data buffer reset/replay cases'),\n                       ('voice_inference','PASS: 77 AXI accesses')")
bind=bind.replace("'voice_axi_accesses':77,", "'voice_axi_accesses':77,'output_data_reset_replay_cases':2,")
bind=bind.replace("paths += [ROOT/'rtl/sph0645_rx.v'", "paths += [ROOT/'sim/tb_qn_branch512_outslice_payload_reset.sv',ROOT/'scripts/create_branch512_outslice_payload_reset.py',ROOT/'scripts/branch512_outslice_payload_reset_sim.tcl']\npaths += [ROOT/'rtl/sph0645_rx.v'")
save('scripts/bind_branch512_outslice_regression.py',bind)
check=(ROOT/'scripts/check_branch512_slice_software.py').read_text().replace('branch512_slice_regression_evidence.json','branch512_outslice_regression_evidence.json').replace("['full_pipeline_reset_replay_cases']==4","['full_pipeline_reset_replay_cases']==6").replace('registered stream boundary','registered input/output boundaries')
check=check.replace("for name,value in p['sources_sha256'].items():", "assert p['output_data_reset_replay_cases']==2\nfor name,value in p['sources_sha256'].items():")
save('scripts/check_branch512_outslice_software.py',check)
for kind in ('synth','implement'):
    text=(ROOT/f'scripts/branch512_slice166_{kind}.tcl').read_text().replace('branch512_slice166','branch512_outslice166').replace('branch512-slice166','branch512-outslice166').replace('check_branch512_slice_software.py','check_branch512_outslice_software.py').replace('qn_branch512_slice_axis.sv','qn_branch512_outslice_axis.sv').replace('BRANCH512_SLICE166','BRANCH512_OUTSLICE166')
    save(f'scripts/branch512_outslice166_{kind}.tcl',text)
build=(ROOT/'scripts/build_branch512_slice166.ps1').read_text().replace('branch512_slice166','branch512_outslice166').replace('branch512_slice_fast','branch512_outslice_fast').replace('branch512_slice_reset','branch512_outslice_reset').replace('bind_branch512_slice_regression.py','bind_branch512_outslice_regression.py').replace('PASS: 4 full-pipeline reset/replay cases','PASS: 6 full-pipeline reset/replay cases').replace('BRANCH512_SLICE166','BRANCH512_OUTSLICE166')
save('scripts/build_branch512_outslice166.ps1',build)
print('Prepared source-bound output-slice proof, synthesis and routed timing gate')
