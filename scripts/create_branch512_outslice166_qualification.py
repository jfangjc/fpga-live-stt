"""Bind new qualification to its own firmware/proof; never deploy failed slice166."""
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
names=[
 'scripts/prepare_branch512_slice166_firmware.py','scripts/finalize_branch512_slice166_firmware.py',
 'scripts/install_branch512_slice166_firmware.py','scripts/run_branch512_slice166_board.sh',
 'scripts/qualify_branch512_slice166.py','software/latency/branch512_slice166_benchmark.py',
 'software/latency/test_branch512_slice166_blocks.py','software/latency/validate_branch512_slice166_physical.py',
 'software/latency/tune_branch512_slice166_policy.py','software/latency/confirm_branch512_slice166_latency.py']
for variant in ('scale','more','neon'):
    names += [f'scripts/qualify_branch512_slice166_{variant}.py',
              f'software/latency/branch512_slice166_{variant}_benchmark.py',
              f'software/latency/validate_branch512_slice166_{variant}_physical.py',
              f'software/latency/tune_branch512_slice166_{variant}_policy.py',
              f'software/latency/confirm_branch512_slice166_{variant}_latency.py']
for name in names:
    text=(ROOT/name).read_text().replace('branch512_slice166','branch512_outslice166').replace('branch512-slice166','branch512-outslice166')
    text=text.replace('check_branch512_slice_software.py','check_branch512_outslice_software.py').replace('branch512_slice_regression_evidence.json','branch512_outslice_regression_evidence.json')
    if '/qualify_' in name:
        for old,new in (('test_scale_split_pairs_physical.py','test_outslice_scale_split_pairs_physical.py'),('test_stride_pointwise_physical.py','test_outslice_stride_pointwise_physical.py'),('test_neon_pointwise_physical.py','test_outslice_neon_pointwise_physical.py')):
            text=text.replace(old,new)
        # Windows PowerShell native redirection can produce UTF-16 logs.
        helper='''def read_log(path):
    data=path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\\xff\\xfe',b'\\xfe\\xff')) else 'utf-8',errors='replace')

def timing_failed(path):
    # Tcl echoes gate commands; only actual error lines indicate failure.
    return any(line.strip()=='Chain timing or DRC gate failed' or line.lstrip().startswith('ERROR:')
               for line in read_log(path).splitlines())

'''
        index=text.index('def local(')
        text=text[:index]+helper+text[index:]
        text=re.sub(r"(\w+)\.read_text\(errors='replace'\)",r'read_log(\1)',text)
        text=text.replace("any((line.startswith('ERROR:') or 'Chain timing or DRC gate failed' in line) for line in read_log(log).splitlines())", 'timing_failed(log)')
        text=text.replace("'Chain timing or DRC gate failed' in read_log(log)", 'timing_failed(log)')
        text=text.replace('FPGA-ASR-broader-retention-confirmed-2026-10-13','FPGA-ASR-output-pipeline-retention-confirmed-2026-10-13').replace('FPGA-ASR-vector-retention-confirmed-2026-10-13','FPGA-ASR-output-pipeline-vector-confirmed-2026-10-13')
    dest=ROOT/name.replace('branch512_slice166','branch512_outslice166')
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
for old,new in (('test_scale_split_pairs_physical.py','test_outslice_scale_split_pairs_physical.py'),('test_stride_pointwise_physical.py','test_outslice_stride_pointwise_physical.py'),('test_neon_pointwise_physical.py','test_outslice_neon_pointwise_physical.py')):
    text=(ROOT/'software/latency'/old).read_text().replace('branch512_slice166','branch512_outslice166')
    dest=ROOT/'software/latency'/new
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
print('Prepared separate source-bound deployment and sequential physical qualification')
