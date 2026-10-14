#define _POSIX_C_SOURCE 200809L
#include "qnc.h"
#include <errno.h>
#include <fcntl.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>
#if defined(__aarch64__) && defined(__ARM_NEON) && !defined(QNC_FORCE_SCALAR) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#include <arm_neon.h>
#define QNC_NEON 1
#endif
#define RX_CAP (4u * 1024u * 1024u)
#define TX_CAP 2099200u
#define CMD 0x32434e51u
#define ACK 0x32524e51u
struct request { uint64_t tx, rx; uint32_t a,b,c,d; };
_Static_assert(sizeof(struct request)==32, "ioctl ABI");
struct qnc { int fd; uint8_t *tx,*rx; unsigned k,m,tag; int valid,quantized; qnc_exchange exchange; void *opaque; qnc_stats stats; qnc_profile profile; };
static void put32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i)); }
static uint32_t get32(const uint8_t *p) { return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static void header(uint8_t *p,unsigned op,unsigned k,unsigned m,unsigned tag) { put32(p,CMD); put32(p+4,op|(m<<16)); put32(p+8,k); put32(p+12,tag); }
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec*1e-9; }
#ifdef QNC_NEON
/* Transpose one time-major 16x16 byte tile into contiguous channel rows. */
static void output16_u8(const uint8_t *src,uint8_t *dst,size_t stride,unsigned lanes) {
 uint8x16_t row[16];
 for(unsigned i=0;i<16;i++)row[i]=vld1q_u8(src+i*16);
 for(unsigned i=0;i<16;i+=2) {
  uint8x16x2_t r=vtrnq_u8(row[i],row[i+1]);row[i]=r.val[0];row[i+1]=r.val[1];
 }
 for(unsigned base=0;base<16;base+=4)for(unsigned j=0;j<2;j++) {
  uint16x8x2_t r=vtrnq_u16(vreinterpretq_u16_u8(row[base+j]),vreinterpretq_u16_u8(row[base+j+2]));
  row[base+j]=vreinterpretq_u8_u16(r.val[0]);row[base+j+2]=vreinterpretq_u8_u16(r.val[1]);
 }
 for(unsigned base=0;base<16;base+=8)for(unsigned j=0;j<4;j++) {
  uint32x4x2_t r=vtrnq_u32(vreinterpretq_u32_u8(row[base+j]),vreinterpretq_u32_u8(row[base+j+4]));
  row[base+j]=vreinterpretq_u8_u32(r.val[0]);row[base+j+4]=vreinterpretq_u8_u32(r.val[1]);
 }
 for(unsigned j=0;j<8;j++) {
  uint64x2_t a=vreinterpretq_u64_u8(row[j]),b=vreinterpretq_u64_u8(row[j+8]);
  row[j]=vreinterpretq_u8_u64(vtrn1q_u64(a,b));row[j+8]=vreinterpretq_u8_u64(vtrn2q_u64(a,b));
 }
 for(unsigned i=0;i<lanes;i++)vst1q_u8(dst+i*stride,row[i]);
}
#endif
static int linux_exchange(void *opaque,const uint8_t *tx,uint8_t *rx,uint32_t a,uint32_t b,uint32_t count,int batch) {
 qnc *c=opaque; struct request r={(uintptr_t)tx,(uintptr_t)rx,a,b,batch?count:0,0};
 /* Never retry: EINTR can mean a command partially executed. */
 return ioctl(c->fd,batch?_IOWR('Q',4,struct request):_IOWR('Q',3,struct request),&r)<0?-errno:0;
}
qnc *qnc_create(qnc_exchange exchange,void *opaque) {
 if(!exchange) { errno=EINVAL; return NULL; }
 qnc *c=calloc(1,sizeof(*c)); if(!c) return NULL; c->fd=-1;
 c->tx=malloc(TX_CAP); c->rx=malloc(RX_CAP);
 if(!c->tx||!c->rx) { qnc_close(c); errno=ENOMEM; return NULL; }
 c->exchange=exchange; c->opaque=opaque; return c;
}
qnc *qnc_open(const char *path) {
 qnc *c=qnc_create(linux_exchange,NULL); if(!c) return NULL;
 c->fd=open(path?path:"/dev/qn-tile",O_RDWR|O_CLOEXEC);
 if(c->fd<0) { int e=errno; qnc_close(c); errno=e; return NULL; } c->opaque=c; return c;
}
void qnc_close(qnc *c) { if(c) { if(c->fd>=0) close(c->fd); free(c->tx); free(c->rx); free(c); } }
static int transact(qnc *c,unsigned a,unsigned b,unsigned n,int batch) {
 double start=now(); int rc=c->exchange(c->opaque,c->tx,c->rx,a,b,n,batch);
 c->stats.ioctl_seconds+=now()-start; c->stats.ioctls++; c->stats.tx_bytes+=(uint64_t)a*n; c->stats.rx_bytes+=(uint64_t)b*n;
 if(rc) c->valid=0;
 return rc;
}
static int ack(qnc *c,const uint8_t *p,unsigned k,unsigned m,unsigned tag) {
 if(get32(p)!=ACK||get32(p+8)!=(k|(m<<16))||get32(p+12)!=tag||get32(p+4)) { c->valid=0; return -EPROTO; } return 0;
}
#ifdef QNC_NEON
/* Transpose eight contiguous K positions from eight channel rows. Destination
 * rows are K positions, stride 16 bytes (the other eight lanes belong to the
 * other half of this output group). No full tensor temporary is required. */
