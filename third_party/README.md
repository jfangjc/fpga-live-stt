# Third-party notices

License texts are in `licenses/`.

| Component | Owner | License | Text |
|---|---|---|---|
| Citrinet INT8 graph, frontend constants and vocabulary, derived from [nvidia/stt_en_citrinet_256_ls](https://huggingface.co/nvidia/stt_en_citrinet_256_ls) at `c7cdacff` | NVIDIA | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | `licenses/CC-BY-4.0.txt` |
| ONNX Runtime C API headers, copied into `software/*/include/` before a native build | Microsoft | MIT | `licenses/ONNX-Runtime-MIT.txt` |
| `qn_tile` drivers in `drivers/bulk` and `drivers/branch` | This project | GPL-2.0 (`SPDX-License-Identifier: GPL-2.0`) | `licenses/GPL-2.0.txt` |

- **Citrinet changes:** the project exported the Citrinet checkpoint to ONNX,
  quantized it to INT8, simplified the graph and added FPGA block transforms.
  NVIDIA does not endorse the modified model.
- **Moonshine models:** downloaded from Hugging Face at run time, under the
  terms on their model cards.
- **Python packages:** installed by pip and keep their own notices.
- **Vivado and vendor IP:** not included. Regenerating the vendor IP needs an
  AMD tool installation under its own terms.
