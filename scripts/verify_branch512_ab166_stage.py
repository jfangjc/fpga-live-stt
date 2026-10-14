"""Read-only checksum verification of staged qualification tools."""
import hashlib,json,os,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
paths=[p for p in (ROOT/'scripts').glob('*branch512_ab166*') if p.name.startswith(('prepare_','finalize_','install_','run_'))]
paths += list((ROOT/'software/latency').glob('*branch512_ab166*.py'))+list((ROOT/'software/latency').glob('test_ab_*.py'))
names=sorted(p.relative_to(ROOT).as_posix() for p in paths)
command='cd /home/ubuntu/prototype-v3-fused && sha256sum '+' '.join(shlex.quote(n) for n in names)
result=subprocess.run(['C:/Program Files/PuTTY/plink.exe','-batch','-hostkey','SHA256:LKipAYiol8maTkeoe4VDOwZRuJLRLhyp1Nd7iSMk+1I','-pw',os.environ['ASR_KV260_PASSWORD'],'ubuntu@192.168.1.111',command],capture_output=True,text=True)
assert result.returncode==0,'Read-only board checksum command failed'
remote={line.split(None,1)[1].strip():line.split(None,1)[0] for line in result.stdout.splitlines()}
local={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
assert remote==local,'Staged qualification source mismatch'
report={'complete':True,'hardware_execution':False,'read_only_board_check':True,'staged_files':len(names),'sources_sha256':local}
(ROOT/'reports/fused/branch512_ab166_staged_tools.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS:',len(names),'staged qualification files match local SHA256')
