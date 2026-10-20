"""Summarize measured transport and CPU-region costs without double counting."""
import json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
rows=[]
for label in ('half','one'):
    p=json.loads((ROOT/f'reports/fused/shortcache_total_{label}.json').read_text())
    f=[r['results']['fpga'] for r in p['paired_runs']]
    result={'context_seconds':p['contexts'][0]['context_seconds']}
    for key in ('frontend_seconds','model_seconds','decode_seconds'):
        result[key]=float(np.median([r[key] for r in f]))
    for key in ('ioctl_seconds','run_pack_seconds','unpack_seconds','active_cycles',
                'input_stall_cycles','output_stall_cycles','tx_bytes','rx_bytes'):
        result[key]=float(np.median([r['counters'][key] for r in f]))
    result['fpga_active_seconds']=result['active_cycles']/p['pl_clock_hz']
    result['model_outside_transport_seconds']=float(np.median([
        r['model_seconds']-r['counters']['ioctl_seconds']-
        r['counters']['run_pack_seconds']-r['counters']['unpack_seconds'] for r in f]))
    rows.append(result)
print(json.dumps(rows,indent=2))
