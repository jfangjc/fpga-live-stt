`timescale 1ns/1ps
// Integer implementation of int32->float32, float32 scale multiplication,
// nearest-even integer conversion and UINT8 saturation used by ARM ORT.
// Q31 parameters encode an exact float32 scale (multiplier low 7 bits zero).
module fused_affine_quant_exact #(parameter LANES=16)(
 input wire aclk,aresetn,
 input wire [LANES*32-1:0] s_acc,s_bias,s_multiplier,
 input wire [LANES*6-1:0] s_shift,input wire [LANES*8-1:0] s_zero,
 input wire s_valid,output wire s_ready,
 output reg [LANES*8-1:0] m_data,output wire m_valid,input wire m_ready,output reg m_error
);
 reg [5:0] valid;
 wire [5:0] ready;
 assign ready[5]=!valid[5] || m_ready;
 genvar stage;
 generate for(stage=0;stage<5;stage=stage+1)begin
  assign ready[stage]=!valid[stage] || ready[stage+1];
 end endgenerate
 assign s_ready=aresetn && ready[0];assign m_valid=aresetn && valid[5];
 reg [31:0] magnitude[0:LANES-1];reg [32:0] rounded_acc[0:LANES-1];
 reg [63:0] product[0:LANES-1],product_hold[0:LANES-1],rounded_product[0:LANES-1];
 reg [5:0] drops[0:LANES-1];
 reg [31:0] multipliers[0:1][0:LANES-1];
 reg [5:0] shifts[0:4][0:LANES-1];reg [7:0] zeros[0:4][0:LANES-1];
 reg negative[0:4][0:LANES-1],invalid[0:4][0:LANES-1];
 function automatic [5:0] leading_bit(input [63:0] value);
  reg [63:0] tmp;reg [5:0] result;
  begin
   tmp=value;result=0;
   if(|tmp[63:32])begin result=result+32;tmp=tmp>>32;end
   if(|tmp[31:16])begin result=result+16;tmp=tmp>>16;end
   if(|tmp[15:8])begin result=result+8;tmp=tmp>>8;end
   if(|tmp[7:4])begin result=result+4;tmp=tmp>>4;end
   if(|tmp[3:2])begin result=result+2;tmp=tmp>>2;end
   if(tmp[1])result=result+1;
   leading_bit=result;
  end
 endfunction
 function automatic [63:0] round_magnitude(input [63:0] value,input [5:0] drop);
  reg [63:0] q,remainder,half;
  begin
   if(drop==0)round_magnitude=value;
   else begin
    q=value>>drop;remainder=value&((64'd1<<drop)-1);half=64'd1<<(drop-1);
    q=q+((remainder>half)||((remainder==half)&&q[0]));round_magnitude=q<<drop;
   end
  end
 endfunction
 function automatic [7:0] output_byte(input [63:0] value,input [5:0] shift,
                                     input [7:0] zero,input neg,input bad);
  reg [63:0] q,remainder,half;reg signed [63:0] result;
  begin
   if(bad)output_byte=0;
   else begin
    q=value>>shift;remainder=value&((64'd1<<shift)-1);half=64'd1<<(shift-1);
    q=q+((remainder>half)||((remainder==half)&&q[0]));
    result=(neg?-$signed(q):$signed(q))+$signed({1'b0,zero});
    output_byte=result<0?0:result>255?255:result[7:0];
   end
  end
 endfunction
 reg signed [32:0] added;reg [5:0] highest,drop_acc;reg bad_output;
 integer i,j;
 always @(posedge aclk)begin
  if(!aresetn)begin valid<=0;m_data<=0;m_error<=0;end
  else begin
   if(ready[5])begin
    valid[5]<=valid[4];
    if(valid[4])begin
     bad_output=0;
     for(i=0;i<LANES;i=i+1)begin
      m_data[i*8+:8]<=output_byte(rounded_product[i],shifts[4][i],zeros[4][i],negative[4][i],invalid[4][i]);
      bad_output=bad_output|invalid[4][i];
     end
     m_error<=bad_output;
    end
   end
   for(j=1;j<5;j=j+1)if(ready[j])begin
    valid[j]<=valid[j-1];
    if(valid[j-1])for(i=0;i<LANES;i=i+1)begin
     shifts[j][i]<=shifts[j-1][i];zeros[j][i]<=zeros[j-1][i];
     negative[j][i]<=negative[j-1][i];invalid[j][i]<=invalid[j-1][i];
    end
   end
   if(ready[4] && valid[3])for(i=0;i<LANES;i=i+1)
    rounded_product[i]<=round_magnitude(product_hold[i],drops[i]);
   if(ready[3] && valid[2])for(i=0;i<LANES;i=i+1)begin
    highest=leading_bit(product[i]);drops[i]<=highest>23?highest-23:0;product_hold[i]<=product[i];
   end
   if(ready[2] && valid[1])for(i=0;i<LANES;i=i+1)
    product[i]<=rounded_acc[i]*multipliers[1][i][30:0];
   if(ready[1] && valid[0])for(i=0;i<LANES;i=i+1)begin
    highest=leading_bit({32'b0,magnitude[i]});drop_acc=highest>23?highest-23:0;
    rounded_acc[i]<=round_magnitude({32'b0,magnitude[i]},drop_acc);multipliers[1][i]<=multipliers[0][i];
   end
   if(ready[0])begin
    valid[0]<=s_valid;
    if(s_valid)for(i=0;i<LANES;i=i+1)begin
     added=$signed(s_acc[i*32+:32])+$signed({s_bias[i*32+31],s_bias[i*32+:32]});
     magnitude[i]<=added[31]?-$signed(added[31:0]):added[31:0];negative[0][i]<=added[31];
     multipliers[0][i]<=s_multiplier[i*32+:32];shifts[0][i]<=s_shift[i*6+:6];zeros[0][i]<=s_zero[i*8+:8];
     invalid[0][i]<=added[32]!=added[31] || s_multiplier[i*32+31] || |s_multiplier[i*32+:7] ||
                       s_shift[i*6+:6]==0 || s_shift[i*6+:6]==63;
    end
   end
  end
 end
endmodule
