"""Record routed cached hardware evidence without claiming board execution."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
timing = (root/'reports/cached_dma_timing.rpt').read_text()
pattern = r'WNS\(ns\).*?\n\s*-.*?\n\s*([-\d.]+)\s+([-\d.]+)\s+\d+\s+\d+\s+([-\d.]+)\s+([-\d.]+)'
match = re.search(pattern,timing,re.S)
if not match or any(float(x)<0 for x in match.groups()):
    raise RuntimeError('Routed setup/hold timing must pass')
simulation = (root/'reports/cached_sim.log').read_text()
if 'PASS: 69 cached arithmetic/protocol/reset cases' not in simulation:
    raise RuntimeError('Cached simulation must pass')
utilization = (root/'reports/cached_dma_utilization.rpt').read_text()
def used(label):
    match = re.search(r'\| '+re.escape(label)+r'\s*\|\s*(\d+)',utilization)
    if not match:
        raise RuntimeError('Resource missing: '+label)
    return int(match.group(1))
files = ['rtl/qn_cached_axis.v','sim/tb_qn_cached_axis.sv',
         'voice_cached_dma/voice_cached_dma.runs/impl_1/voice_cached_dma_top.bit',
         'voice_cached_dma/voice_cached_dma.runs/impl_1/voice_cached_dma_top.bit.bin',
         'software/voice-cached.dts','software/voice-cached.dtbo',
         'software/tile-driver/prebuilt/6.8.0-1015-xilinx/qn_tile_cached.ko']
report = {
    'tool':'Vivado 2026.1', 'part':'xck26-sfvc784-2LV-c',
    'project':'voice_cached_dma','clock_target_hz':100000000,
    'setup_slack_ns':float(match.group(1)),'hold_slack_ns':float(match.group(3)),
    'all_user_timing_constraints_met':'All user specified timing constraints are met.' in timing,
    'rtl_simulation_cases_passed':69,
    'resources':{'lut':used('CLB LUTs'),'registers':used('CLB Registers'),
                 'bram_tiles':used('Block RAM Tile'),'uram':used('URAM'),'dsp':used('DSPs')},
    'sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files},
    'board_execution':'pending','performance_validated':False,'accuracy_validated':False,
    'scope':'Cached pointwise weights and input reuse; bounded RUN batching; existing quantization and native CPU depthwise retained.'}
(root/'reports/cached_hardware_validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
