"""Exercise reset while either new stream buffer or quantizer buffer is full."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def expand_reset(text):
    if 'task interrupt_slice' not in text:
        start=text.index(' initial begin\n')
        task=''' task interrupt_slice(input reg branch);
      reg [127:0] held;reg held_last;
      begin
       force dut.engine.slice_ready=1'b0;
       fork : interrupted_slice
        begin
         if(branch)residual_case(13,7,3,11);else stream_case(17,13,2,11);
         $fatal(1,"Transaction completed despite blocked stream register");
        end
        begin
         wait(dut.engine.slice_valid);@(negedge clk);
         held=dut.engine.slice_data;held_last=dut.engine.slice_last;
         repeat(5)begin
          @(negedge clk);
          if(!dut.engine.slice_valid || dut.engine.slice_data!==held || dut.engine.slice_last!==held_last)
           $fatal(1,"Stream register changed under backpressure");
         end
         checking=0;rstn=0;valid=0;last=0;disable interrupted_slice;
        end
       join
       repeat(3)@(negedge clk);
       if(dut.engine.slice_valid)$fatal(1,"Stream input survived reset");
       release dut.engine.slice_ready;
       rstn=1;force_stall=0;repeat(5)@(negedge clk);
       if(out_valid || busy || error)$fatal(1,"Stale stream response after reset");
      end
     endtask
    '''
        task=(task.splitlines()[0]+'\n'+'\n'.join(line[4:] for line in task.splitlines()[1:])).rstrip()+'\n'
        text=text[:start]+task+text[start:]
        text=text.replace('  interrupt_quantizer(1);','  interrupt_slice(1);\n  residual_case(13,7,3,11);\n  interrupt_slice(0);\n  stream_case(17,13,2,11);\n  interrupt_quantizer(1);')
        text=text.replace('PASS: 2 full-pipeline reset/replay cases','PASS: 4 full-pipeline reset/replay cases')
    return text

if __name__=='__main__':
    p=ROOT/'sim/tb_qn_branch512_slice_reset.sv'
    p.write_text(expand_reset(p.read_text()))
    sim=ROOT/'scripts/branch512_slice_reset_sim.tcl'
    sim.write_text(sim.read_text().replace('PASS: 2 full-pipeline reset/replay cases','PASS: 4 full-pipeline reset/replay cases'))
    print('Prepared four stalled stream/quantizer reset and exact replay cases')
