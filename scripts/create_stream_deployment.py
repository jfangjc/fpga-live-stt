"""Activate the separate stream app only through complete artifact gates."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for name in ('finalize_chain_firmware.py','install_chain_firmware.py','run_chain_board.sh'):
    text=(ROOT/'scripts'/name).read_text()
    text=text.replace('chain_firmware_evidence','stream_firmware_evidence').replace('chain_system','stream_system').replace('Prototype_v3_chain','Prototype_v3_stream')
    text=text.replace('asr-v3-chain','asr-v3-stream').replace('asr_v3_chain','asr_v3_stream')
    text=text.replace('software/ort_fpga_chain','software/ort_fpga_stream_exact').replace('deployment/experimental-chain','deployment/experimental-stream')
    text=text.replace('short_chain_protocol','stream_chain_protocol').replace('chain_bulk_before_','stream_bulk_before_').replace('chain_bulk_restored_','stream_bulk_restored_')
    (ROOT/'scripts'/name.replace('chain_','stream_')).write_bytes(text.encode())
print('Created separate stream activation, conversion and compatible bulk rollback')
