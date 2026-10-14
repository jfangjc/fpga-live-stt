$ErrorActionPreference = 'Stop'
$asrGuardRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrGuardRoot
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_guard_software.py
if ($LASTEXITCODE -ne 0) { throw 'Exact header equivalence or independent regression gate failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_guard166_synth.tcl -log build/branch512_guard166_synth_vivado.log -journal build/branch512_guard166_synth_vivado.jou *> build/branch512_guard166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Guard synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_guard166_implement.tcl -log build/branch512_guard166_implement_vivado.log -journal build/branch512_guard166_implement_vivado.jou *> build/branch512_guard166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Guard implementation failed; no qualified export.' }
Write-Output 'BRANCH512_GUARD166_ROUTED_GATE_FINISHED'
