"""Separate Vivado project and mandatory exact arithmetic gate."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
text=(ROOT/'scripts/chain_synth.tcl').read_text()
text=text.replace('chain_system','stream_system').replace('Prototype_v3_chain','Prototype_v3_stream')
text=text.replace('qn_chain_axis.sv qn_chain_inner.sv qn_short_cache_core.v fused_depthwise_channel_wide.sv fused_affine_quant.v',
                  'qn_stream_axis.sv qn_stream_inner.sv qn_stream_pw_core.v fused_depthwise_stream.sv fused_affine_quant_exact.sv')
text=text.replace('chain_synth_utilization','stream_synth_utilization')
text=text.replace('set target ', '''set python C:/Users/jfang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
exec $python -I $root/scripts/check_stream_software.py
set target ''')
(ROOT/'scripts/stream_synth.tcl').write_bytes(text.encode())
text=(ROOT/'scripts/chain_implement.tcl').read_text().replace('chain_system','stream_system').replace('Prototype_v3_chain','Prototype_v3_stream')
text=text.replace('asr-v3-chain','asr-v3-stream').replace('asr_v3_chain.xsa','asr_v3_stream.xsa')
(ROOT/'scripts/stream_implement.tcl').write_bytes(text.encode())
print('Created isolated streamed block synthesis/routing helpers')
