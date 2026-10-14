import hashlib
import json
from pathlib import Path
root=Path(__file__).parent
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
files=['qnc.c','qnc.h','qnc.py','cross_build.sh','test_qnc.c','prebuilt/aarch64/libqnc.so']
report={'target':'Linux aarch64 Cortex-A53','compiler':'aarch64-linux-gnu-gcc-13 (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0',
        'flags':'-O3 -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off -mcpu=cortex-a53 -fPIC -shared',
        'sysroot':'existing Ubuntu 24.04 ARM64 glibc2.39 downloaded sysroot (read-only)',
        'source_and_binary_sha256':{name:digest(root/name) for name in files},
        'host_verification':{'compiler_warnings_as_errors':True,'int64_arithmetic_and_protocol_tests':'passed',
                             'address_sanitizer':'passed','undefined_behavior_sanitizer':'passed',
                             'cortex_a53_instruction_emulation':'NEON and QNC_FORCE_SCALAR tests passed under QEMU8.2.2',
                             'code_generation':'FDIV + FRINTN + TRN verified; no reciprocal approximations or FMA'},
        'target_binary_executed_on_kv260':False,'deployment_requirement':'Compile with make on the board or copy only prebuilt/aarch64/libqnc.so; exclude host x86 library'}
(root/'prebuilt/aarch64/provenance.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
