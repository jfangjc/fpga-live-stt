"""Compare measured FPGA production and transport costs with the verified parent."""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
rows=[];sources={}
for label in ('half','one'):
    for version,prefix in [('16 time lanes','shortcache'),('64 time lanes','shortwide')]:
        path=ROOT/f'reports/fused/{prefix}_scheduled_{label}.json';proof=json.loads(path.read_text())
        samples=[r['results']['fpga'] for r in proof['paired_runs']]
        row={'version':version,'context_seconds':proof['contexts'][0]['context_seconds']}
        for key in ('frontend_seconds','model_seconds','decode_seconds'):
            row[key]=float(np.median([r[key] for r in samples]))
        for key in ('ioctl_seconds','run_pack_seconds','unpack_seconds','active_cycles','input_stall_cycles','output_stall_cycles','tx_bytes','rx_bytes'):
            row[key]=float(np.median([r['counters'][key] for r in samples]))
        row['fpga_active_seconds']=row['active_cycles']/proof['pl_clock_hz']
        row['model_outside_transport_seconds']=float(np.median([r['model_seconds']-r['counters']['ioctl_seconds']-r['counters']['run_pack_seconds']-r['counters']['unpack_seconds'] for r in samples]))
        rows.append(row);sources[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
report={'complete':True,'scope':'Measured diagnostics; interval components overlap and must not be added together','sources_sha256':sources,'rows':rows}
(ROOT/'reports/fused/shortwide_counter_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(rows,indent=2))
