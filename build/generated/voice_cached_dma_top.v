`timescale 1ns/1ps
module voice_cached_dma_top (
 output pmod_i2s_lrclk, output pmod_i2s_bclk, input pmod_i2s_dout,
 output pmod_i2s2_lrclk, output pmod_i2s2_bclk, input pmod_i2s2_dout,
 output pmod_led_d1, input pmod_btn_sw1
);
 voice_cached_dma_system_wrapper system_i(.mic_bclk(pmod_i2s_bclk),
   .mic_ws(pmod_i2s_lrclk), .mic_data(pmod_i2s_dout));
 assign pmod_i2s2_lrclk = 1'b0;
 assign pmod_i2s2_bclk = 1'b0;
 assign pmod_led_d1 = 1'b1;
endmodule

