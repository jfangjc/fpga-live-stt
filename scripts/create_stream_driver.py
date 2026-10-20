"""Separate driver: a complete op17 program is validated before DMA starts."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];dest=ROOT/'deployment/experimental-stream';dest.mkdir(parents=True,exist_ok=True)
for name in ('qn_tile.c','qn_tile_uapi.h','qn_layer_protocol.h','Makefile'):
    shutil.copyfile(ROOT/'deployment/experimental-chain'/name,dest/name)
source=(dest/'qn_tile.c').read_text()
source=source.replace('else if(layer_op!=12 &&', 'else if(layer_op!=17 && layer_op!=12 &&')
source=source.replace('static unsigned int short_chain_protocol = 1;', 'static unsigned int stream_chain_protocol = 1;\nmodule_param(stream_chain_protocol, uint, 0444);\nstatic unsigned int short_chain_protocol = 0;')
(dest/'qn_tile.c').write_bytes(source.encode())