static void weights8(uint8_t *dst,const int8_t *src,unsigned k) {
 int8x8x2_t a0=vtrn_s8(vld1_s8(src),vld1_s8(src+k));
 int8x8x2_t a1=vtrn_s8(vld1_s8(src+2*k),vld1_s8(src+3*k));
 int8x8x2_t a2=vtrn_s8(vld1_s8(src+4*k),vld1_s8(src+5*k));
 int8x8x2_t a3=vtrn_s8(vld1_s8(src+6*k),vld1_s8(src+7*k));
 int16x4x2_t b0=vtrn_s16(vreinterpret_s16_s8(a0.val[0]),vreinterpret_s16_s8(a1.val[0]));
 int16x4x2_t b1=vtrn_s16(vreinterpret_s16_s8(a0.val[1]),vreinterpret_s16_s8(a1.val[1]));
 int16x4x2_t b2=vtrn_s16(vreinterpret_s16_s8(a2.val[0]),vreinterpret_s16_s8(a3.val[0]));
 int16x4x2_t b3=vtrn_s16(vreinterpret_s16_s8(a2.val[1]),vreinterpret_s16_s8(a3.val[1]));
 int32x2x2_t c0=vtrn_s32(vreinterpret_s32_s16(b0.val[0]),vreinterpret_s32_s16(b2.val[0]));
 int32x2x2_t c1=vtrn_s32(vreinterpret_s32_s16(b1.val[0]),vreinterpret_s32_s16(b3.val[0]));
 int32x2x2_t c2=vtrn_s32(vreinterpret_s32_s16(b0.val[1]),vreinterpret_s32_s16(b2.val[1]));
 int32x2x2_t c3=vtrn_s32(vreinterpret_s32_s16(b1.val[1]),vreinterpret_s32_s16(b3.val[1]));
 vst1_s8((int8_t*)dst,vreinterpret_s8_s32(c0.val[0])); vst1_s8((int8_t*)dst+16,vreinterpret_s8_s32(c1.val[0]));
 vst1_s8((int8_t*)dst+32,vreinterpret_s8_s32(c2.val[0])); vst1_s8((int8_t*)dst+48,vreinterpret_s8_s32(c3.val[0]));
 vst1_s8((int8_t*)dst+64,vreinterpret_s8_s32(c0.val[1])); vst1_s8((int8_t*)dst+80,vreinterpret_s8_s32(c1.val[1]));
 vst1_s8((int8_t*)dst+96,vreinterpret_s8_s32(c2.val[1])); vst1_s8((int8_t*)dst+112,vreinterpret_s8_s32(c3.val[1]));
}
static int32x4_t quant4(const float *x,float32x4_t scale) {
 float32x4_t v=vdivq_f32(vld1q_f32(x),scale);
 v=vmaxq_f32(vdupq_n_f32(-127.0f),vminq_f32(vdupq_n_f32(127.0f),v));
 /* FDIV, not reciprocal multiplication; FRINTN is explicit nearest-even. */
 return vcvtq_s32_f32(vrndnq_f32(v));
}
static void quant16(uint8_t *dst,const float *x,float32x4_t scale) {
 int16x8_t low=vcombine_s16(vmovn_s32(quant4(x,scale)),vmovn_s32(quant4(x+4,scale)));
 int16x8_t high=vcombine_s16(vmovn_s32(quant4(x+8,scale)),vmovn_s32(quant4(x+12,scale)));
 vst1q_s8((int8_t*)dst,vcombine_s8(vmovn_s16(low),vmovn_s16(high)));
}
static void output4(const uint8_t *src,int32x4_t columns[4]) {
 int32x4x2_t a=vtrnq_s32(vld1q_s32((const int32_t*)src),vld1q_s32((const int32_t*)(src+64)));
 int32x4x2_t b=vtrnq_s32(vld1q_s32((const int32_t*)(src+128)),vld1q_s32((const int32_t*)(src+192)));
 columns[0]=vcombine_s32(vget_low_s32(a.val[0]),vget_low_s32(b.val[0]));
 columns[1]=vcombine_s32(vget_low_s32(a.val[1]),vget_low_s32(b.val[1]));
 columns[2]=vcombine_s32(vget_high_s32(a.val[0]),vget_high_s32(b.val[0]));
 columns[3]=vcombine_s32(vget_high_s32(a.val[1]),vget_high_s32(b.val[1]));
}
#endif
static int load(qnc *c,const int8_t *w,unsigned m,unsigned k,
                const int32_t *bias,const int32_t *mult,const uint8_t *shift,uint8_t zero) {
 if(!c||!w||!m||!k||m>1024||k>1024) return -EINVAL;
 c->valid=0; c->tag=c->tag==UINT_MAX?1:c->tag+1; unsigned g=(m+15)/16,bytes=16+g*k*16;
 double start=now(); header(c->tx,bias?4:1,k,m,c->tag);
 /* Every valid byte is overwritten; only padded output lanes need clearing. */
 if(m%16) memset(c->tx+16+(g-1)*k*16,0,k*16);
 for(unsigned o=0;o<m;) {
  unsigned channels=m-o<8?m-o:8,i=0;
#ifdef QNC_NEON
  if(channels==8) for(;i+8<=k;i+=8) weights8(c->tx+16+(o/16*k+i)*16+o%16,w+(size_t)o*k+i,k);
#endif
  for(;i<k;i++) for(unsigned lane=0;lane<channels;lane++)
   c->tx[16+(o/16*k+i)*16+o%16+lane]=(uint8_t)w[(size_t)(o+lane)*k+i];
  o+=channels;
 }
 if(bias) {
  if(!mult||!shift) return -EINVAL;
  for(unsigned o=0;o<g*16;o++) {
   uint8_t *p=c->tx+bytes+o*16;
   if(o<m && (mult[o]<0||shift[o]<1||shift[o]>62))return -EINVAL;
   put32(p,o<m?(uint32_t)bias[o]:0);put32(p+4,o<m?(uint32_t)mult[o]:0);
   put32(p+8,o<m?shift[o]|((uint32_t)zero<<8):1);put32(p+12,0);
  }
  bytes+=g*256;
 }
 c->profile.load_pack_seconds+=now()-start;
 int rc=transact(c,bytes,16,1,0); if(!rc) rc=ack(c,c->rx,k,m,c->tag);
 if(!rc) { c->k=k; c->m=m; c->valid=1; c->quantized=bias!=NULL; c->stats.loads++; } return rc;
}
int qnc_load(qnc *c,const int8_t *w,unsigned m,unsigned k) {return load(c,w,m,k,NULL,NULL,NULL,0);}
int qnc_load_quant(qnc *c,const int8_t *w,unsigned m,unsigned k,const int32_t *b,const int32_t *mult,const uint8_t *shift,uint8_t z) {
 if(!b)return -EINVAL;
 return load(c,w,m,k,b,mult,shift,z);
}
int qnc_load_quant_packet(qnc *c,const uint8_t *body,size_t bytes,unsigned m,unsigned k) {
 if(!c || !body || !m || !k || m>1024 || k>1024)return -EINVAL;
 size_t expected=(size_t)((m+15)/16)*(k*16u+256u);
 if(bytes!=expected || bytes>TX_CAP-16)return -EINVAL;
 c->valid=0;c->tag=c->tag==UINT_MAX?1:c->tag+1;
 double start=now();header(c->tx,4,k,m,c->tag);memcpy(c->tx+16,body,bytes);
 c->profile.load_pack_seconds+=now()-start;
 int rc=transact(c,(unsigned)bytes+16,16,1,0);
 if(!rc)rc=ack(c,c->rx,k,m,c->tag);
 if(!rc){c->k=k;c->m=m;c->valid=1;c->quantized=1;c->stats.loads++;}
 return rc;
}
int qnc_invalidate(qnc *c) {
 if(!c) return -EINVAL;
 c->valid=0; header(c->tx,3,0,0,0);
 int rc=transact(c,16,16,1,0); return rc?rc:ack(c,c->rx,0,0,0);
}
/* Explicit nearest-even avoids caller rounding-mode dependency. */
static int8_t quant(float x,float scale) {
 float v=x/scale; if(v>=127) return 127; if(v<=-127) return -127;
 float f=floorf(v),d=v-f; int n=(int)f;
 if(d>0.5f||(d==0.5f&&(n%2))) n++;
 return (int8_t)n;
}
static int run(qnc *c,const void *x,size_t t,void *y,const float *scales,float scale,int mode) {
 int fp=mode==1,quantized=mode==2;
 if(!c||!c->valid||!x||!y||!t||t>SIZE_MAX/1024/sizeof(float)) return -EINVAL;
 if(c->quantized!=quantized)return -EINVAL;
 unsigned k=c->k,m=c->m,pb=16+16*k,rb=16+(quantized?256:1024)*((m+15)/16),limit=RX_CAP/rb;
 if(limit>128) limit=128;
 for(size_t start=0;start<t;) {
  size_t remaining=t-start; unsigned n=remaining>limit*16u?limit:(unsigned)(remaining/16+(remaining%16!=0));
  double pack_start=now();
#ifdef QNC_NEON
  float32x4_t vector_scale=vdupq_n_f32(scale);
#endif
  for(unsigned p=0;p<n;p++) {
   uint8_t *packet=c->tx+(size_t)p*pb; header(packet,quantized?5:2,k,m,c->tag);
   size_t offset=start+p*16u; unsigned nt=t-offset<16?(unsigned)(t-offset):16;
   for(unsigned i=0;i<k;i++) {
#ifdef QNC_NEON
    if(fp&&nt==16) { quant16(packet+16+i*16,(const float*)x+(size_t)i*t+offset,vector_scale); continue; }
#endif
    if(fp) for(unsigned j=0;j<nt;j++) packet[16+i*16+j]=(uint8_t)quant(((const float*)x)[(size_t)i*t+offset+j],scale);
    else memcpy(packet+16+i*16,(const int8_t*)x+(size_t)i*t+offset,nt);
    if(nt<16) memset(packet+16+i*16+nt,0,16-nt);
   }
  }
  c->profile.run_pack_seconds+=now()-pack_start;
  int rc=transact(c,pb,rb,n,1); if(rc) return rc;
  double unpack_start=now();
  for(unsigned p=0;p<n;p++) { rc=ack(c,c->rx+(size_t)p*rb,k,m,c->tag); if(rc) return rc; }
  for(unsigned p=0;p<n;p++) {
   const uint8_t *result=c->rx+(size_t)p*rb+16; size_t offset=start+p*16u; unsigned nt=t-offset<16?(unsigned)(t-offset):16;
   if(quantized) {
#ifdef QNC_NEON
    if(nt==16) {
     for(unsigned o=0;o<m;o+=16)output16_u8(result+(o/16)*256,
       (uint8_t*)y+(size_t)o*t+offset,t,m-o<16?m-o:16);
     continue;
    }
#endif
    for(unsigned o=0;o<m;o++) for(unsigned j=0;j<nt;j++)
     ((uint8_t*)y)[(size_t)o*t+offset+j]=result[(o/16)*256+j*16+o%16];
    continue;
   }
   unsigned o=0;
#ifdef QNC_NEON
   for(;o+4<=m;o+=4) {
    unsigned j=0;
    for(;j+4<=nt;j+=4) {
     int32x4_t columns[4]; output4(result+((o/16)*256+j*16+o%16)*4,columns);
     for(unsigned lane=0;lane<4;lane++) {
      if(fp) vst1q_f32((float*)y+(size_t)(o+lane)*t+offset+j,
             vmulq_f32(vcvtq_f32_s32(columns[lane]),vdupq_n_f32(scales[o+lane]*scale)));
      else vst1q_s32((int32_t*)y+(size_t)(o+lane)*t+offset+j,columns[lane]);
     }
    }
    for(unsigned lane=0;lane<4;lane++) for(unsigned tail=j;tail<nt;tail++) {
     uint32_t bits=get32(result+((o/16)*256+tail*16+o%16+lane)*4); int32_t value; memcpy(&value,&bits,4);
     if(fp) ((float*)y)[(size_t)(o+lane)*t+offset+tail]=(float)value*(scales[o+lane]*scale);
     else ((int32_t*)y)[(size_t)(o+lane)*t+offset+tail]=value;
    }
   }
#endif
   for(;o<m;o++) for(unsigned j=0;j<nt;j++) {
    uint32_t bits=get32(result+((o/16)*256+j*16+o%16)*4); int32_t value; memcpy(&value,&bits,4);
    if(fp) ((float*)y)[(size_t)o*t+offset+j]=(float)value*(scales[o]*scale);
    else ((int32_t*)y)[(size_t)o*t+offset+j]=value;
   }
  }
  c->profile.unpack_seconds+=now()-unpack_start;
  c->stats.runs+=n; start+=n*16u;
 } return 0;
}
int qnc_run_i8(qnc *c,const int8_t *x,size_t t,int32_t *y) { return run(c,x,t,y,NULL,1,0); }
int qnc_run_quant(qnc *c,const int8_t *x,size_t t,uint8_t *y) {return run(c,x,t,y,NULL,1,2);}
int qnc_run_f32(qnc *c,const float *x,size_t t,const float *scales,float *y,float *activation_scale) {
 if(!c||!c->valid||!x||!t||!scales||t>SIZE_MAX/1024/sizeof(float)) return -EINVAL;
 double scan_start=now(); float peak=0;size_t i=0,total=(size_t)c->k*t;
#ifdef QNC_NEON
 float32x4_t max4=vdupq_n_f32(0),largest=vdupq_n_f32(FLT_MAX);
 for(;i+4<=total;i+=4) {
  float32x4_t a=vabsq_f32(vld1q_f32(x+i));
  if(vminvq_u32(vcleq_f32(a,largest))!=UINT_MAX) return -EDOM;
  max4=vmaxq_f32(max4,a);
 }
 peak=vmaxvq_f32(max4);
#endif
 for(;i<total;i++) { if(!isfinite(x[i])) return -EDOM; float a=fabsf(x[i]); if(a>peak) peak=a; }
 for(unsigned o=0;o<c->m;o++) if(!isfinite(scales[o])||scales[o]<=0) return -EDOM;
 float scale=peak/127.0f; if(scale==0) scale=1;
 if(activation_scale) *activation_scale=scale;
 c->profile.scan_seconds+=now()-scan_start;
 return run(c,x,t,y,scales,scale,1);
}
void qnc_get_stats(const qnc *c,qnc_stats *stats) { if(c&&stats) *stats=c->stats; }
void qnc_get_profile(const qnc *c,qnc_profile *profile) { if(c&&profile) *profile=c->profile; }
int qnc_run_bulk(qnc *c,const uint8_t *x,size_t t,uint8_t *y) {
 if(!c || !c->valid || !c->quantized || !x || !y || !t || t>4096)return -EINVAL;
 unsigned tiles=(unsigned)((t+15)/16),groups=(c->m+15)/16;
 if(c->k>65536u/tiles)return -E2BIG;
 unsigned padded=tiles*16,ib=16+c->k*padded,rb=32+tiles*groups*256;
 if(ib>TX_CAP || rb>RX_CAP)return -E2BIG;
 double start=now();header(c->tx,6,c->k,c->m,c->tag);put32(c->tx+8,c->k|((unsigned)t<<16));
 for(unsigned k=0;k<c->k;k++) {
  memcpy(c->tx+16+(size_t)k*padded,x+(size_t)k*t,t);
  if(padded>t)memset(c->tx+16+(size_t)k*padded+t,0,padded-t);
 }
 c->profile.run_pack_seconds+=now()-start;
 int rc=transact(c,ib,rb,1,0);if(rc)return rc;
 rc=ack(c,c->rx,c->k,c->m,c->tag);if(rc)return rc;
 const uint8_t *counter=c->rx+rb-16;
 uint32_t issues=get32(counter),active=get32(counter+12);
 if(issues!=tiles*((groups+3)/4)*c->k || active<issues) {c->valid=0;return -EPROTO;}
 c->profile.mac_issue_cycles+=issues;c->profile.input_stall_cycles+=get32(counter+4);
 c->profile.output_stall_cycles+=get32(counter+8);c->profile.active_cycles+=active;
 start=now();
 for(unsigned tile=0;tile<tiles;tile++)for(unsigned g=0;g<groups;g++) {
  const uint8_t *src=c->rx+16+((size_t)tile*groups+g)*256;
  unsigned offset=tile*16,nt=t-offset<16?(unsigned)(t-offset):16;
  unsigned lanes=c->m-g*16<16?c->m-g*16:16;
#ifdef QNC_NEON
  if(nt==16) {output16_u8(src,y+(size_t)g*16*t+offset,t,lanes);continue;}
#endif
  for(unsigned o=0;o<lanes;o++)for(unsigned time=0;time<nt;time++)
   y[(size_t)(g*16+o)*t+offset+time]=src[time*16+o];
 }
 c->profile.unpack_seconds+=now()-start;c->stats.runs+=tiles;return 0;
}
