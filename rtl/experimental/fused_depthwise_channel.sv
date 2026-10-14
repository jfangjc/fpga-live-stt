`timescale 1ns/1ps
// Experimental channel-major depthwise stage. One channel is retained locally;
// output beats can write the pointwise input bank without a host round trip.
// Odd symmetric kernels, stride/dilation one. Sixteen time lanes per tap.
module fused_depthwise_channel #(parameter MAX_T=4096, MAX_KERNEL=127)(
 input wire aclk,aresetn,
 input wire cfg_valid,output wire cfg_ready,
 input wire [12:0] cfg_times,cfg_valid_times,
 input wire [6:0] cfg_kernel,
 input wire [MAX_KERNEL*8-1:0] cfg_weights,
 input wire signed [31:0] cfg_bias,cfg_multiplier,
 input wire [5:0] cfg_shift,input wire [7:0] cfg_xzero,cfg_yzero,
 input wire [127:0] s_data,input wire s_valid,output wire s_ready,
 output wire [127:0] m_data,output wire m_valid,input wire m_ready,
 output wire m_last,output reg error,output reg done
);
 localparam AW=$clog2(MAX_T/16), IDLE=0, INPUTS=1, CLEAR=2, MAC=3, QUANT=4;
 reg [2:0] state;
 reg [12:0] times,valid_times;
 reg [6:0] kernel,tap,read_tap;
 reg [MAX_KERNEL*8-1:0] weights;
 reg signed [31:0] bias,multiplier;
 reg [5:0] shift;
 reg [7:0] xzero,yzero;
 reg [AW:0] tiles,write_tile,time_tile;
 reg read_valid,product_valid,product_last,quant_sent;
 reg [3:0] read_rotation;
 reg [15:0] read_inside;
 reg signed [17:0] products[0:15];
 reg signed [31:0] accum[0:15];
 wire [127:0] bank_data;
 wire issue=state==MAC && tap<kernel;
 wire signed [17:0] base=$signed({1'b0,time_tile,4'b0})+$signed({1'b0,tap})-$signed({1'b0,kernel>>1});
 wire [3:0] rotation=base[3:0];
 wire [511:0] qa,qb,qm;
 wire [95:0] qs;
 wire [127:0] qz,qdata;
 wire qvalid,qready,qerror;
 assign cfg_ready=aresetn && state==IDLE;
 assign s_ready=aresetn && state==INPUTS;
 assign m_valid=aresetn && state==QUANT && qvalid;
 assign m_last=m_valid && time_tile==tiles-1;
 genvar b;
 generate for(b=0;b<16;b=b+1) begin: banks
  (* ram_style="distributed" *) reg [7:0] memory[0:MAX_T/16-1];
  reg [7:0] read_byte;
  wire [3:0] displacement=b-rotation;
  wire signed [17:0] position=base+$signed({1'b0,displacement});
  always @(posedge aclk) begin
   if(s_valid && s_ready)memory[write_tile[AW-1:0]]<=s_data[b*8+:8];
   if(issue)read_byte<=memory[position[AW+3:4]];
  end
  assign bank_data[b*8+:8]=read_byte;
  assign qa[b*32+:32]=accum[b];assign qb[b*32+:32]=bias;
  assign qm[b*32+:32]=multiplier;assign qs[b*6+:6]=shift;assign qz[b*8+:8]=yzero;
  // Mask invalid output positions after requantization, in the UINT8 domain.
  assign m_data[b*8+:8]=(time_tile*16+b<valid_times)?qdata[b*8+:8]:yzero;
 end endgenerate
 fused_affine_quant #(.LANES(16)) quant(
  .aclk(aclk),.aresetn(aresetn && state==QUANT),
  .s_acc(qa),.s_bias(qb),.s_multiplier(qm),.s_shift(qs),.s_zero(qz),
  .s_valid(state==QUANT && !quant_sent),.s_ready(qready),
  .m_data(qdata),.m_valid(qvalid),.m_ready(m_ready && state==QUANT),.m_error(qerror));
 integer i;
 reg signed [8:0] centered;
 reg signed [17:0] position_i;
 always @(posedge aclk) begin
  if(!aresetn)begin
   state<=IDLE;times<=0;valid_times<=0;kernel<=0;tap<=0;read_tap<=0;
   weights<=0;bias<=0;multiplier<=0;shift<=1;xzero<=0;yzero<=0;
   tiles<=0;write_tile<=0;time_tile<=0;read_valid<=0;product_valid<=0;
   product_last<=0;quant_sent<=0;read_rotation<=0;read_inside<=0;error<=0;done<=0;
   for(i=0;i<16;i=i+1)begin accum[i]<=0;products[i]<=0;end
  end else begin
   done<=0;read_valid<=issue;
   product_valid<=state==MAC && read_valid;
   if(issue)begin
    read_tap<=tap;read_rotation<=rotation;tap<=tap+1;
    for(i=0;i<16;i=i+1)begin
     position_i=base+i;
     read_inside[i]<=position_i>=0 && position_i<times;
    end
   end
   if(state==MAC && read_valid)begin
    product_last<=read_tap==kernel-1;
    for(i=0;i<16;i=i+1)begin
     centered=read_inside[i]?$signed({1'b0,bank_data[((i+read_rotation)%16)*8+:8]})-$signed({1'b0,xzero}):9'sd0;
     products[i]<=centered*$signed(weights[read_tap*8+:8]);
    end
   end
   if(state==MAC && product_valid)
    for(i=0;i<16;i=i+1)accum[i]<=accum[i]+products[i];
   case(state)
    IDLE:if(cfg_valid)begin
     error<=0;
     if(cfg_times==0 || cfg_times>MAX_T || cfg_valid_times>cfg_times ||
        cfg_kernel==0 || cfg_kernel>MAX_KERNEL || !cfg_kernel[0] ||
        cfg_multiplier[31] || cfg_shift==0 || cfg_shift==63)begin error<=1;done<=1;end
     else begin
      times<=cfg_times;valid_times<=cfg_valid_times;kernel<=cfg_kernel;weights<=cfg_weights;
      bias<=cfg_bias;multiplier<=cfg_multiplier;shift<=cfg_shift;xzero<=cfg_xzero;yzero<=cfg_yzero;
      tiles<=(cfg_times+15)>>4;write_tile<=0;time_tile<=0;state<=INPUTS;
     end
    end
    INPUTS:if(s_valid)begin
     if(write_tile==tiles-1)state<=CLEAR;else write_tile<=write_tile+1;
    end
    CLEAR:begin
     for(i=0;i<16;i=i+1)accum[i]<=0;
     tap<=0;read_valid<=0;product_valid<=0;quant_sent<=0;state<=MAC;
    end
    MAC:if(product_valid && product_last)state<=QUANT;
    QUANT:begin
     if(!quant_sent && qready)quant_sent<=1;
     if(qvalid && m_ready)begin
      if(qerror)error<=1;
      if(time_tile==tiles-1)begin state<=IDLE;done<=1;end
      else begin time_tile<=time_tile+1;state<=CLEAR;end
     end
    end
    default:begin state<=IDLE;error<=1;done<=1;end
   endcase
  end
 end
endmodule
