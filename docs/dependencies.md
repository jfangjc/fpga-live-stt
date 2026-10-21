# External dependencies

The repository does not contain the Citrinet model, firmware, kernel drivers,
ONNX Runtime headers or the generated block design. They come in one pinned
archive, `fpga-ai-accelerator-dependencies-1.0.0.zip`, listed with its size,
SHA256 and file hashes in `config/dependencies.json`.

## Install

Python 3.12, no root needed:

```sh
python3 scripts/setup_dependencies.py --archive /path/to/fpga-ai-accelerator-dependencies-1.0.0.zip
python3 scripts/setup_dependencies.py --url https://HOST/fpga-ai-accelerator-dependencies-1.0.0.zip
python3 scripts/integrity.py
```

- Setup checks the archive and every file hash before writing anything.
- It rejects unsafe paths and refuses to overwrite changed files. Rerunning it
  with matching files is safe.
- Instead of `--url` you can set `FPGA_AI_DEPENDENCIES_URL` or `download_url`
  in `config/dependencies.json`. No public URL is set yet.
- `integrity.py --source-only` checks a fresh checkout without the archive.

Moonshine does not use this archive for its model. It downloads the pinned
checkpoint from Hugging Face and exports its own graphs
([moonshine.md](moonshine.md)). It does need the bulk firmware and driver.

## Citrinet model

The archive holds the INT8 graph, frontend constants and vocabulary derived
from NVIDIA `stt_en_citrinet_256_ls`, revision
`c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed`
([Hugging Face](https://huggingface.co/nvidia/stt_en_citrinet_256_ls/tree/c7cdacff0262bbb2a17771d20ec9f9f3b5cff6ed)).
The raw checkpoint alone does not produce this graph, and the scripts do not
reproduce its export or calibration.

## Publishing the archive

Host the unchanged archive over HTTPS. Set `download_url` in
`config/dependencies.json`, run `python3 scripts/write_manifest.py`, then
rerun the host checks. Do not commit the installed assets.
