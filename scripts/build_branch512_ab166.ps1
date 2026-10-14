$ErrorActionPreference = 'Stop'
$asrAbRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrAbRoot
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/bind_branch512_ab_regression.py
if ($LASTEXITCODE -ne 0) { throw 'Real DSP retiming or full-block regression gate failed.' }
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_ab_software.py
if ($LASTEXITCODE -ne 0) { throw 'DSP retiming source proof failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_ab166_synth.tcl -log build/branch512_ab166_synth_vivado.log -journal build/branch512_ab166_synth_vivado.jou *> build/branch512_ab166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DSP input-register retiming synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_ab166_implement.tcl -log build/branch512_ab166_implement_vivado.log -journal build/branch512_ab166_implement_vivado.jou *> build/branch512_ab166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Retimed implementation failed; no qualified export.' }
Write-Output 'BRANCH512_AB166_ROUTED_GATE_FINISHED'
