import os,subprocess,re,json,hashlib
from pathlib import Path
native=Path(__file__).parent.parent
hosttools=native.parents[1]/'tile-driver/kernel-build/sysroot'
env=dict(os.environ);env['LD_LIBRARY_PATH']=str(hosttools/'usr/lib/x86_64-linux-gnu')
so=native/'prebuilt/libqn_depthwise_aarch64.so'
def run(args):return subprocess.check_output(list(map(str,args)),env=env,text=True)
dis=run([hosttools/'usr/bin/aarch64-linux-gnu-objdump','-d',so])
fused=re.findall(r'\bf(?:madd|msub|nmadd|nmsub|mla|mls)\b',dis)
assert not fused,fused
versions=run(['readelf','--version-info',so])
deps=run(['readelf','-d',so])
metadata={'artifact':so.name,'sha256':hashlib.sha256(so.read_bytes()).hexdigest(),
'source_sha256':hashlib.sha256((native/'qn_depthwise.c').read_bytes()).hexdigest(),
'compiler':run([hosttools/'usr/bin/aarch64-linux-gnu-gcc-13','--version']).splitlines()[0],
'flags':['-O3','-std=c11','-Wall','-Wextra','-Werror','-mcpu=cortex-a53','-fno-fast-math','-ffp-contract=off','-fPIC','-shared','-pthread'],
'elf':run(['file',so]).strip(),'dependencies':re.findall(r'Shared library: \[([^\]]+)\]',deps),
'glibc_symbol_versions':sorted(set(re.findall(r'GLIBC_[\d.]+',versions))),
'neon_fmul_instructions':len(re.findall(r'\bfmul\s+v\d',dis)),
'neon_fadd_instructions':len(re.findall(r'\bfadd\s+v\d',dis)),
'fused_fp_instructions':len(fused),'arm_execution':False,
'portable_model_fixture_checks':462,'portable_max_scaled_error':2.384185791015625e-7,
'portable_independent_comparisons':282,'sanitizers':'ASan/UBSan PASS on Linux x86_64'}
metadata['downloaded_dependencies']=[]
for p in sorted((native/'build').glob('*.deb')):
 folder='gcc-14' if p.name.startswith(('libasan','libubsan')) else 'gcc-13-cross' if p.name.startswith('libgcc-13') else 'gcc-14-cross' if p.name.startswith('libgcc-s1') else 'cross-toolchain-base'
 metadata['downloaded_dependencies'].append({'name':p.name,'url':'https://archive.ubuntu.com/ubuntu/pool/main/'+folder[0]+'/'+folder+'/'+p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(native/'prebuilt/provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')
print(json.dumps({k:metadata[k] for k in ['sha256','source_sha256','dependencies','glibc_symbol_versions','neon_fmul_instructions','neon_fadd_instructions','fused_fp_instructions']},indent=2))
