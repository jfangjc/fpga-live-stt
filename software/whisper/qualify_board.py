"""Run turbo accuracy, repeated timing, packaging and relocated deployment checks."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
from benchmark import dependencies, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--release', required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Run as root; each hardware phase restores the starter application')
    work = args.work.resolve()
    project = Path(__file__).resolve().parents[2]
    harness = project/'software/whisper'
    state_path = work/'pipeline_state.json'
    if state_path.exists():
        parser.error('Use new evidence paths; a pipeline state already exists')
    state = {'pid':os.getpid(),'status':'running','phase':'preflight'}
    def phase(name, total=None):
        state.update(phase=name,phase_started=datetime.now(timezone.utc).isoformat(),total_runs=total)
        state_path.write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps(state),flush=True)
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Pipeline interrupted by signal {signum}')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    def execute(command, log=None):
        stream = log.open('w') if log else None
        try:
            child = subprocess.Popen(list(map(str,command)),cwd=work,stdout=stream,stderr=subprocess.STDOUT if stream else None)
            try:
                code = child.wait()
            except BaseException:
                child.terminate()
                # A hardware-session child gets time to terminate its own group
                # and restore the original app. Do not SIGKILL that supervisor.
                child.wait(timeout=90)
                raise
            if code:
                raise RuntimeError(f'Phase {state["phase"]} exited {code}; inspect {log}')
        finally:
            if stream:
                stream.close()
    def session(evidence, command, log):
        execute([sys.executable,harness/'hardware_session.py','--release',args.release.resolve(),
                 '--expected-app','k26-starter-kits','--evidence',evidence,'--',*command],work/log)
    model = 'models/ggml-large-v3-turbo-q8_0.bin'
    common = [sys.executable,harness/'benchmark.py','--cpu','build-cpu/bin/whisper-cli',
              '--hybrid','build-hybrid/bin/whisper-cli','--model',model,'--fpga-attention','--cpu-unfused-only']
    try:
        phase('preflight')
        for local,packaged in (('validation-ten','whisper-validation'),('latency-three','whisper-latency')):
            if not (work/local).exists():
                shutil.copytree(project/'research'/packaged,work/local)
        if not (work/'parallel_conformance.json').exists():
            phase('physical_arithmetic')
            execute(['gcc','-O3','-mcpu=cortex-a53','-fno-fast-math','-ffp-contract=off','-fPIC','-shared',
                     'upstream-kv260/ggml/src/ggml-cpu/qnc_transport.c','-lm','-o','libqnc_parallel.so'])
            session('parallel_session.json',[work/'.venv/bin/python',harness/'test_physical_matrix.py',
                     '--library','libqnc_parallel.so','--ggml','--out','parallel_conformance.json'],'parallel_progress.log')
        sample = work/'latency-three/audio/6930-75918-0000.wav'
        if not (work/'cpu-q8-smoke.json').exists():
            phase('cpu_attention_reference')
            execute(['/usr/bin/time','-v','-o','cpu-q8-smoke.time.txt',sys.executable,harness/'transcribe.py',
                     sample,'--binary','build-cpu/bin/whisper-cli','--model',model,'--language','en',
                     '--mode','cpu','--out','cpu-q8-smoke.json'],work/'cpu-q8-smoke-progress.log')
        if not (work/'attention_screen.json').exists():
            phase('cpu_attention_screen')
            execute([sys.executable,harness/'screen_attention.py','--cpu','build-cpu/bin/whisper-cli',
                     '--model',model,'--audio',sample,'--reference','cpu-q8-smoke.json',
                     '--out','attention_screen.json'],work/'attention-screen-progress.log')
        screen = json.loads((work/'attention_screen.json').read_text())
        if screen['reference_sha256']!=sha(work/'cpu-q8-smoke.json') or screen['dynamic_libraries']!=dependencies(work/'build-cpu/bin/whisper-cli'):
            raise RuntimeError('CPU candidate-screen evidence is stale')
        if screen['selected']!='unfused':
            raise RuntimeError('Adapt comparison to the faster fused CPU mode before qualification')
        if not (work/'hybrid-parallel-weight.json').exists():
            phase('hybrid_functional')
            session('parallel_weight_session.json',['/usr/bin/time','-v','-o','hybrid-parallel-weight.time.txt',
                     sys.executable,harness/'transcribe.py',sample,'--binary','build-hybrid/bin/whisper-cli',
                     '--model',model,'--language','en','--fpga-attention','--out','hybrid-parallel-weight.json'],
                     'hybrid-parallel-weight-progress.log')
        after = json.loads((work/'hybrid-parallel-weight.json').read_text())
        if not after['physical'] or after['dynamic_libraries']!=dependencies(work/'build-hybrid/bin/whisper-cli'):
            raise RuntimeError('Hybrid functional evidence is stale or nonphysical')
        if (work/'hybrid-smoke.json').exists():
            before = json.loads((work/'hybrid-smoke.json').read_text())
            if before['text']!=after['text']:
                raise RuntimeError('Parallel weight preparation changed the smoke transcript')
        phase('cache_reuse_smoke',1)
        session('auto_smoke_session.json',[sys.executable,harness/'transcribe.py',
                work/'validation-ten/audio/3570-5694-0013.wav','--binary','build-hybrid/bin/whisper-cli',
                '--model',model,'--language','auto','--fpga-attention','--out','auto-smoke.json'],'auto_progress.log')
        phase('accuracy',20)
        session('validation_session.json',[*common,'--cpu-model','models/ggml-large-v3-turbo.bin',
                '--manifest','validation-ten/evaluation.jsonl','--repeats','1','--warmup','0',
                '--out','validation_results'],'validation_progress.jsonl')
        phase('accuracy_scoring')
        execute([sys.executable,harness/'evaluate_report.py','validation_results/results.json',
                 '--manifest','validation-ten/evaluation.jsonl','--out','validation_wer.json'])
        totals = json.loads((work/'validation_wer.json').read_text())['totals']
        accuracy = json.loads((work/'validation_results/results.json').read_text())
        automatic = json.loads((work/'auto-smoke.json').read_text())
        explicit = next(row for row in accuracy['clips'] if Path(row['audio']).name=='3570-5694-0013.wav')['rows']['hybrid'][0]
        if automatic['text']!=explicit['text']:
            raise RuntimeError('Automatic-language/cache-reuse transcript differs from explicit English')
        if totals['hybrid']['wer']-totals['cpu_0_no_flash']['wer']>0.01:
            raise RuntimeError('Accuracy gate failed; preserve evidence and fix before timing qualification')
        phase('latency',36)
        session('latency_session.json',[*common,'--cpu-model','models/ggml-large-v3-turbo.bin',
                '--cpu-model',model,'--cpu-model','models/ggml-large-v3-turbo-q5_0.bin',
                '--manifest','latency-three/evaluation.jsonl','--repeats','3','--warmup','0',
                '--out','latency_results'],'latency_progress.jsonl')
        phase('qualification')
        execute([sys.executable,harness/'evaluate_report.py','latency_results/results.json',
                 '--manifest','latency-three/evaluation.jsonl','--out','latency_wer.json'])
        execute([sys.executable,harness/'qualify.py','--work',work,'--out','qualification.json'])
        execute([sys.executable,project/'scripts/summarize_whisper.py','--work',work,
                 '--out',project/'docs/WHISPER_TURBO_RESULTS.md'])
        phase('packaging')
        archive = work/'kv260-whisper-large-v3-turbo-prototype-0.2.0-runtime.zip'
        execute([sys.executable,project/'scripts/package_whisper.py','--work',work,'--project',project,
                 '--release',args.release.resolve(),'--out',archive])
        phase('relocated_deployment')
        relocated = work.parent/'whisper-turbo-runtime-check-v020'
        if relocated.exists():
            raise RuntimeError('Relocation destination already exists')
        execute(['unzip','-q',archive,'-d',relocated])
        execute([sys.executable,relocated/'scripts/verify_whisper_deployment.py','--root',relocated,
                 '--out',work/'runtime_check.json'])
        state['status'] = 'complete'
        state['archive'] = str(archive)
        phase('complete')
    except BaseException as failure:
        state.update(status='failed',error=str(failure))
        phase('failed')
        raise


if __name__ == '__main__':
    main()
