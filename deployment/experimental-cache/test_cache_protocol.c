#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t get_unaligned_le32(const void *v){const uint8_t*p=v;return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put32(void *v,uint32_t x){uint8_t*p=v;for(unsigned i=0;i<4;i++)p[i]=x>>(8*i);}
#include "qn_cache_protocol.h"
static unsigned checks;
static void check(uint8_t*p,unsigned in,unsigned out,int valid){
 struct qn_layer_command c;unsigned op=p[4],slot=p[5];
 int rc=qn_cache_validate(p,in,out,&c);assert((rc==0)==valid);
 assert(p[4]==op&&p[5]==slot);if(valid)assert(c.op==op);checks++;
}
int main(void){
 uint8_t*p=calloc(1,2*1024*1024);assert(p);
 for(unsigned slot=0;slot<4;slot++){
  memset(p,0,2*1024*1024);put32(p,0x32434e51);put32(p+12,slot+1);
  put32(p+4,9|(slot<<8)|(256<<16));put32(p+8,256);
  for(unsigned i=0;i<256;i++)p[16+65536+i*16+8]=1;
  check(p,16+65536+4096,16,1);check(p,16+65536+4096-16,16,0);
  for(unsigned k=0;k<=1024;k++){put32(p+8,k);check(p,16+65536+4096,16,k==256);}
  put32(p+8,256);p[5]=4;check(p,16+65536+4096,16,0);p[5]=slot;
  p[4]=4;check(p,16+65536+4096,16,0);
  memset(p+16,0,2*1024*1024-16);
  put32(p+4,10|(slot<<8)|(11<<16));put32(p+8,256);
  for(unsigned i=0;i<256;i++)p[16+4096+i*16+8]=1;
  check(p,16+8192,16,1);
  p[16+11]=1;check(p,16+8192,16,0);p[16+11]=0;
  p[16+4096+8]=63;check(p,16+8192,16,0);p[16+4096+8]=1;
  p[16+4096+13]=1;check(p,16+8192,16,0);
  memset(p+16,0,2*1024*1024-16);
  put32(p+4,11|(slot<<8)|(256<<16));
  for(unsigned t=0;t<=4097;t++){
   put32(p+8,256|(t<<16));put32(p+16,t);
   unsigned bytes=256*((t+15)/16)*16;
   check(p,32+bytes,32+bytes,t>=1&&t<=4096);
   if(t>=1&&t<=4096){put32(p+16,t+1);check(p,32+bytes,32+bytes,0);}
  }
  put32(p+8,256|(51<<16));put32(p+16,51);p[20]=1;check(p,32+16384,32+16384,0);
 }
 free(p);printf("PASS: %u cache slot packet, bounds and normalization checks\n",checks);return 0;
}
