$ErrorActionPreference = 'Stop'
$asrSliceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrSliceRoot
$asrSliceMarkers = @{
 'build/branch512_slice_fast_sim/branch512_slice_fast_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 25 two-output residual branches'
 'build/branch512_slice_reset_sim/branch512_slice_reset_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 4 full-pipeline reset/replay cases'
 'build/voice_inference_sim/voice_inference_sim.sim/sim_1/behav/xsim/simulate.log' = 'PASS: 77 AXI accesses'
}
$asrSliceDeadline = (Get-Date).AddHours(1)
foreach ($asrSliceEntry in $asrSliceMarkers.GetEnumerator()) {
 while ($true) {
  if (Test-Path -LiteralPath $asrSliceEntry.Key) {
   $asrSliceText = Get-Content -LiteralPath $asrSliceEntry.Key -Raw
   if ($asrSliceText -match 'Fatal:|ERROR:|cannot be opened for reading') { throw 'Slice RTL regression failed; build not started.' }
   if ($asrSliceText.Contains($asrSliceEntry.Value)) { break }
  }
  if ((Get-Date) -gt $asrSliceDeadline) { throw 'Slice regression timeout; build not started.' }
  Start-Sleep -Seconds 5
 }
}
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/bind_branch512_slice_regression.py
if ($LASTEXITCODE -ne 0) { throw 'Slice proof binding failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_slice166_synth.tcl -log build/branch512_slice166_synth_vivado.log -journal build/branch512_slice166_synth_vivado.jou *> build/branch512_slice166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Slice synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_slice166_implement.tcl -log build/branch512_slice166_implement_vivado.log -journal build/branch512_slice166_implement_vivado.jou *> build/branch512_slice166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Slice implementation failed; no qualified export.' }
Write-Output 'BRANCH512_SLICE166_ROUTED_GATE_FINISHED'
