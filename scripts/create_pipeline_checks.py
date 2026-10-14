"""Keep FPGA-first checks separate from CPU-first overlap experiments."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];directory=ROOT/'software/latency'
files=('overlap_session_benchmark.py','validate_overlap_session_oracle.py','validate_overlap_session_physical.py',
       'tune_overlap_session_policy.py','confirm_overlap_session_latency.py')
for name in files:
    source=(directory/name).read_text().replace('software/ort_fpga_overlap_session','software/ort_fpga_pipeline')
    source=source.replace('session_graph','pipeline_graph').replace('overlap_session_native_oracle','pipeline_native_oracle')
    source=source.replace('overlap_session_benchmark','pipeline_benchmark')
    (directory/name.replace('overlap_session','pipeline')).write_text(source)
print('Created separate FPGA-first pipeline checks')
