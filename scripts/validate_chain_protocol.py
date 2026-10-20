"""Bind compiled packet/mock transport checks and driver compatibility."""
import hashlib,json,platform,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
reports=ROOT/'reports/fused';reports.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
tests=[]
for folder,sources,name,expected in (
    ('deployment/experimental-chain',['test_short_protocol.c'],'chain_packets', 'PASS: 120068'),
    ('software/ort_fpga_chain',['test_slot_transport.c','qnc_transport.c'],'chain_transport','384 chain packets')):
    directory=ROOT/folder;exe=reports/name
    command=['gcc','-O2','-std=c11','-Wall','-Wextra','-Werror',*sources,'-o',str(exe)]
    subprocess.run(command,cwd=directory,check=True)
    output=subprocess.check_output([str(exe)],text=True);assert expected in output
    (reports/(name+'.log')).write_text(output)
    tests.append({'name':name,'command':command,'stdout':output.strip(),'binary_sha256':sha(exe),
                  'sources_sha256':{(directory/s).relative_to(ROOT).as_posix():sha(directory/s) for s in sources}})
driver=ROOT/'deployment/experimental-chain/qn_tile.ko'
vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).strip()
assert vermagic.split()[0]==platform.release()
proof={'complete':True,'hardware_execution':False,'source_sha256':sha(Path(__file__)),
       'kernel':platform.release(),'driver_vermagic':vermagic,'driver_sha256':sha(driver),'tests':tests,
       'headers_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in
                        (ROOT/'software/ort_fpga_chain/qnc.h',ROOT/'deployment/experimental-chain/qn_cache_protocol.h')}}
(reports/'chain_protocol_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
