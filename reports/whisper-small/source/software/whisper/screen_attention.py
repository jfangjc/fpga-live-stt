"""Screen CPU fused attention against a completed matching unfused CLI run.

A censored fused trial only excludes a slower candidate. It never supplies a
completed-transcription timing to the repeated performance qualification.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from benchmark import dependencies, runtime_environment, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu', required=True, type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--audio', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.out.with_suffix('.log').exists():
        parser.error('Refusing to overwrite screening evidence')
    reference = json.loads(args.reference.read_text())
    if reference['mode']!='cpu' or reference['physical'] or reference['flash_attention'] or reference['language']!='en':
        raise ValueError('Expected an explicit-English unfused CPU reference')
    expected = {str(Path(path).resolve()):digest for path,digest in reference['sha256'].items()}
    if any(sha(path)!=expected[str(path.resolve())] for path in (args.cpu,args.model,args.audio)):
        raise ValueError('Screening inputs differ from the reference')
    libraries = dependencies(args.cpu)
    if libraries!=reference['dynamic_libraries']:
        raise ValueError('CPU libraries changed')
    command = [str(args.cpu.resolve()),'-m',str(args.model.resolve()),'-f',str(args.audio.resolve()),
               '-t','4','-l','en','-nt','-ng','-nf','-bs','1','-bo','1','-fa']
    environment = dict(runtime_environment(args.cpu),WHISPER_KV260='0',WHISPER_KV260_ATTENTION='0',WHISPER_KV260_DECODE='0')
    deadline = reference['seconds']*1.1
    started = time.perf_counter()
    try:
        process = subprocess.run(command,env=environment,capture_output=True,text=True,timeout=deadline)
        elapsed = time.perf_counter()-started
        stderr,stdout = process.stderr,process.stdout
        completed = process.returncode==0
        if not completed:
            raise RuntimeError(f'Fused CPU candidate failed: {stderr}')
    except subprocess.TimeoutExpired as failure:
        elapsed = time.perf_counter()-started
        def decode(value):
            return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else (value or '')
        stderr,stdout = decode(failure.stderr),decode(failure.stdout)
        completed = False
    args.out.with_suffix('.log').write_text(stderr+'\nSTDOUT\n'+stdout)
    result = {'model':reference['model'],'unfused_seconds':reference['seconds'],
              'fused_completed':completed,'fused_seconds':elapsed if completed else None,
              'fused_censored_lower_bound_seconds':None if completed else deadline,
              'selected':'fused' if completed and elapsed<reference['seconds'] else 'unfused',
              'scope':'CPU attention candidate screening only; timeout is not a completed-transcription timing',
              'reference_sha256':sha(args.reference),'dynamic_libraries':libraries,
              'command':command,'text':stdout.strip() if completed else None}
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
