$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $taskRoot
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_ab_software.py
if ($LASTEXITCODE -ne 0) { throw 'Qualified parent source proof failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_dma128166_synth.tcl -log build/branch512_dma128166_synth_vivado.log -journal build/branch512_dma128166_synth_vivado.jou *> build/branch512_dma128166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DMA burst synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_dma128166_implement.tcl -log build/branch512_dma128166_implement_vivado.log -journal build/branch512_dma128166_implement_vivado.jou *> build/branch512_dma128166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DMA burst implementation failed; no qualified export.' }
Write-Output 'DMA128166_ROUTED_GATE_FINISHED'
