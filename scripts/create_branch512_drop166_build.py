"""Separate exact DW pipeline build with reusable static IP cache."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    dest=ROOT/name
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
for kind in ('synth','implement'):
    text=(ROOT/f'scripts/branch512_outslice166_{kind}.tcl').read_text()
    text=text.replace('branch512_outslice166','branch512_drop166').replace('branch512-outslice166','branch512-drop166').replace('check_branch512_outslice_software.py','check_branch512_drop_software.py').replace('BRANCH512_OUTSLICE166','BRANCH512_DROP166')
    if kind=='synth':
        text=text.replace('open_project $root/build/stream_system/Prototype_v3_stream.xpr','open_project $root/build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.xpr')
        text=text.replace('qn_stream_axis.sv qn_stream_inner.sv', 'qn_branch512_outslice_axis.sv qn_branch512_slice_inner.sv fused_depthwise_bimodal.sv fused_affine_quant_compact.sv qn_stream_axis.sv qn_stream_inner.sv')
        text=text.replace('qn_branch512_outslice_axis.sv qn_branch512_slice_inner.sv qn_branch512_slice_pw_core.v fused_depthwise_bimodal.sv fused_affine_quant_compact.sv fused_affine_quant_select_wrap.sv',
                          'qn_branch512_drop_axis.sv qn_branch512_drop_inner.sv qn_branch512_slice_pw_core.v fused_depthwise_droppipe.sv fused_affine_quant_drop_pipe.sv fused_affine_quant_select_wrap.sv')
    if kind=='implement':
        text=text.replace('reset_run impl_1\nlaunch_runs', '''reset_run impl_1
# BASIC license does not support read_checkpoint -incremental.
# Clear persisted settings and run full placement/routing.
set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs impl_1]
set_property incremental_checkpoint {} [get_runs impl_1]
launch_runs''')
    save(f'scripts/branch512_drop166_{kind}.tcl',text)
build='''$ErrorActionPreference = 'Stop'
$asrDropRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrDropRoot
$asrDropMarkers = @{
 'build/drop_requant_sim/drop_requant_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 9600 float32-equivalent lanes'
 'build/branch512_drop_fast_sim/branch512_drop_fast_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 25 two-output residual branches'
 'build/branch512_drop_reset_sim/branch512_drop_reset_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 6 full-pipeline reset/replay cases'
 'build/branch512_drop_payload_reset_sim/branch512_drop_payload_reset_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 2 full output-data buffer reset/replay cases'
}
$asrDropDeadline = (Get-Date).AddHours(1)
foreach ($asrDropEntry in $asrDropMarkers.GetEnumerator()) {
 while ($true) {
  if (Test-Path -LiteralPath $asrDropEntry.Key) {
   $asrDropText = Get-Content -LiteralPath $asrDropEntry.Key -Raw
   if ($asrDropText -match 'Fatal:|ERROR:|cannot be opened for reading') { throw 'DW pipeline regression failed; build not started.' }
   if ($asrDropText.Contains($asrDropEntry.Value)) { break }
  }
  if ((Get-Date) -gt $asrDropDeadline) { throw 'DW regression timeout; build not started.' }
  Start-Sleep -Seconds 5
 }
}
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/bind_branch512_drop_regression.py
if ($LASTEXITCODE -ne 0) { throw 'DW pipeline proof binding failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_drop166_synth.tcl -log build/branch512_drop166_synth_vivado.log -journal build/branch512_drop166_synth_vivado.jou *> build/branch512_drop166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DW pipeline synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_drop166_implement.tcl -log build/branch512_drop166_implement_vivado.log -journal build/branch512_drop166_implement_vivado.jou *> build/branch512_drop166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DW pipeline implementation failed; no qualified export.' }
Write-Output 'BRANCH512_DROP166_ROUTED_GATE_FINISHED'
'''
save('scripts/build_branch512_drop166.ps1',build)
print('Prepared separate DW pipeline build; unchanged final setup/hold/DRC gates')
