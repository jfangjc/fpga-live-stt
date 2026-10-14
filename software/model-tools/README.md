# Citrinet model tools

The checkpoint is `nvidia/stt_en_citrinet_256_ls` at revision
`c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed`, with archive SHA256 `a00c8fb7…aa21c`.

**Tokenizer:** WordPiece (`tokenizer.type=wpe`) with 256 tokens and CTC blank
index 256. The model card says SentencePiece, but the archive has no
SentencePiece model.

**Frontend:**
- 400-sample Hann window, 512-point FFT and 160-sample hop.
- 80 mel bins, with 0.97 preemphasis and a 2^-24 log guard.
- Per-feature normalization, then padding to a multiple of 16 frames.

**Lengths:** there are `floor(samples/160)+1` valid frames, and the encoder
outputs `ceil(frames/8)` frames.

| Script | Purpose |
|---|---|
| `acquire_citrinet.py` | Downloads and hash-checks the checkpoint |
| `export_citrinet.py` | Exports ONNX using the pinned NeMo Jasper source, with strict state loading |
| `inspect_citrinet.py` | Records the graph census and tensor hashes |
| `validate_nemo.py` | Compares the export with the complete original NeMo 1.23 model on real audio: frontend, lengths, logits and text |
| `citrinet_cpu.py` | Resident CPU benchmark |
| `acquire_librispeech.py` | Downloads the five-clip calibration and evaluation sets |
| `export_larger_citrinet.py`, `quantize_larger_citrinet.py` | Citrinet-512 and Citrinet-1024 export and INT8 quantization |

On the board:

```sh
python3 -m venv software/.venv-cpu
software/.venv-cpu/bin/python -m pip install -r software/model-tools/requirements-cpu.txt
software/.venv-cpu/bin/python software/model-tools/acquire_citrinet.py --output-dir research/checkpoints/citrinet-256-ls
```

NeMo validation needs Python 3.10 on a Linux host, with the pins in
`constraints-nemo-linux.txt`.
- Use Transformers 4.30.2. Version 4.38 overwrote two token IDs in the custom
  vocabulary and garbled the decoded text.
- NeMo 1.23 does not install on Windows because Triton has no Windows build.

The LibriSpeech clips are CC-BY-4.0 ([OpenSLR 12](https://www.openslr.org/12/)).
