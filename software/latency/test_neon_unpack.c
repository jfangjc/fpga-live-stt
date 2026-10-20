#define _GNU_SOURCE
#include "../ort_fpga_stream_branch512/qnc.h"
#include <assert.h>
#include <dlfcn.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {
 void *so;qnc *ctx;
 qnc*(*create)(qnc_exchange,void*);void(*close)(qnc*);
 int(*run)(qnc*,uint8_t*,size_t,size_t,unsigned,unsigned,const uint8_t*,size_t,size_t,uint8_t*,uint8_t*,unsigned);
 void(*profile)(const qnc*,qnc_profile*);
} backend;
static void put(uint8_t*p,unsigned v){for(int i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static unsigned get(const uint8_t*p){return p[0]|p[1]<<8|p[2]<<16|(unsigned)p[3]<<24;}
static int exchange(void*unused,const uint8_t*tx,uint8_t*rx,uint32_t a,uint32_t b,uint32_t c,int batch){
 (void)unused;(void)a;assert(c==1 && batch==0);
 unsigned t=get(tx+8)>>16,tiles=(t+15)/16,padded=tiles*16;
 assert(b==48+512*padded);
 for(unsigned output=0;output<2;output++){
  unsigned ack=output?16+256*padded:0,payload=ack+16;
  put(rx+ack,0x32524e51);put(rx+ack+4,0);put(rx+ack+8,256|(256<<16));put(rx+ack+12,11);
  for(unsigned tile=0;tile<tiles;tile++)for(unsigned group=0;group<16;group++)
   for(unsigned row=0;row<16;row++)for(unsigned lane=0;lane<16;lane++){
    unsigned ch=group*16+lane,time=tile*16+row;
    rx[payload+(tile*16+group)*256+row*16+lane]=(uint8_t)(ch*(output?17:11)+time*(output?7:13)+3);
   }
 }
 put(rx+b-16,2*tiles*2048);put(rx+b-12,0);put(rx+b-8,0);put(rx+b-4,2*tiles*2048+10000);
 return 0;
}
static int cmp(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return(x>y)-(x<y);}
static backend open_backend(const char*path){
 backend b={0};b.so=dlopen(path,RTLD_NOW|RTLD_LOCAL);if(!b.so){fprintf(stderr,"%s\n",dlerror());exit(2);}
 b.create=dlsym(b.so,"qnc_create");b.close=dlsym(b.so,"qnc_close");b.run=dlsym(b.so,"qnc_run_branch_reuse");b.profile=dlsym(b.so,"qnc_get_profile");
 assert(b.create && b.close && b.run && b.profile);b.ctx=b.create(exchange,NULL);assert(b.ctx);return b;
}
int main(int argc,char**argv){
 assert(argc==3);cpu_set_t affinity;CPU_ZERO(&affinity);CPU_SET(3,&affinity);assert(sched_setaffinity(0,sizeof(affinity),&affinity)==0);
 backend back[2]={open_backend(argv[1]),open_backend(argv[2])};int(*enabled)(void)=dlsym(back[1].so,"qnc_output_neon_enabled");assert(enabled && enabled()==1);
 const size_t prefix=32+2*16+2*86016+256,capacity=prefix+65536;
 uint8_t*packet=calloc(1,capacity),*x=malloc(65536),*y=malloc(65536+32),*r=malloc(65536+32);assert(packet&&x&&y&&r);
 put(packet,0x32434e51);put(packet+4,18|(256<<16));put(packet+12,11);
 for(unsigned i=0;i<65536;i++)x[i]=(uint8_t)(i*37+19);
 unsigned checks=0;
 for(unsigned t=1;t<=256;t++)for(unsigned stride=1;stride<=2;stride++)for(unsigned kind=0;kind<2;kind++){
  unsigned rt=(t+stride-1)/stride;
  memset(y,0xcd,65536+32);memset(r,0xcd,65536+32);
  assert(back[kind].run(back[kind].ctx,packet,prefix,capacity,2,11,x,t,t/2,y,r,stride)==0);
  for(unsigned ch=0;ch<256;ch++){
   for(unsigned p=0;p<t;p++)assert(y[ch*t+p]==(uint8_t)(ch*17+p*7+3));
   for(unsigned p=0;p<rt;p++)assert(r[ch*rt+p]==(uint8_t)(ch*11+p*stride*13+3));
  }
  for(unsigned i=0;i<32;i++){assert(y[256*t+i]==0xcd);assert(r[256*rt+i]==0xcd);}
  checks++;
 }
 unsigned contexts[]={1,4,7,8,13,16,17,26,32,65,126,256};
 printf("{\"complete\":true,\"hardware_execution\":false,\"neon_enabled\":true,\"exact_output_and_guard_cases\":%u,\"timings\":[",checks);
 unsigned record=0;
 for(unsigned ci=0;ci<sizeof(contexts)/sizeof(contexts[0]);ci++)for(unsigned stride=1;stride<=2;stride++){
  unsigned t=contexts[ci];double samples[2][300];
  for(unsigned rep=0;rep<310;rep++)for(unsigned order=0;order<2;order++){
   unsigned kind=(rep+order)&1;qnc_profile before,after;back[kind].profile(back[kind].ctx,&before);
   assert(back[kind].run(back[kind].ctx,packet,prefix,capacity,2,11,x,t,t,y,r,stride)==0);
   back[kind].profile(back[kind].ctx,&after);if(rep>=10)samples[kind][rep-10]=(after.unpack_seconds-before.unpack_seconds)*1e6;
  }
  for(unsigned kind=0;kind<2;kind++)qsort(samples[kind],300,sizeof(double),cmp);
  double old=(samples[0][149]+samples[0][150])/2,optimized=(samples[1][149]+samples[1][150])/2;
  printf("%s{\"times\":%u,\"stride\":%u,\"old_unpack_p50_us\":%.6f,\"neon_unpack_p50_us\":%.6f,\"reduction_percent\":%.6f}",record++?",":"",t,stride,old,optimized,100*(1-optimized/old));
 }
 printf("]}\n");
 for(unsigned i=0;i<2;i++){back[i].close(back[i].ctx);dlclose(back[i].so);}free(packet);free(x);free(y);free(r);return 0;
}
