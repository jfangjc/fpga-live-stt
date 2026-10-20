"""Create an isolated retained-bank replay pipeline; preserve qualified chain RTL."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(name,text):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or path.read_text()!=text or (path.suffix=='.sh' and b'\r\n' in path.read_bytes()):
        if path.suffix=='.sh':path.write_bytes(text.encode())
        else:path.write_text(text)
source=(ROOT/'rtl/experimental/qn_chain_axis.sv').read_text()
source=source.replace('// Multi-pair sequencer', '// Two-entry read pipeline: one retained activation beat per clock.\n// Multi-pair sequencer')
source=source.replace('reg [12:0] input_index,input_beats,read_index;', '''reg [12:0] input_index,input_beats,read_index,fetch_index;
 reg [127:0] replay_head,replay_tail;
 reg [1:0] replay_count;
 reg replay_pending;
 wire replay_pop=state==SEND && replay_count!=0 && inner_ready;
 wire [2:0] replay_occupied={1'b0,replay_count}+{2'b0,replay_pending};
 wire replay_fetch=state==SEND && fetch_index<input_beats &&
   (replay_occupied<2 || (replay_pop && replay_occupied==2));''')
source=source.replace('state==RUNHEAD || state==RUNMETA || state==SEND;', 'state==RUNHEAD || state==RUNMETA || (state==SEND && replay_count!=0);')
source=source.replace('state==SEND?activation_data:s_axis_tdata;', 'state==SEND?replay_head:s_axis_tdata;')
source=source.replace('.enb(state==READ),.regceb(1\'b1),.addrb(read_index[11:0]),', '.enb(replay_fetch),.regceb(1\'b1),.addrb(fetch_index[11:0]),')
source=source.replace('active_cycles<=0;snapshot_cycles<=0;', 'fetch_index<=0;replay_count<=0;replay_pending<=0;replay_head<=0;replay_tail<=0;\n     active_cycles<=0;snapshot_cycles<=0;')
source=source.replace('     case(state)', '''     if(state==SEND)begin
       replay_pending<=replay_fetch;
       if(replay_fetch)fetch_index<=fetch_index+1;
       case({replay_pending,replay_pop})
         2'b10:begin
           if(replay_count==0)replay_head<=activation_data;else replay_tail<=activation_data;
           replay_count<=replay_count+1;
         end
         2'b01:begin replay_head<=replay_tail;replay_count<=replay_count-1;end
         2'b11:begin
           if(replay_count==1)replay_head<=activation_data;
           else begin replay_head<=replay_tail;replay_tail<=activation_data;end
         end
         default:begin end
       endcase
     end
`ifndef SYNTHESIS
     if(state==SEND && (replay_occupied>2 || (replay_pop && read_index==input_beats-1 && replay_pending)))
       $fatal(1,"Retained replay FIFO invariant failed");
`endif
     case(state)''')
source=source.replace('RUNMETA:if(inner_ready)begin read_index<=0;state<=READ;end\n       READ:state<=READWAIT;\n       READWAIT:state<=SEND;\n       SEND:if(inner_ready)begin', '''RUNMETA:if(inner_ready)begin
         read_index<=0;fetch_index<=0;replay_count<=0;replay_pending<=0;state<=SEND;
       end
       SEND:if(replay_pop)begin''')
source=source.replace('else begin read_index<=read_index+1;state<=READ;end', 'else read_index<=read_index+1;')
assert 'state<=READ;' not in source
write('rtl/experimental/qn_chain_prefetch_axis.sv',source)
for name in ('chain_sim.tcl','chain_synth.tcl','chain_implement.tcl'):
    text=(ROOT/'scripts'/name).read_text().replace('qn_chain_axis.sv','qn_chain_prefetch_axis.sv')
    text=text.replace('tb_qn_chain_prefetch_axis.sv','tb_qn_chain_axis.sv')
    text=text.replace('chain_sim','chain_prefetch_sim').replace('chain_system','chain_prefetch_system')
    text=text.replace('Prototype_v3_chain','Prototype_v3_chain_prefetch')
    text=text.replace('asr-v3-chain','asr-v3-chain-prefetch').replace('asr_v3_chain.xsa','asr_v3_chain_prefetch.xsa')
    text=text.replace('chain_synth_utilization','chain_prefetch_synth_utilization')
    write('scripts/'+name.replace('chain_','chain_prefetch_'),text)
for name in ('prepare_chain_firmware.py','finalize_chain_firmware.py','install_chain_firmware.py','run_chain_board.sh'):
    text=(ROOT/'scripts'/name).read_text().replace('qn_chain_axis.sv','qn_chain_prefetch_axis.sv')
    text=text.replace('build/chain_sim','build/chain_prefetch_sim').replace('/chain_sim.sim/','/chain_prefetch_sim.sim/')
    text=text.replace('chain_system','chain_prefetch_system').replace('Prototype_v3_chain','Prototype_v3_chain_prefetch')
    text=text.replace('asr-v3-chain','asr-v3-chain-prefetch').replace('asr_v3_chain.xsa','asr_v3_chain_prefetch.xsa')
    text=text.replace('chain_firmware_evidence','chain_prefetch_firmware_evidence')
    text=text.replace('chain_bulk_before_','chain_prefetch_bulk_before_').replace('chain_bulk_restored_','chain_prefetch_bulk_restored_')
    if name=='prepare_chain_firmware.py':
        text=text.replace('build/chain_prefetch_sim/chain_prefetch_sim.sim', 'build/chain_prefetch_vector_sim/chain_prefetch_vector_sim.sim')
        text=text.replace("native=json.loads", "stall_log=ROOT/'build/chain_prefetch_stall_sim/chain_prefetch_stall_sim.sim/sim_1/behav/xsim/simulate.log'\nassert 'PASS: prefetch replay stalls=' in stall_log.read_text()\nassert not re.search(r'Fatal:|\\$fatal|ERROR:',stall_log.read_text())\nnative=json.loads")
        text=text.replace('paths=[log,bit,', "paths=[log,stall_log,ROOT/'sim/tb_qn_chain_prefetch_stalls.sv',ROOT/'sim/tb_qn_chain_axis.sv',bit,")
        text=text.replace('for folder in (', "fixtures=json.loads((ROOT/'verification/chain-prefetch-vectors/manifest.json').read_text())\nassert fixtures['independent_reference'] and fixtures['generator_sha256']==sha(ROOT/'scripts/create_chain_vectors.py')\npaths += [ROOT/'scripts/create_chain_vectors.py',ROOT/'sim/tb_qn_chain_prefetch_vectors.sv',ROOT/'verification/chain-prefetch-vectors/manifest.json']\nfor name,value in fixtures['files_sha256'].items():\n    assert sha(ROOT/name)==value\n    paths.append(ROOT/name)\nfor folder in (")
    write('scripts/'+name.replace('chain_','chain_prefetch_'),text)
text=(ROOT/'software/latency/chain_benchmark.py').read_text()
text=text.replace('chain_firmware_evidence','chain_prefetch_firmware_evidence').replace('asr-v3-chain','asr-v3-chain-prefetch')
write('software/latency/prefetch_benchmark.py',text)
for name in ('tune_chain_policy.py','confirm_chain_latency.py','validate_chain_physical.py'):
    text=(ROOT/'software/latency'/name).read_text().replace('from chain_benchmark import','from prefetch_benchmark import')
    text=text.replace('chain_physical_validation','prefetch_physical_validation')
    write('software/latency/'+name.replace('chain_','prefetch_'),text)
print('Created isolated replay pipeline and matching build/qualification helpers')
