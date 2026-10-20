"""Record the compiled packet test and matching board-kernel driver."""
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'deployment/experimental-stream'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
log=ROOT/'reports/fused/stream_protocol_test.log';match=re.search(r'PASS: (\d+) streamed block',log.read_text());assert match
assert int(match[1])>=177152
driver=folder/'qn_tile.ko';vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(driver)],text=True).strip()
assert vermagic.startswith('6.8.0-1036-xilinx')
paths=[folder/n for n in ('qn_tile.c','qn_cache_protocol.h','qn_layer_protocol.h','qn_tile_uapi.h','test_stream_protocol.c')]
proof={'complete':True,'hardware_execution':False,'checks':int(match[1]),'driver_sha256':sha(driver),'driver_vermagic':vermagic,
       'test_executable_sha256':sha(folder/'test_stream_protocol'),'log_sha256':sha(log),
       'sources_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths}}
(ROOT/'reports/fused/stream_protocol_validation.json').write_text(json.dumps(proof,indent=2)+'\n')
print('PASS: streamed packet and kernel driver proof bound')
