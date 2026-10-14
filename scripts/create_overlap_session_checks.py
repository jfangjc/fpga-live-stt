"""Clone overlap checks while preserving the measured direct-invocation variant."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];directory=ROOT/'software/latency'
files=('overlap_benchmark.py','validate_overlap_oracle.py','validate_overlap_physical.py','tune_overlap_policy.py','confirm_overlap_latency.py')
for name in files:
    source=(directory/name).read_text()
    source=source.replace('software/ort_fpga_overlap/','software/ort_fpga_overlap_session/').replace("ROOT/'software/ort_fpga_overlap'","ROOT/'software/ort_fpga_overlap_session'")
    source=source.replace('from overlap_graph import fuse_residuals','from session_graph import fuse_residuals')
    source=source.replace('overlap_graph.py','session_graph.py').replace('overlap_native_oracle.json','overlap_session_native_oracle.json')
    source=source.replace('from overlap_benchmark import *','from overlap_session_benchmark import *')
    if name=='overlap_benchmark.py':
        source=source.replace("'overlapped_residual_branches':8","'overlapped_residual_branches':8,'nested_cpu_sessions':8,'nested_cpu_threads':4")
    (directory/name.replace('overlap','overlap_session')).write_text(source)
print('Created separate prepacked residual overlap checks')
