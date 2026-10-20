#include "qnc.h"
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int8_t w[1024*1024]; unsigned k,m,tag; int bad,fail; unsigned calls; } mock;
static unsigned rd(const uint8_t *p) { return p[0]|(unsigned)p[1]<<8|(unsigned)p[2]<<16|(unsigned)p[3]<<24; }
static void wr(uint8_t *p,unsigned x) { for(unsigned i=0;i<4;i++) p[i]=(uint8_t)(x>>(8*i)); }
static int exchange(void *opaque,const uint8_t *tx,uint8_t *rx,uint32_t pb,uint32_t rb,uint32_t n,int batch) {
 mock *s=opaque; s->calls++; if(s->fail) return -EIO;
 assert(n>=1&&n<=128); assert(!batch||(size_t)rb*n<=133120);
 for(unsigned p=0;p<n;p++) {
  const uint8_t *a=tx+(size_t)p*pb; uint8_t *b=rx+(size_t)p*rb;
  assert(rd(a)==0x32434e51); unsigned op=rd(a+4)&255,m=rd(a+4)>>16,k=rd(a+8),tag=rd(a+12);
  memset(b,0,rb); wr(b,0x32524e51); wr(b+8,k|(m<<16)); wr(b+12,s->bad?tag+1:tag);
  if(op==1) {
   assert(!batch&&pb==16+((m+15)/16)*16*k&&rb==16);
   s->k=k;s->m=m;s->tag=tag;
   for(unsigned o=0;o<m;o++) for(unsigned i=0;i<k;i++) s->w[o*k+i]=(int8_t)a[16+(o/16*k+i)*16+o%16];
   for(unsigned o=m;o<((m+15)/16)*16;o++) for(unsigned i=0;i<k;i++) assert(a[16+(o/16*k+i)*16+o%16]==0);
  } else if(op==2) {
   assert(batch&&pb==16+16*k&&rb==16+((m+15)/16)*1024&&s->k==k&&s->m==m&&s->tag==tag);
   for(unsigned o=0;o<m;o++) for(unsigned t=0;t<16;t++) {
    int64_t sum=0; for(unsigned i=0;i<k;i++) sum+=(int64_t)s->w[o*k+i]*(int8_t)a[16+i*16+t];
    wr(b+16+((o/16)*256+t*16+o%16)*4,(unsigned)(int32_t)sum);
   }
  } else assert(op==3&&k==0&&m==0&&tag==0);
 } return 0;
}
static void check(unsigned m,unsigned k,size_t t) {
 mock *s=calloc(1,sizeof(*s)); qnc *c=qnc_create(exchange,s); assert(c);
 int8_t *w=malloc(m*k),*x=malloc(k*t); int32_t *y=malloc(m*t*4);
 for(unsigned i=0;i<m*k;i++) w[i]=(int8_t)((i*17u)%256-128);
 for(size_t i=0;i<k*t;i++) x[i]=(int8_t)((i*29u)%256-128);
 assert(qnc_run_i8(c,x,t,y)==-EINVAL); assert(qnc_load(c,w,m,k)==0); assert(qnc_run_i8(c,x,t,y)==0);
 for(unsigned o=0;o<m;o++) for(size_t j=0;j<t;j++) { int64_t sum=0; for(unsigned i=0;i<k;i++) sum+=(int64_t)w[o*k+i]*x[i*t+j]; assert(y[o*t+j]==sum); }
 qnc_stats stats; qnc_get_stats(c,&stats); assert(stats.loads==1&&stats.runs==(t+15)/16);
 s->bad=1; assert(qnc_run_i8(c,x,t,y)==-EPROTO); assert(qnc_run_i8(c,x,t,y)==-EINVAL);
 s->bad=0; assert(qnc_load(c,w,m,k)==0); s->fail=1; assert(qnc_run_i8(c,x,t,y)==-EIO); assert(qnc_run_i8(c,x,t,y)==-EINVAL);
 free(w);free(x);free(y);qnc_close(c);free(s);
}
static int8_t scalar_quant(float x,float scale) {
 float v=x/scale;if(v>=127) return 127;if(v<=-127) return -127;
 float f=floorf(v),d=v-f;int n=(int)f;
 if(d>0.5f||(d==0.5f&&(n%2))) n++;
 return (int8_t)n;
}
static void check_float(unsigned m,unsigned k,size_t t,float highest) {
 mock *s=calloc(1,sizeof(*s));qnc *c=qnc_create(exchange,s);assert(c);
 int8_t *w=malloc(m*k),*qx=malloc(k*t);float *x=malloc(k*t*4),*y=malloc(m*t*4),*scale=malloc(m*4);
 for(unsigned i=0;i<m*k;i++) w[i]=(int8_t)((i*17u)%256-128);
 for(size_t i=0;i<k*t;i++) x[i]=((float)((int)(i*29u%255)-127))*.5f;
 x[0]=highest;float act=0;
 for(unsigned o=0;o<m;o++) scale[o]=(float)(o%7+1)/127.0f;
 assert(qnc_load(c,w,m,k)==0);assert(qnc_run_f32(c,x,t,scale,y,&act)==0&&act==highest/127.0f);
 for(size_t i=0;i<k*t;i++) qx[i]=scalar_quant(x[i],act);
 for(unsigned o=0;o<m;o++) for(size_t j=0;j<t;j++) {
  int64_t sum=0;for(unsigned i=0;i<k;i++) sum+=(int64_t)w[o*k+i]*qx[i*t+j];
  float expected=(float)(int32_t)sum*(scale[o]*act);assert(memcmp(&expected,y+o*t+j,4)==0);
 }
 qnc_profile profile;qnc_get_profile(c,&profile);
 assert(profile.load_pack_seconds>=0&&profile.scan_seconds>=0&&profile.run_pack_seconds>=0&&profile.unpack_seconds>=0);
 free(w);free(qx);free(x);free(y);free(scale);qnc_close(c);free(s);
}
int main(void) {
 check(1,1,1); check(17,31,17); check(256,64,129); check(512,32,131); check(1024,1024,33);
 check_float(17,31,33,127);check_float(256,64,129,97.33f);check_float(1024,1024,17,123.456f);
 mock *s=calloc(1,sizeof(*s)); qnc *c=qnc_create(exchange,s); int8_t w=1; float scale=1,x[]={127,.5f,1.5f,2.5f,-.5f,-1.5f,-2.5f},y[7],as;
 assert(qnc_load(c,&w,1,1)==0); assert(qnc_run_f32(c,x,7,&scale,y,&as)==0&&as==1);
 float expected[]={127,0,2,2,0,-2,-2}; for(unsigned i=0;i<7;i++) assert(y[i]==expected[i]);
 x[0]=NAN; assert(qnc_run_f32(c,x,7,&scale,y,&as)==-EDOM);
 assert(qnc_invalidate(c)==0); qnc_close(c);free(s);
 puts("PASS: INT64 arithmetic, bit-exact full-tile FP32 scalar oracle (ties/non-power-of-two scales), padding/cropping, batches, corruption, I/O failure, invalidate"); return 0;
}
