#include "qnc.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct transport { unsigned calls; int fail;unsigned tag[4],loaded[4]; };
static uint32_t get(const uint8_t*p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t*p,uint32_t x){for(unsigned i=0;i<4;i++)p[i]=x>>(8*i);}
static int exchange(void*opaque,const uint8_t*tx,uint8_t*rx,uint32_t in,uint32_t out,uint32_t count,int batch){
 struct transport*s=opaque;s->calls++;if(s->fail)return -EIO;
 unsigned op=tx[4],slot=tx[5],k=get(tx+8)&65535,m=get(tx+4)>>16,t=get(tx+8)>>16,tag=get(tx+12);
 assert(slot<4&&k==256&&count==1&&!batch&&get(tx)==0x32434e51);
 memset(rx,0,out);put(rx,0x32524e51);put(rx+8,k|(m<<16));put(rx+12,tag);
 if(op==9){assert(m==256&&in==16+65536+4096&&out==16);s->tag[slot]=tag;s->loaded[slot]=1;}
 else if(op==10){assert(m==11&&in==16+8192&&out==16&&s->tag[slot]==tag&&s->loaded[slot]==1);s->loaded[slot]=2;}
 else {assert(op==11&&m==256&&t==17&&s->tag[slot]==tag&&s->loaded[slot]==2);
  assert(in==32+8192&&out==32+8192);memset(rx+16,slot+7,8192);
  put(rx+out-16,2*8*256);put(rx+out-4,5000);
 }
 return 0;
}
int main(void){
 struct transport mock={0};qnc*c=qnc_create(exchange,&mock);assert(c);
 int8_t*w=calloc(65536,1),*dw=calloc(256*11,1);int32_t b[256]={0},mult[256]={0};uint8_t shifts[256];memset(shifts,1,sizeof(shifts));
 uint8_t x[256*17]={0},y[256*17];
 for(unsigned slot=0;slot<4;slot++){
  assert(!qnc_select_slot(c,slot));assert(!qnc_load_quant(c,w,256,256,b,mult,shifts,slot+7));
  assert(!qnc_load_depthwise(c,dw,b,mult,shifts,0,0));
 }
 unsigned warm_start=mock.calls;
 for(int repeat=0;repeat<2;repeat++)for(int slot=3;slot>=0;slot--){
  assert(!qnc_select_slot(c,slot));assert(!qnc_run_pair(c,x,17,13,y));
  for(unsigned i=0;i<sizeof(y);i++)assert(y[i]==slot+7);
 }
 assert(mock.calls==warm_start+8);qnc_stats stats;qnc_get_stats(c,&stats);assert(stats.loads==8&&stats.ioctls==16);
 assert(qnc_select_slot(c,4)==-EINVAL);
 mock.fail=1;assert(qnc_run_pair(c,x,17,13,y)==-EIO);
 unsigned failed=mock.calls;
 for(unsigned slot=0;slot<4;slot++){assert(!qnc_select_slot(c,slot));assert(qnc_run_pair(c,x,17,13,y)==-EINVAL);}
 assert(mock.calls==failed);free(w);free(dw);qnc_close(c);
 puts("PASS: four-slot transport residency, tags, exact byte unpacking and error invalidation");return 0;
}
