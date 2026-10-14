"""Save the post-trimming CPU thread audit separately from immutable snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--destination',type=Path,required=True)
    ap.add_argument('--parent',type=Path,required=True)
    a=ap.parse_args()
    assert not a.destination.exists()
    parent=json.loads((a.parent.parent/'short-package.json').read_text(encoding='utf-8'))
    assert sha(a.parent)==parent['archive_sha256']
    reports=[ROOT/'reports/fused/short_cpu_threads_nonspin30.json',ROOT/'reports/fused/short_cpu_threads_spin10_30.json']
    rows=[]
    for path in reports:
        p=json.loads(path.read_text())
        assert p['complete'] and p['runs']==30 and p['feature_padding_policy']=='trim_to_valid'
        assert p['runner_sha256']==sha(ROOT/'software/latency/short_cpu_threads_screen.py')
        for c in p['contexts']:
            assert c['cpu_bit_parity_between_thread_policies']
            assert c['fastest_p50_threads']==4, 'A faster CPU policy requires new paired FPGA validation'
            rows.append(f"| {c['context_seconds']:g} s | {p['spin_duration_us']} us | "+
                        ' | '.join(f"{c['policies'][str(t)]['p50']*1000:.2f} ms" for t in (1,2,4))+' |')
    text='''# CPU baseline audit after short-input trimming

One, two and four pinned CPU threads were independently screened after trimming zero feature padding. Each context and spin configuration has 30 randomized triples. Four threads remain fastest in every tested case, with exact logits between thread policies. This supports the worker count used in the separately preserved 100/300-pair CPU/FPGA confirmations; it is not additional FPGA speed evidence.

| Context | Worker spin | One thread p50 | Two threads p50 | Four threads p50 |
|---|---|---|---|---|
'''+ '\n'.join(rows)+'''

The zero versus 10-us spin selection was independently confirmed with 100 CPU runs in short_worker_trim_confirmation100.json. The selected FPGA profiles and their limits remain described in SHORT_INPUT_RESULTS.md. Parent snapshots are unchanged; this supplement adds only audit sources and reports.
'''
    doc=ROOT/'SHORT_INPUT_CPU_AUDIT.md';doc.write_text(text,encoding='utf-8')
    files=reports+[doc,ROOT/'software/latency/short_cpu_threads_screen.py',ROOT/'scripts/run_short_cpu_audit.sh',Path(__file__).resolve()]
    a.destination.mkdir(parents=True); archive=a.destination/'short-cpu-audit.zip'
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for rel in hashes:
            z.write(ROOT/rel,rel); target=a.destination/'project'/rel
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,target)
    with zipfile.ZipFile(archive) as z:
        for rel,digest in hashes.items():assert hashlib.sha256(z.read(rel)).hexdigest()==digest
    manifest={'archive':archive.name,'archive_sha256':sha(archive),'files':hashes,
              'parent_archive':str(a.parent),'parent_sha256':parent['archive_sha256'],
              'four_threads_remain_fastest':True}
    (a.destination/'audit-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(doc,a.destination/doc.name)
    print(json.dumps({'directory':str(a.destination),'sha256':manifest['archive_sha256']}))


if __name__=='__main__':main()
