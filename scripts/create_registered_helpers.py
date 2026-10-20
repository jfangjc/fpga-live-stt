"""Bootstrap isolated DMA program-cache experiments; preserve measured variants."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(name,text):
    path=ROOT/name
    if path.exists():assert path.read_text()==text,str(path)
    else:path.write_bytes(text.encode())
for source,target in (('validate_exact_stream_oracle.py','validate_registered_oracle.py'),
                      ('test_stream_transport.py','test_registered_transport.py')):
    text=(ROOT/'software/latency'/source).read_text().replace('ort_fpga_stream_exact','ort_fpga_stream_registered')
    text=text.replace('prototype.fpga.stream.exact','prototype.fpga.stream.registered')
    text=text.replace('physical_backend_implemented\':False','physical_backend_implemented\':True')
    text=text.replace('stream_mock_transport','registered_mock_transport')
    write('software/latency/'+target,text)
text=(ROOT/'software/latency/stream_benchmark.py').read_text()
text=text.replace('ort_fpga_stream_exact','ort_fpga_stream_registered').replace('experimental-stream/','experimental-stream-registered/')
text=text.replace('stream_firmware_evidence.json','registered_transport_evidence.json')
text=text.replace('/parameters/stream_chain_protocol','/parameters/registered_stream_protocol')
text=text.replace("'maximum_feature_frames':256}","'maximum_feature_frames':256,'kernel_program_cache':True}")
write('software/latency/registered_benchmark.py',text)
for source,target in (('validate_stream_physical.py','validate_registered_physical.py'),
                      ('tune_stream_policy.py','tune_registered_policy.py'),
                      ('confirm_stream_latency.py','confirm_registered_latency.py')):
    text=(ROOT/'software/latency'/source).read_text().replace('from stream_benchmark import','from registered_benchmark import')
    if 'tune' in target:
        text=text.replace("(3,10,'extended',0),(3,10,'extended',3),(4,10,'all',0),(4,0,'all',3))]",
                          "(3,10,'extended',0),(3,10,'extended',3),(4,10,'all',0),(4,0,'all',3),\n                               (1,0,'extended',3),(2,10,'extended',3),(2,0,'all',3),\n                               (4,500,'extended',3),(4,1000,'extended',3))]")
    if 'validate' in target:
        # First inference registers 23 prefixes; the following warm inference
        # must transfer/load the same weights with only 23 run ioctls.
        text=text.replace("physical,actual=timer.call(runners['fpga'],clip,'fpga')",
                          "timer.call(runners['fpga'],clip,'fpga')\n            physical,actual=timer.call(runners['fpga'],clip,'fpga')")
    write('software/latency/'+target,text)
text=(ROOT/'scripts/run_stream_board.sh').read_text()
text=text.replace('stream_bulk_','registered_bulk_').replace('stream_firmware_evidence.json','registered_transport_evidence.json')
text=text.replace('ort_fpga_stream_exact','ort_fpga_stream_registered').replace('experimental-stream/','experimental-stream-registered/')
text=text.replace('/parameters/stream_chain_protocol','/parameters/registered_stream_protocol')
write('scripts/run_registered_board.sh',text)
print('Prepared isolated program-cache helpers')
