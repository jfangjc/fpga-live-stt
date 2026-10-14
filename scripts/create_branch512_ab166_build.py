"""Isolated 166.667 MHz build of the source-bound DSP input-register retiming."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def save(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,path
    else:path.write_text(text,newline='\n')
for kind in ('synth','implement'):
    text=(ROOT/f'scripts/branch512_guard166_{kind}.tcl').read_text()
    text=text.replace('branch512_guard166','branch512_ab166').replace('branch512-guard166','branch512-ab166')
    text=text.replace('check_branch512_guard_software.py','check_branch512_ab_software.py').replace('BRANCH512_GUARD166','BRANCH512_AB166')
    if kind=='synth':
        text=text.replace('open_project $root/build/branch512_drop166_system/Prototype_v3_branch512_drop166.xpr',
                          'open_project $root/build/branch512_guard166_system/Prototype_v3_branch512_guard166.xpr')
        text=text.replace('qn_branch512_guard_axis.sv','qn_branch512_ab_axis.sv').replace('qn_branch512_guard_inner.sv','qn_branch512_ab_inner.sv').replace('qn_branch512_slice_pw_core.v','qn_branch512_ab_pw_core.v')
        text=text.replace('foreach source {qn_branch512_drop_axis.sv',
                          'foreach source {qn_branch512_guard_axis.sv qn_branch512_guard_inner.sv qn_branch512_slice_pw_core.v qn_branch512_drop_axis.sv',1)
        text=text.replace('if {[llength [get_files -quiet */qn_mac_model.sv]]',
                          'if {[llength [get_files -quiet */qn_mac_ab_model.sv]] || [llength [get_files -quiet */qn_mac_model.sv]]')
    save(f'scripts/branch512_ab166_{kind}.tcl',text)
build='''$ErrorActionPreference = 'Stop'
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
'''
save('scripts/build_branch512_ab166.ps1',build)
print('Prepared isolated retimed 512-MAC build; unchanged final setup/hold/DRC gates')
