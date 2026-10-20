// Two-entry read pipeline: one retained activation beat per clock.
// Multi-pair sequencer over the verified 32-slot shortwide engine.
// Op 15: header, {count[23:16],valid_t[12:0]}, N descriptors,
// (N-1)*256 LUT bytes, padded channel-major input. One final response.
// Descriptor: slot[4:0], masked byte[15:8], tag[63:32]; other bits zero.
// A single activation bank is safe: the inner engine consumes the entire
// input before producing pointwise output. Partial output tiles transpose
// through 16 registers before overwriting this bank.
module qn_cached_axis #(parameter MAX_K=256,parameter MAX_M=256)(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn" *)
 (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK" *) input wire aclk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
 (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST" *) input wire aresetn,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [127:0] s_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_axis_tlast,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [127:0] m_axis_tdata,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_axis_tvalid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_axis_tready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_axis_tlast,
 output wire busy,output reg done,output wire error
);
 localparam IDLE=0,PASS=1,META=2,DESC=3,LUTIN=4,INPUTS=5,LUTREAD=6,
   LUTWAIT=7,LUTCOPY=8,RUNHEAD=9,RUNMETA=10,READ=11,READWAIT=12,
   SEND=13,ACK=14,OUTPUTS=15,WRITE=16,COUNTER=17,FOOTER=18,DRAIN=19,BADACK=20;
 reg [4:0] state;
 reg [8:0] times,valid_times;
 reg [4:0] tiles;
 reg [5:0] count,step,desc_index;
 reg [8:0] lut_beats,lut_index;
 reg [3:0] lut_lane,row,group_index,time_row;
 reg [4:0] tile_index;
 reg [12:0] input_index,input_beats,read_index,fetch_index;
 reg [127:0] replay_head,replay_tail;
 reg [1:0] replay_count;
 reg replay_pending;
 wire replay_pop=state==SEND && replay_count!=0 && inner_ready;
 wire [2:0] replay_occupied={1'b0,replay_count}+{2'b0,replay_pending};
 wire replay_fetch=state==SEND && fetch_index<input_beats &&
   (replay_occupied<2 || (replay_pop && replay_occupied==2));
 reg [31:0] outer_tag,active_cycles,snapshot_cycles,issue_cycles,input_stalls,output_stalls,status;
 reg bad;
 reg [63:0] descriptors[0:31];
 reg [7:0] lookup[0:255];
 reg [127:0] transpose[0:15];
 wire final_step=step==count-1;
 wire accept=s_axis_tvalid && s_axis_tready;
 wire inner_ready,inner_valid,inner_last,inner_busy,inner_done,inner_error;
 wire [127:0] inner_data;
 wire [127:0] activation_data,lut_data;
 reg [127:0] write_data;
 wire activation_write=(state==INPUTS && accept) || state==WRITE;
 wire [11:0] activation_addr=state==INPUTS?input_index[11:0]:
                   ((group_index*16+row)*tiles+tile_index);
 wire [127:0] activation_input=state==INPUTS?s_axis_tdata:write_data;
 wire [4:0] selected_slot=descriptors[step[4:0]][4:0];
 wire [31:0] selected_tag=descriptors[step[4:0]][63:32];
 wire [7:0] mask_value=descriptors[step[4:0]][15:8];
 wire inner_input_valid=(state==IDLE && s_axis_tdata[39:32]!=15)?s_axis_tvalid:
   state==PASS?s_axis_tvalid:state==RUNHEAD || state==RUNMETA || (state==SEND && replay_count!=0);
 wire [127:0] inner_input_data=state==RUNHEAD?
   {selected_tag,7'b0,times,16'd256,16'd256,3'b0,selected_slot,8'd14,32'h32434e51}:
   state==RUNMETA?{119'b0,valid_times}:state==SEND?replay_head:s_axis_tdata;
 wire inner_input_last=state==RUNHEAD || state==RUNMETA?1'b0:
   state==SEND?read_index==input_beats-1:s_axis_tlast;
 wire inner_output_ready=state==PASS?m_axis_tready:
   state==ACK?(final_step?m_axis_tready:1'b1):state==OUTPUTS?(final_step?m_axis_tready:1'b1):state==COUNTER;
 assign s_axis_tready=aresetn && (state==IDLE?(s_axis_tdata[39:32]==15?1'b1:inner_ready):
   state==PASS?inner_ready:state==META || state==DESC || state==LUTIN || state==INPUTS || state==DRAIN);
 assign m_axis_tvalid=aresetn && (state==PASS?inner_valid:state==BADACK || state==FOOTER ||
   ((state==ACK || state==OUTPUTS) && final_step && inner_valid));
 assign m_axis_tdata=state==BADACK?{outer_tag,16'd256,16'd256,status,32'h32524e51}:
   state==FOOTER?{snapshot_cycles,output_stalls,input_stalls,issue_cycles}:
   state==ACK && final_step?{outer_tag,inner_data[95:0]}:inner_data;
 assign m_axis_tlast=state==PASS?inner_last:state==BADACK || state==FOOTER;
 assign busy=state!=IDLE;
 assign error=bad || inner_error;
 always @* begin
   write_data=0;
   for(integer lane=0;lane<16;lane=lane+1)
     write_data[lane*8+:8]=(tile_index*16+lane>=valid_times)?mask_value:
       lookup[transpose[lane][row*8+:8]];
 end
 xpm_memory_sdpram #(.MEMORY_SIZE(4096*128),.MEMORY_PRIMITIVE("block"),
   .CLOCKING_MODE("common_clock"),.ECC_MODE("no_ecc"),.USE_MEM_INIT(0),
   .WRITE_DATA_WIDTH_A(128),.BYTE_WRITE_WIDTH_A(128),.ADDR_WIDTH_A(12),
   .READ_DATA_WIDTH_B(128),.ADDR_WIDTH_B(12),.READ_LATENCY_B(1),.WRITE_MODE_B("read_first"),.SIM_ASSERT_CHK(1)) activation_bank(
   .clka(aclk),.clkb(aclk),.sleep(1'b0),.ena(activation_write),.wea(activation_write),
   .addra(activation_addr),.dina(activation_input),.injectsbiterra(1'b0),.injectdbiterra(1'b0),
   .rstb(1'b0),.enb(replay_fetch),.regceb(1'b1),.addrb(fetch_index[11:0]),
   .doutb(activation_data),.sbiterrb(),.dbiterrb());
 xpm_memory_sdpram #(.MEMORY_SIZE(512*128),.MEMORY_PRIMITIVE("block"),
   .CLOCKING_MODE("common_clock"),.ECC_MODE("no_ecc"),.USE_MEM_INIT(0),
   .WRITE_DATA_WIDTH_A(128),.BYTE_WRITE_WIDTH_A(128),.ADDR_WIDTH_A(9),
   .READ_DATA_WIDTH_B(128),.ADDR_WIDTH_B(9),.READ_LATENCY_B(1),.WRITE_MODE_B("read_first"),.SIM_ASSERT_CHK(1)) lut_bank(
   .clka(aclk),.clkb(aclk),.sleep(1'b0),.ena(state==LUTIN && accept),.wea(state==LUTIN && accept),
   .addra(lut_index),.dina(s_axis_tdata),.injectsbiterra(1'b0),.injectdbiterra(1'b0),
   .rstb(1'b0),.enb(state==LUTREAD),.regceb(1'b1),.addrb({step[4:0],lut_lane}),
   .doutb(lut_data),.sbiterrb(),.dbiterrb());
 qn_short_wide_inner #(.MAX_K(MAX_K),.MAX_M(MAX_M)) engine(
   .aclk(aclk),.aresetn(aresetn),.s_axis_tdata(inner_input_data),.s_axis_tvalid(inner_input_valid),
   .s_axis_tready(inner_ready),.s_axis_tlast(inner_input_last),.m_axis_tdata(inner_data),
   .m_axis_tvalid(inner_valid),.m_axis_tready(inner_output_ready),.m_axis_tlast(inner_last),
   .busy(inner_busy),.done(inner_done),.error(inner_error));
 always @(posedge aclk) begin
   if(!aresetn) begin
     state<=IDLE;done<=0;bad<=0;status<=0;times<=0;valid_times<=0;tiles<=0;count<=0;step<=0;
     desc_index<=0;lut_beats<=0;lut_index<=0;lut_lane<=0;row<=0;group_index<=0;time_row<=0;
     tile_index<=0;input_index<=0;input_beats<=0;read_index<=0;outer_tag<=0;
     fetch_index<=0;replay_count<=0;replay_pending<=0;replay_head<=0;replay_tail<=0;
     active_cycles<=0;snapshot_cycles<=0;issue_cycles<=0;input_stalls<=0;output_stalls<=0;
   end else begin
     done<=0;
     if(state!=IDLE && state!=PASS && state!=FOOTER)active_cycles<=active_cycles+1;
     if(state==INPUTS && !s_axis_tvalid)input_stalls<=input_stalls+1;
     if(m_axis_tvalid && !m_axis_tready && state!=PASS && state!=FOOTER)output_stalls<=output_stalls+1;
     if(state==SEND)begin
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
     case(state)
       IDLE:if(accept)begin
         bad<=0;status<=0;
         if(s_axis_tdata[39:32]!=15)state<=PASS;
         else begin
           outer_tag<=s_axis_tdata[127:96];times<=s_axis_tdata[88:80];tiles<=(s_axis_tdata[95:80]+15)>>4;
           input_beats<=256*((s_axis_tdata[95:80]+15)>>4);
           active_cycles<=0;issue_cycles<=0;input_stalls<=0;output_stalls<=0;step<=0;
           if(s_axis_tdata[31:0]!=32'h32434e51 || s_axis_tdata[79:40]!={16'd256,16'd256,8'b0} ||
             s_axis_tdata[95:80]==0 || s_axis_tdata[95:80]>256 || s_axis_tdata[127:96]==0 || s_axis_tlast)
               begin bad<=1;status<=1;state<=s_axis_tlast?BADACK:DRAIN;end
           else state<=META;
         end
       end
       PASS:if(inner_done)begin state<=IDLE;done<=1;end
       META:if(accept)begin
         if(s_axis_tlast || s_axis_tdata[127:24]!=0 || s_axis_tdata[15:13]!=0 ||
           s_axis_tdata[12:0]>times || s_axis_tdata[23:16]==0 || s_axis_tdata[23:16]>32)
             begin bad<=1;status<=1;state<=s_axis_tlast?BADACK:DRAIN;end
         else begin valid_times<=s_axis_tdata[8:0];count<=s_axis_tdata[21:16];desc_index<=0;
           lut_beats<=(s_axis_tdata[23:16]-1)*16;state<=DESC;end
       end
       DESC:if(accept)begin
         descriptors[desc_index[4:0]]<=s_axis_tdata[63:0];
         if(s_axis_tlast || s_axis_tdata[127:64]!=0 || s_axis_tdata[31:16]!=0 ||
           s_axis_tdata[7:5]!=0 || s_axis_tdata[63:32]==0)
             begin bad<=1;status<=1;state<=s_axis_tlast?BADACK:DRAIN;end
         else if(desc_index==count-1)begin lut_index<=0;input_index<=0;state<=count==1?INPUTS:LUTIN;end
         else desc_index<=desc_index+1;
       end
       LUTIN:if(accept)begin
         if(s_axis_tlast)begin bad<=1;status<=2;state<=BADACK;end
         else if(lut_index==lut_beats-1)begin input_index<=0;state<=INPUTS;end
         else lut_index<=lut_index+1;
       end
       INPUTS:if(accept)begin
         if(s_axis_tlast!=(input_index==input_beats-1))begin bad<=1;status<=2;state<=s_axis_tlast?BADACK:DRAIN;end
         else if(input_index==input_beats-1)begin lut_lane<=0;state<=count==1?RUNHEAD:LUTREAD;end
         else input_index<=input_index+1;
       end
       LUTREAD:state<=LUTWAIT;
       LUTWAIT:state<=LUTCOPY;
       LUTCOPY:begin
         for(integer i=0;i<16;i=i+1)lookup[lut_lane*16+i]<=lut_data[i*8+:8];
         if(lut_lane==15)state<=RUNHEAD;else begin lut_lane<=lut_lane+1;state<=LUTREAD;end
       end
       RUNHEAD:if(inner_ready)state<=RUNMETA;
       RUNMETA:if(inner_ready)begin
         read_index<=0;fetch_index<=0;replay_count<=0;replay_pending<=0;state<=SEND;
       end
       SEND:if(replay_pop)begin
         if(read_index==input_beats-1)state<=ACK;
         else read_index<=read_index+1;
       end
       ACK:if(inner_valid && inner_output_ready)begin
         if(inner_data[31:0]!=32'h32524e51 || inner_data[63:32]!=0 ||
           inner_data[95:64]!={16'd256,16'd256} || inner_data[127:96]!=selected_tag)bad<=1;
         group_index<=0;tile_index<=0;time_row<=0;state<=OUTPUTS;
       end
       OUTPUTS:if(inner_valid && inner_output_ready)begin
         if(final_step)begin
           if(time_row==15)begin time_row<=0;
             if(group_index==15)begin group_index<=0;if(tile_index==tiles-1)state<=COUNTER;else tile_index<=tile_index+1;end
             else group_index<=group_index+1;
           end else time_row<=time_row+1;
         end else begin
           transpose[time_row]<=inner_data;
           if(time_row==15)begin time_row<=0;row<=0;state<=WRITE;end
           else time_row<=time_row+1;
         end
       end
       WRITE:begin
         if(row==15)begin row<=0;
           if(group_index==15)begin group_index<=0;if(tile_index==tiles-1)state<=COUNTER;else begin tile_index<=tile_index+1;state<=OUTPUTS;end end
           else begin group_index<=group_index+1;state<=OUTPUTS;end
         end else row<=row+1;
       end
       COUNTER:if(inner_valid)begin
         issue_cycles<=issue_cycles+inner_data[31:0];
         input_stalls<=input_stalls+inner_data[63:32];output_stalls<=output_stalls+inner_data[95:64];
         if(!inner_last)bad<=1;
         if(final_step)begin snapshot_cycles<=active_cycles+1;state<=FOOTER;end
         else begin step<=step+1;lut_lane<=0;state<=step==count-2?RUNHEAD:LUTREAD;end
       end
       FOOTER:if(m_axis_tready)begin state<=IDLE;done<=1;end
       DRAIN:if(accept && s_axis_tlast)state<=BADACK;
       BADACK:if(m_axis_tready)begin state<=IDLE;done<=1;end
       default:begin state<=IDLE;bad<=1;end
     endcase
   end
 end
endmodule
