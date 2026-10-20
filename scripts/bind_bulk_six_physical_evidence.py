"""Bind completed physical checks and fair latency reports to gated firmware."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('smoke','benchmark','regression','reference'):
        parser.add_argument('--'+flag,type=Path,required=True)
    args=parser.parse_args()
    report=ROOT/'reports/fused'
    evidence=read(report/'bulk_physical_firmware_evidence.json')
    evidence['parent_firmware_evidence_sha256']=sha(report/'bulk_physical_firmware_evidence.json')
    for path,digest in evidence['source_evidence_sha256'].items():
        assert sha(ROOT/path)==digest,path
    firmware=ROOT/'deployment/asr-v3-bulk/asr-v3-bulk.bit.bin'
    library=ROOT/'software/ort_fpga_bulk/libort_fpga.so'
    driver=ROOT/'deployment/experimental-bulk/qn_tile.ko'
    smoke=read(args.smoke)
    assert smoke['hardware_execution'] and smoke['library_sha256']==sha(library)
    assert len([c for c in smoke['checks'] if c.get('physical_oracle_exact')])>=6
    assert any(c.get('late_overflow_rejected_without_cpu_fallback') for c in smoke['checks'])
    assert any(c.get('fresh_load_recovers_after_error') for c in smoke['checks'])
    benchmark=read(args.benchmark)
    for path in (args.benchmark,args.regression,args.reference):
        r=read(path)
        assert r['complete'] and r['hardware_execution'] and r['runs']>=50
        for key in ('nodes','model_sha256','library_sha256','firmware_sha256','driver_sha256'):
            assert r[key]==benchmark[key],key
        assert r['firmware_sha256']==sha(firmware)
        assert r['library_sha256']==sha(library) and r['driver_sha256']==sha(driver)
        assert all(c['physical_oracle_bit_parity'] for c in r['clips'])
        for name,digest in r['sources_sha256'].items():
            assert sha(ROOT/'software/ort_fpga_bulk'/name)==digest,name
    for path in (args.benchmark,args.reference):
        assert all(c['fpga_p50']<c['cpu_p50'] and c['fpga_p95']<c['cpu_p95'] and
                   c['mean_saving_95ci_seconds'][0]>0 for c in read(path)['clips'])
    regression=read(args.regression)
    assert len(regression['clips'])>=9
    assert sum(c['fpga_errors']-c['cpu_errors'] for c in regression['clips'])/sum(c['reference_words'] for c in regression['clips'])<=.01
    evidence['speedup_scope']='Supplied recording and original reference; eight of nine available recordings have positive paired savings, with one short clip inconclusive'
    evidence.update(physical_execution=True,physical_fpga_execution_validated=True,end_to_end_cpu_speedup_validated=True,
        firmware_binary_sha256=sha(firmware),physical_smoke_sha256=sha(args.smoke),
        end_to_end_report_sha256=sha(args.benchmark),corpus_report_sha256=sha(args.regression),
        reference_report_sha256=sha(args.reference),representative_corpus_claimed=False,
        sustained_capture_validated=False)
    evidence['source_evidence_sha256'][p.relative_to(ROOT).as_posix()]=sha(p)
    evidence['source_evidence_sha256'][firmware.relative_to(ROOT).as_posix()]=sha(firmware)
    (report/'bulk_six_physical_firmware_evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('PASS: physical arithmetic/recovery, current source identity, paired CPU speedup and available accuracy')
if __name__=='__main__':
    p=Path(__file__).resolve()
    main()
