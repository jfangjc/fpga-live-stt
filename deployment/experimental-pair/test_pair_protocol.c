// Host test of packet admission before any DMA can be queued.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static uint32_t get_unaligned_le32(const void* p){const uint8_t* b=p;return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
#include "qn_layer_protocol.h"
static void put(uint8_t* p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static void demand(int yes){if(!yes){fprintf(stderr,"Protocol admission assertion failed\n");exit(1);}}
int main(void){
 uint8_t* p=calloc(1,2099200);demand(p!=NULL);struct qn_layer_command c;
 unsigned cases=0;
 for(unsigned k=1;k<=1024;k++){
  memset(p,0,16+k*32);put(p,QN_LAYER_COMMAND_MAGIC);put(p+4,7|(11u<<16));put(p+8,k);put(p+12,99);
  for(unsigned i=0;i<k;i++)put(p+16+k*16+i*16+8,1);
  demand(qn_layer_validate(p,16+k*32,16,&c)==0);cases++;
  demand(qn_layer_validate(p,16+k*32-1,16,&c)!=0);cases++;
  demand(qn_layer_validate(p,16+k*32,32,&c)!=0);cases++;
  uint8_t* q=p+16+k*16;
  put(q+4,0x80000000);demand(qn_layer_validate(p,16+k*32,16,&c)!=0);put(q+4,0);cases++;
  for(unsigned shift=0;shift<64;shift++){
   put(q+8,shift|(255u<<8));demand((qn_layer_validate(p,16+k*32,16,&c)==0)==(shift>0&&shift<63));cases++;
  }
  put(q+8,1);put(q+12,256);demand(qn_layer_validate(p,16+k*32,16,&c)!=0);cases++;
  put(q+12,255);p[27]=1;demand(qn_layer_validate(p,16+k*32,16,&c)!=0);cases++;
 }
 const unsigned lengths[]={1,15,16,17,51,101,4095,4096};
 for(unsigned k=1;k<=1024;k++)for(unsigned j=0;j<8;j++){
  unsigned t=lengths[j],tiles=(t+15)/16,m=257,g=(m+15)/16;
  memset(p,0,32);put(p,QN_LAYER_COMMAND_MAGIC);put(p+4,8|(m<<16));put(p+8,k|(t<<16));put(p+12,99);put(p+16,t);
  unsigned ib=32+k*tiles*16,ob=32+tiles*g*256;
  int eligible=k*tiles<=65536 && ob<=QN_LAYER_BATCH_OUTPUT_BYTES;
  demand((qn_layer_validate(p,ib,ob,&c)==0)==eligible);cases++;
  put(p+16,t+1);demand(qn_layer_validate(p,ib,ob,&c)!=0);cases++;
  put(p+16,0);put(p+20,1);demand(qn_layer_validate(p,ib,ob,&c)!=0);cases++;
  put(p+20,0);demand(qn_layer_validate(p,ib-16,ob,&c)!=0);cases++;
 }
 free(p);printf("PASS: %u paired packet admission and malformed bounds checks\n",cases);return 0;
}
