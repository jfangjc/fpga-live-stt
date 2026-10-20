#!/bin/sh
# Run as ubuntu on KV260, with this project (or the overlay) as argument.
set -eu
project=$(realpath "${1:?Project source root required}")
work=$(realpath "${2:-.}")
cd "$work"
python3 -m venv .venv
.venv/bin/pip install cmake numpy soundfile
model=${3:-large-v3-turbo}
case "$model" in
    base) source_sha1=465707469ff3a37a2b9b8d8f89f2f99de7299dac ;;
    small) source_sha1=55356645c2b361a969dfd0ef2c5a50d530afd8d5 ;;
    large-v3-turbo) source_sha1=4af2b29d7ec73d781377bfd1758ca957a807e941 ;;
    *) echo "Supported models: base, small, large-v3-turbo" >&2; exit 1 ;;
esac
pin=2eeeba56e9edd762b4b38467bab96c2517163158
if ! test -d upstream; then
    git clone --depth 1 --branch v1.8.3 https://github.com/ggml-org/whisper.cpp.git upstream
fi
test "$(git -C upstream rev-parse HEAD)" = "$pin"
test -z "$(git -C upstream status --porcelain --untracked-files=no)"
if ! test -d upstream-kv260; then cp -a upstream upstream-kv260; fi
python3 "$project/software/whisper/patch_upstream.py" upstream-kv260 --project "$project"
for variant in cpu hybrid; do
    source=upstream
    if test "$variant" = hybrid; then source=upstream-kv260; fi
    .venv/bin/cmake -S "$source" -B "build-$variant" -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8-a -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF
    .venv/bin/cmake --build "build-$variant" --target whisper-cli whisper-quantize -j 3
done
mkdir -p models
if ! test -f "models/ggml-$model.bin"; then
    curl -L --fail --retry 3 -o "models/ggml-$model.bin.partial" \
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin"
    echo "$source_sha1  models/ggml-$model.bin.partial" | sha1sum -c -
    mv "models/ggml-$model.bin.partial" "models/ggml-$model.bin"
fi
echo "$source_sha1  models/ggml-$model.bin" | sha1sum -c -
build-cpu/bin/whisper-quantize "models/ggml-$model.bin" "models/ggml-$model-q8_0.bin" q8_0
build-cpu/bin/whisper-quantize "models/ggml-$model.bin" "models/ggml-$model-q5_0.bin" q5_0
python3 "$project/software/whisper/write_model_manifest.py" --work "$work" --model "$model" --out model_manifest.json
