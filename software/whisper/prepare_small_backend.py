"""Build the 12-head hook separately and assemble a pinned hybrid runtime."""
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    work = Path(sys.argv[1]).resolve()
    original = Path('/home/ubuntu/whisper-turbo-kv260')
    source = work/'upstream-kv260'
    build = work/'build-small-ggml'
    project = work/'source'
    if source.exists() or build.exists():
        raise RuntimeError('Use fresh backend build paths')
    shutil.copytree(original/'upstream-kv260', source, symlinks=True)
    subprocess.run([sys.executable, project/'software/whisper/patch_upstream.py', source,
                    '--project', project], check=True)
    cmake = work/'.venv/bin/cmake'
    subprocess.run([cmake, '-S', source, '-B', build, '-DCMAKE_BUILD_TYPE=Release',
                    '-DGGML_NATIVE=OFF', '-DGGML_CPU_ARM_ARCH=armv8-a', '-DGGML_OPENMP=OFF',
                    '-DWHISPER_BUILD_TESTS=OFF', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'], check=True)
    subprocess.run([cmake, '--build', build, '--target', 'ggml-cpu', '-j', '3'], check=True)
    runtime = work/'build-hybrid'
    if not runtime.is_symlink() or runtime.resolve() != (original/'build-hybrid').resolve():
        raise RuntimeError('Expected only the original runtime symlink to replace')
    runtime.unlink()  # remove this experiment's link; original directory is unchanged
    (runtime/'bin').mkdir(parents=True)
    shutil.copy2(original/'build-hybrid/bin/whisper-cli', runtime/'bin/whisper-cli')
    for directory in ('src', 'ggml/src', 'ggml/src/ggml-cpu'):
        for path in (original/'build-hybrid'/directory).glob('*.so*'):
            target = runtime/directory/path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path.resolve(), target)
    for path in build.rglob('libggml-cpu.so*'):
        if path.is_file():
            target = runtime/path.relative_to(build)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path.resolve(), target)
    print('Assembled separate 12-head hybrid runtime', flush=True)


if __name__ == '__main__':
    main()
