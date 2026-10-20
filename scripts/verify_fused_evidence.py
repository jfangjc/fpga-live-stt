"""Verify experimental artifacts without promoting them to physical acceptance."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT/'reports/fused'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = set()
    primitives = {}
    for prefix, rtl, tb, vector_dir, success in (
        ('requant','fused_requant.v','tb_fused_requant.sv','fused_vectors',
         'PASS: 1024 four-lane requant vectors'),
        ('se','fused_se_reduce.v','tb_fused_se_reduce.sv','se_vectors',
         'PASS: SE reduction packets')):
        log = REPORTS/(prefix+'_sim.log')
        assert success in log.read_text(), f'{prefix} simulation failed'
        result_path = REPORTS/(prefix+'_implementation.json')
        result = json.loads(result_path.read_text())
        assert result['clock_hz'] == 100000000
        assert result['setup_slack_ns'] >= 0 and result['hold_slack_ns'] >= 0
        assert result['physical_hardware_execution'] is False
        drc = REPORTS/(prefix+'_drc.rpt')
        # The heading also appears in the table of contents before the summary.
        summary = drc.read_text().rsplit('2. REPORT DETAILS',1)[0]
        assert not re.search(r'\|\s*(Error|Critical Warning)\s*\|', summary)
        result['drc_warning_rows'] = re.findall(r'^\|.*Warning.*\|$',summary,re.M)
        primitives[prefix] = result
        files.update([ROOT/'rtl/experimental'/rtl,ROOT/'sim'/tb,log,result_path,drc,
                      REPORTS/(prefix+'_timing.rpt'),REPORTS/(prefix+'_utilization.rpt'),
                      ROOT/'scripts'/('fused_'+prefix+'_sim.tcl'),
                      ROOT/'scripts'/('fused_'+prefix+'_impl.tcl'),
                      ROOT/'scripts'/('generate_'+('requant' if prefix=='requant' else 'se')+'_vectors.py')])
        vector_path = ROOT/'sim'/vector_dir
        provenance = json.loads((vector_path/'provenance.json').read_text())
        for name in ('input.mem','expected.mem'):
            expected = (provenance['sha256'][(vector_path/name).relative_to(ROOT).as_posix()]
                        if prefix == 'requant' else provenance[name+'_sha256'])
            assert sha(vector_path/name) == expected
        source_hashes = provenance.get('sources_sha256',provenance.get('sha256',{}))
        for name, expected in source_hashes.items():
            assert sha(ROOT/name) == expected, f'{prefix}: changed fixture source: {name}'
        files.update(p for p in vector_path.iterdir() if p.is_file())

    board_reports = ['board-int8-4-paired.json','board-user-int8-4-paired.json',
                     'board-stress-ac-int8-4-paired.json']
    cpu_summary = {}
    for name in board_reports:
        path = REPORTS/name
        report = json.loads(path.read_text())
        assert report['repeats'] == 20 and report['warmups'] == 3
        assert report['candidate_int8_conv_kernels_present'] is True
        assert report['candidate_artifact_sha256'] == sha(ROOT/'research/fused/cpu-int8.onnx')
        for source, expected in report['sources_sha256'].items():
            source_path = ROOT/'software/fused'/source
            assert sha(source_path) == expected, f'{name}: source changed: {source}'
            files.add(source_path)
        cpu_summary[name] = report['summary']
        files.add(path)
    for name in ('integer-regression.json','user-integer-regression.json',
                 'user-stress-integer.json','user-stress-mixed0.json',
                 'user-stress-ac-integer.json'):
        path = REPORTS/name
        report = json.loads(path.read_text())
        assert report['final_accuracy_gate_claimed'] is False
        assert report['rtl_expansion_approved'] is False
        assert report['sources_sha256']['oracle.py'] == sha(ROOT/'software/fused/oracle.py')
        files.add(path)
    files.add(ROOT/'research/fused/cpu-int8.onnx')
    files.add(ROOT/'research/fused/cpu-int8.json')
    launcher = REPORTS/'user-int8-launcher-smoke.json'
    smoke = json.loads(launcher.read_text())
    user = json.loads((REPORTS/'board-user-int8-4-paired.json').read_text())
    assert smoke['recordings'][0]['text'] == user['clips'][0]['candidate_text']
    assert smoke['candidate_sha256'] == user['candidate_artifact_sha256']
    files.add(launcher)
    files.add(ROOT/'software/fused/transcribe_cpu_int8.py')
    result = {'primitives':primitives,'board_cpu_results':cpu_summary,
              'physical_fpga_acceleration_demonstrated':False,
              'representative_accuracy_gate_passed':False,
              'full_fused_block_implemented':False,
              'firmware_changed':False,
              'files_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}}
    (REPORTS/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: source/vector/report identities and standalone primitive timing; acceptance flags remain false')


if __name__ == '__main__':
    main()
