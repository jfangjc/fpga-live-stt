// Simulation-only model of the fixed MAC configuration used by the PW core.
// Never included in synthesis. Conformance is checked against vendor DSP48E2.
module qn_mac_model #(
 parameter AREG=0,ACASCREG=0,BREG=0,BCASCREG=0,ADREG=0,DREG=0,CREG=0,
 parameter MREG=1,PREG=1,ALUMODEREG=0,OPMODEREG=0,INMODEREG=0,CARRYINREG=0,CARRYINSELREG=0,
 parameter USE_MULT="MULTIPLY"
)(input wire CLK,input wire [29:0] A,ACIN,input wire [17:0] B,BCIN,
 input wire [47:0] C,PCIN,input wire [26:0] D,
 input wire [3:0] ALUMODE,input wire [4:0] INMODE,input wire [8:0] OPMODE,
 input wire CARRYIN,input wire [2:0] CARRYINSEL,input wire CARRYCASCIN,MULTSIGNIN,
 input wire CEA1,CEA2,CEB1,CEB2,CEAD,CEC,CED,CEALUMODE,CECTRL,CEINMODE,CECARRYIN,CEM,CEP,
 input wire RSTA,RSTB,RSTC,RSTD,RSTALUMODE,RSTCTRL,RSTINMODE,RSTALLCARRYIN,RSTM,RSTP,
 output reg [47:0] P,output wire [29:0] ACOUT,output wire [17:0] BCOUT,output wire [47:0] PCOUT,
 output wire CARRYCASCOUT,output wire [3:0] CARRYOUT,output wire MULTSIGNOUT,
 output wire OVERFLOW,UNDERFLOW,PATTERNDETECT,PATTERNBDETECT,output wire [7:0] XOROUT);
 reg signed [44:0] product;
 initial if(AREG!=0 || BREG!=0 || MREG!=1 || PREG!=1 || ADREG!=0 || DREG!=0 || CREG!=0 ||
   ALUMODEREG!=0 || OPMODEREG!=0 || INMODEREG!=0 || USE_MULT!="MULTIPLY")
   $fatal(1,"Unsupported simulation MAC configuration");
 always @(posedge CLK)begin
  if(RSTM)product<=0;else if(CEM)product<=$signed(A[26:0])*$signed(B);
  if(RSTP)P<=0;else if(CEP)begin
   if(OPMODE!==9'b000100101 || ALUMODE!==0 || INMODE!==0 || CARRYIN!==0 || CARRYINSEL!==0)
    $fatal(1,"Unsupported simulation MAC operation");
   P<=$signed(P)+product;
  end
 end
 assign ACOUT=A;assign BCOUT=B;assign PCOUT=P;assign MULTSIGNOUT=product[44];
 assign CARRYCASCOUT=0;assign CARRYOUT=0;assign OVERFLOW=0;assign UNDERFLOW=0;
 assign PATTERNDETECT=0;assign PATTERNBDETECT=0;assign XOROUT=0;
endmodule
