"""Build the independently verified header simplification in an isolated project."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text,newline='\n')
for kind in ('synth','implement'):
    text=(ROOT/f'scripts/branch512_drop166_{kind}.tcl').read_text()
    text=text.replace('branch512_drop166','branch512_guard166').replace('branch512-drop166','branch512-guard166')
    text=text.replace('check_branch512_drop_software.py','check_branch512_guard_software.py').replace('BRANCH512_DROP166','BRANCH512_GUARD166')
    if kind=='synth':
        text=text.replace('open_project $root/build/branch512_outslice166_system/Prototype_v3_branch512_outslice166.xpr',
                          'open_project $root/build/branch512_drop166_system/Prototype_v3_branch512_drop166.xpr')
        text=text.replace('qn_branch512_drop_axis.sv','qn_branch512_guard_axis.sv').replace('qn_branch512_drop_inner.sv','qn_branch512_guard_inner.sv')
        text=text.replace('foreach source {qn_branch512_outslice_axis.sv',
                          'foreach source {qn_branch512_drop_axis.sv qn_branch512_drop_inner.sv qn_branch512_outslice_axis.sv',1)
    save(f'scripts/branch512_guard166_{kind}.tcl',text)
build='''$ErrorActionPreference = 'Stop'
$asrGuardRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $asrGuardRoot
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_guard_software.py
if ($LASTEXITCODE -ne 0) { throw 'Exact header equivalence or independent regression gate failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_guard166_synth.tcl -log build/branch512_guard166_synth_vivado.log -journal build/branch512_guard166_synth_vivado.jou *> build/branch512_guard166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Guard synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_guard166_implement.tcl -log build/branch512_guard166_implement_vivado.log -journal build/branch512_guard166_implement_vivado.jou *> build/branch512_guard166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'Guard implementation failed; no qualified export.' }
Write-Output 'BRANCH512_GUARD166_ROUTED_GATE_FINISHED'
'''
save('scripts/build_branch512_guard166.ps1',build)
print('Prepared isolated guard166 full implementation; unchanged arithmetic and timing gates')
