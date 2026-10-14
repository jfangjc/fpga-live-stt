param([Parameter(Mandatory=$true)][int]$SynthesisPid)
$ErrorActionPreference = 'Stop'
$asrBuildRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrBuildRoot
$asrSynthesisLog = Join-Path $asrBuildRoot 'build/branch512_pipe166_synth_driver.log'
while ($true) {
    $asrLogText = Get-Content -LiteralPath $asrSynthesisLog -Raw
    if ($asrLogText -match 'SYNTH_COMPLETE\r?\n') { break }
    if (-not (Get-Process -Id $SynthesisPid -ErrorAction SilentlyContinue)) {
        throw 'Synthesis stopped without its completion marker; implementation was not launched.'
    }
    Start-Sleep -Seconds 5
}
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_software.py
if ($LASTEXITCODE -ne 0) { throw 'Source-bound software/RTL gate failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_pipe166_implement.tcl -log build/branch512_pipe166_implement_vivado.log -journal build/branch512_pipe166_implement_vivado.jou *> build/branch512_pipe166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Implementation failed; inspect the saved driver log.' }
Write-Output 'BRANCH512_PIPE166_ROUTED_GATE_FINISHED'
