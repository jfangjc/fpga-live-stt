$ErrorActionPreference = 'Stop'
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
