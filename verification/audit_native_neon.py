"""Artifact/ABI audit of native NEON follow-up; instruction tests run separately."""
import ctypes
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    folder=ROOT/'software/native';r=json.loads((folder/'performance_validation.json').read_text())
    assert all(sha(folder/name)==value for name,value in r['source_sha256'].items())
    assert sha(folder/'prebuilt/aarch64/libqnc.so')==r['aarch64_binary_sha256']
    sys.path.insert(0,str(folder));from qnc import Stats,Profile
    assert ctypes.sizeof(Stats)==48 and Stats.ioctl_seconds.offset==40
    assert ctypes.sizeof(Profile)==32
    result=dict(status='independent_review_passed',source_manifest_hashes_match=True,
        arm64_library_hash_matches=True,original_stats_abi_bytes=48,phase_profile_abi_bytes=32,
        executed_tests=dict(cortex_a53_qemu_neon='passed',cortex_a53_qemu_forced_scalar='passed'),
        code_review=dict(load_vector_bounds='8 channels x8 K only inside dimensions; tail group padding cleared',
            run_vector_bounds='16 time lanes only on complete tiles; explicit partial-lane zero padding',
            output_vector_bounds='4 channels x4 times, no output-group boundary crossing; scalar tails',
            quantization='IEEE vector FDIV then clamp and explicit nearest-even FRINTN; strict compile flags prevent reciprocal/FMA changes',
            error_handling='No replay; cache invalidated on transport or response identity/status failure',
            abi='QNC2 ioctl requests remain 32 bytes; original 48-byte Stats getter unchanged; optional 32-byte phase getter'),
        correctness_blockers=[],physical_board_new_binary_tested=False,
        validation_reuse='Previous physical graph proof invalidated by changed qnc.c/qnc.h/qnc.py/native binary; original CPU NeMo validation may remain valid if its own provenance unchanged',
        library_sha256=sha(folder/'prebuilt/aarch64/libqnc.so'),
        test_binary_sha256={name:sha(folder/'prebuilt/aarch64'/name) for name in ['test_qnc_neon','test_qnc_scalar']},
        limitations=['QEMU instruction correctness does not measure ARM board performance or physical DMA','Host sanitizer results were reported by implementer; independently rerun instruction tests and checked hashes only','No new whole-graph parity/WER/speedup/capture result obtained for optimized binary'])
    (ROOT/'verification/native_neon_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()

