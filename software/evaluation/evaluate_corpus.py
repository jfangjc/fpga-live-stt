"""Paired corpus WER diagnostic; a small read-speech subset is not the final gate."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from citrinet_adapter import Runner,digest
from benchmark import errors

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--mode',choices=['emulate','fpga'],default='emulate');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--threads',type=int,default=4);args=p.parse_args()
    records=[json.loads(line) for line in args.manifest.read_text().splitlines() if line.strip()]
    if not records: raise ValueError('Empty corpus')
    cpu=Runner('cpu',args.threads);hybrid=Runner(args.mode,args.threads)
    rows=[];ids=set()
    try:
        for record in records:
            if record['id'] in ids: raise ValueError('Duplicate clip ID')
            ids.add(record['id'])
            role=record.get('split',record.get('role'))
            if role not in ('evaluation','test'): raise ValueError('Evaluation/test role required; calibration excluded')
            path=args.manifest.parent/record['audio'];reference=record.get('reference',record.get('text'))
            a=cpu.transcribe(path);b=hybrid.transcribe(path)
            ea,n=errors(reference,a['transcript']);eb,n2=errors(reference,b['transcript'])
            if n==0 or n2!=n: raise ValueError('Empty reference')
            rows.append({'id':record['id'],'reference':reference,'reference_words':n,
                'audio_sha256':digest(path),'cpu_text':a['transcript'],'hybrid_text':b['transcript'],
                'cpu_word_errors':ea,'hybrid_word_errors':eb,
                'category':record.get('category',record.get('categories'))})
        count=sum(row['reference_words'] for row in rows)
        cpu_wer=sum(row['cpu_word_errors'] for row in rows)/count
        hybrid_wer=sum(row['hybrid_word_errors'] for row in rows)/count
        report={'mode':args.mode,'hardware_execution':args.mode=='fpga','corpus_sha256':digest(args.manifest),
            'cpu_metadata':cpu.metadata(),'hybrid_metadata':hybrid.metadata(),'n_utterances':len(rows),'reference_words':count,
            'cpu_wer':cpu_wer,'hybrid_wer':hybrid_wer,'absolute_wer_degradation':hybrid_wer-cpu_wer,'clips':rows,
            'final_accuracy_gate_claimed':False,
            'limits':['Corpus size and category coverage must be audited','CPU emulation does not establish physical output parity','Complete speed/capture/WER gates use benchmark.py and independent evaluate_gates.py']}
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('clips','cpu_metadata','hybrid_metadata')},indent=2))
    finally: cpu.close();hybrid.close()

if __name__=='__main__': main()
