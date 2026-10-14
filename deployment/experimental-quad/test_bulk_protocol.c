/* Exercise the exact DMA validator, including all legacy QNC2 bounds tests. */
#define main original_protocol_checks
#include "test_layer_protocol.c"
#undef main
int main(void) {
 unsigned checks=0;unsigned char h[16];struct qn_layer_command c;
 const unsigned ms[]={1,17,256,640,1024},ts[]={1,15,16,17,33,129,1008,1024,2048,4096};
 original_protocol_checks();
 for(unsigned k=1;k<=1024;k++)for(unsigned mi=0;mi<5;mi++)for(unsigned ti=0;ti<10;ti++) {
  unsigned m=ms[mi],t=ts[ti],tiles=(t+15)/16,g=(m+15)/16;
  unsigned ib=16+k*tiles*16,rb=32+tiles*g*256;
  int expected=k*tiles<=65536 && rb<=QN_LAYER_BATCH_OUTPUT_BYTES;
  header(h,QN_LAYER_RUN_BULK,k,m,123);put32(h+8,k|(t<<16));
  assert((qn_layer_validate(h,ib,rb,&c)==0)==expected);checks++;
  assert(qn_layer_validate(h,ib-1,rb,&c)==-EINVAL);checks++;
  assert(qn_layer_validate(h,ib,rb+1,&c)==-EINVAL);checks++;
  assert(qn_layer_validate_batch(h,ib,rb,1,&c)==-EINVAL);checks++;
 }
 for(unsigned t=0;t<=65535;t+=4097) {
  header(h,QN_LAYER_RUN_BULK,1,1,123);put32(h+8,1|(t<<16));
  if(!t || t>4096)assert(qn_layer_validate(h,32,288,&c)==-EINVAL);
 }
 printf("PASS: %u retained-input bounds, capacities, lengths and unsupported batch checks\n",checks);
 return 0;
}
