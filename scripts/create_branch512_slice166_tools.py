"""Clone unqualified PIPE166 tooling; preserve every earlier candidate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
names=[
 'scripts/branch512_pipe166_synth.tcl','scripts/branch512_pipe166_implement.tcl',
 'scripts/prepare_branch512_pipe166_firmware.py','scripts/finalize_branch512_pipe166_firmware.py',
 'scripts/install_branch512_pipe166_firmware.py','scripts/run_branch512_pipe166_board.sh',
 'scripts/qualify_branch512_pipe166.py','software/latency/branch512_pipe166_benchmark.py',
 'software/latency/test_branch512_pipe166_blocks.py','software/latency/validate_branch512_pipe166_physical.py',
 'software/latency/tune_branch512_pipe166_policy.py','software/latency/confirm_branch512_pipe166_latency.py']
for name in names:
    text=(ROOT/name).read_text().replace('branch512_pipe166','branch512_slice166').replace('asr-v3-branch512-pipe166','asr-v3-branch512-slice166')
    if name.endswith('qualify_branch512_pipe166.py'):
        text=text.replace('    subprocess.run([str(a) for a in args],cwd=cwd,check=True)', "    result=subprocess.run([str(a) for a in args],cwd=cwd)\n    if result.returncode:raise RuntimeError(f'Tool {Path(args[0]).name} failed with exit code {result.returncode}')")
        text=text.replace("line.startswith('ERROR:')","(line.startswith('ERROR:') or 'Chain timing or DRC gate failed' in line)")
    if name.endswith('_synth.tcl'):
        text=text.replace('check_branch512_software.py','check_branch512_slice_software.py').replace('voice_axi_auto_clock.v','voice_axi_inference.v')
        text=text.replace('qn_branch512_pipe_','qn_branch512_slice_').replace('BRANCH512_PIPE150_SYNTH_COMPLETE','BRANCH512_SLICE166_SYNTH_COMPLETE')
    if name.endswith('_implement.tcl'):
        text=text.replace('check_branch512_software.py','check_branch512_slice_software.py')
    if 'prepare_' in name:
        a=text.index('original_voice=');b=text.index('paths=[]',a)
        text=text[:a]+"exec((ROOT/'scripts/check_branch512_slice_software.py').read_text(),{'__file__':str(ROOT/'scripts/check_branch512_slice_software.py')})\n"+text[b:]
        text=text.replace("('branch512_regression_evidence.json','sources_sha256')","('branch512_slice_regression_evidence.json','sources_sha256')")
        text=text.replace('voice_axi_auto_clock.v','voice_axi_inference.v')
        text=text.replace('capture_clock_changed=True','capture_clock_changed=True,legacy_mac_disabled=True')
    dest=ROOT/name.replace('branch512_pipe166','branch512_slice166')
    if dest.exists():assert dest.read_text()==text,dest
    else:dest.write_text(text,newline='\n')
print('Prepared separate slice166 build, timing gate and restored-board qualification tools')
