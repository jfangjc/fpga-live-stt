"""Prepare a separate DMA burst experiment; retain qualified arithmetic/clock."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parent = 'branch512_ab166'
candidate = 'branch512_dma128166'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
proof_path = ROOT/'reports/fused/branch512_ab_regression_evidence.json'
proof = json.loads(proof_path.read_text())
assert proof['complete']
parent_xci = ROOT/'build/branch512_ab166_system/Prototype_v3_branch512_ab166.srcs/sources_1/bd/asr_v2_system/ip/asr_v2_system_tensor_dma_0/asr_v2_system_tensor_dma_0.xci'
parameters = json.loads(parent_xci.read_text())['ip_inst']['parameters']['component_parameters']
for key, value in [('c_mm2s_burst_size', 16), ('c_s2mm_burst_size', 16),
                   ('c_m_axi_mm2s_data_width', 128), ('c_m_axi_s2mm_data_width', 128)]:
    assert int(parameters[key][0]['value']) == value, key
for name, value in proof['sources_sha256'].items():
    assert sha(ROOT/name) == value, name

def save(name, text):
    path = ROOT/name
    if path.exists(): assert path.read_text() == text, path
    else: path.write_text(text, newline='\n')

synth = (ROOT/f'scripts/{parent}_synth.tcl').read_text().replace(parent, candidate)
synth = synth.replace('open_project $root/build/branch512_guard166_system/Prototype_v3_branch512_guard166.xpr',
                      'open_project $root/build/branch512_ab166_system/Prototype_v3_branch512_ab166.xpr')
anchor = 'validate_bd_design\nsave_bd_design'
assert anchor in synth
synth = synth.replace(anchor, '''# DMA configuration only: retain all tile arithmetic, protocol and clocks.
set dma [get_bd_cells -quiet tensor_dma]
if {[llength $dma]!=1} {error "Expected one DMA in isolated clone"}
if {[get_property CONFIG.c_m_axi_mm2s_data_width $dma]!=128 || [get_property CONFIG.c_m_axi_s2mm_data_width $dma]!=128} {error "Preserve existing 128-bit memory interfaces"}
set_property -dict [list CONFIG.c_mm2s_burst_size {128} CONFIG.c_s2mm_burst_size {128}] $dma
if {[get_property CONFIG.c_mm2s_burst_size $dma]!=128 || [get_property CONFIG.c_s2mm_burst_size $dma]!=128} {error "Burst configuration not applied"}
validate_bd_design
save_bd_design''')
synth = synth.replace('BRANCH512_AB166_SYNTH_COMPLETE', 'BRANCH512_DMA128166_SYNTH_COMPLETE')
save(f'scripts/{candidate}_synth.tcl', synth)
implement = (ROOT/f'scripts/{parent}_implement.tcl').read_text().replace(parent, candidate)
implement = implement.replace('asr-v3-branch512-ab166', 'asr-v3-branch512-dma128166')
implement = implement.replace('asr_v3_branch512_ab166', 'asr_v3_branch512_dma128166')
# Arithmetic and the positive setup margin remain inherited from the parent.
assert '$setup<0.001 || $hold<0' in implement
save(f'scripts/{candidate}_implement.tcl', implement)
build = '''$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $taskRoot
& 'C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -I scripts/check_branch512_ab_software.py
if ($LASTEXITCODE -ne 0) { throw 'Qualified parent source proof failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_dma128166_synth.tcl -log build/branch512_dma128166_synth_vivado.log -journal build/branch512_dma128166_synth_vivado.jou *> build/branch512_dma128166_synth_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DMA burst synthesis failed.' }
& 'C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat' -mode batch -source scripts/branch512_dma128166_implement.tcl -log build/branch512_dma128166_implement_vivado.log -journal build/branch512_dma128166_implement_vivado.jou *> build/branch512_dma128166_implement_driver.log
if ($LASTEXITCODE -ne 0) { throw 'DMA burst implementation failed; no qualified export.' }
Write-Output 'DMA128166_ROUTED_GATE_FINISHED'
'''
save(f'scripts/build_{candidate}.ps1', build)
paths = [ROOT/f'scripts/{candidate}_synth.tcl', ROOT/f'scripts/{candidate}_implement.tcl',
         ROOT/f'scripts/build_{candidate}.ps1', Path(__file__)]
report = {'complete': True, 'preparation_only': True, 'hardware_execution': False,
          'candidate_qualified': False, 'clock_hz': 166666666, 'pointwise_macs': 512,
          'depthwise_macs': 64, 'parent_regression_sha256': sha(proof_path),
          'parent_dma_burst_beats': 16, 'candidate_dma_burst_beats': 128,
          'memory_data_width_bits': 128, 'arithmetic_and_protocol_changes': False,
          'parent_dma_xci_sha256': sha(parent_xci),
          'source_reference': 'https://docs.amd.com/r/en-US/pg021_axi_dma/Field-Descriptions',
          'sources_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
          'note': 'No build, firmware deployment or latency claim. Requires routed timing/DRC, DMA boundary and physical output qualification.'}
(ROOT/'reports/fused/branch512_dma128166_preparation.json').write_text(json.dumps(report, indent=2)+'\n')
print('Prepared isolated DMA burst experiment; no qualified project modified or build started')
