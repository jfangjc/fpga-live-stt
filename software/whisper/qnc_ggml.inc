/* Appended to the generic QNC2 transport by patch_upstream.py.
 * Input/output are GGML time-major rows, strides in float elements. Weights
 * remain resident only for this call. Each input column gets its own scale.
 * Accumulate into existing output, allowing exact K tiling before FP32 bias.
 */
#include <stdatomic.h>
static float qnc_ggml_scales[1500];
static atomic_int qnc_ggml_result;
static void qnc_ggml_sync(unsigned nth,qnc_barrier_fn barrier,void *opaque) {
    if(nth>1)barrier(opaque);
}
int qnc_run_ggml_parallel(qnc *c,const float *x,size_t xs,size_t t,const float *sw,float *y,size_t ys,
                         int add,unsigned ith,unsigned nth,qnc_barrier_fn barrier,void *opaque) {
    if(!c || !c->valid || c->quantized || !x || !sw || !y || !t || t>1500 ||
       xs<c->k || ys<c->m || !nth || ith>=nth || (nth>1 && !barrier))return -EINVAL;
    unsigned k=c->k,m=c->m,g=(m+15)/16;
    float *sx=qnc_ggml_scales;
    if(!ith)atomic_store(&qnc_ggml_result,0);
    qnc_ggml_sync(nth,barrier,opaque);
    double start_scan=now();
    for(unsigned o=ith;o<m;o+=nth)if(!isfinite(sw[o]) || sw[o]<=0)atomic_store(&qnc_ggml_result,-EDOM);
    for(size_t j=ith;j<t;j+=nth) {
        const float *row=x+j*xs;float peak=0;unsigned i=0;
#ifdef QNC_NEON
        float32x4_t max4=vdupq_n_f32(0);
        for(;i+4<=k;i+=4) {
            float32x4_t v=vabsq_f32(vld1q_f32(row+i));
            if(vminvq_u32(vcleq_f32(v,vdupq_n_f32(FLT_MAX)))!=UINT_MAX)atomic_store(&qnc_ggml_result,-EDOM);
            max4=vmaxq_f32(max4,v);
        }
        peak=vmaxvq_f32(max4);
#endif
        for(;i<k;i++){if(!isfinite(row[i]))atomic_store(&qnc_ggml_result,-EDOM);float a=fabsf(row[i]);if(a>peak)peak=a;}
        sx[j]=peak/127.f;if(sx[j]==0)sx[j]=1;
    }
    qnc_ggml_sync(nth,barrier,opaque);
    if(!ith)c->profile.scan_seconds+=now()-start_scan;
    int rc=atomic_load(&qnc_ggml_result);if(rc)return rc;
    unsigned pb=16+16*k,rb=16+1024*g,limit=RX_CAP/rb;
    if(limit>128)limit=128;
    for(size_t offset=0;offset<t;) {
        size_t left=t-offset;unsigned n=left>limit*16u?limit:(unsigned)((left+15)/16);
        double packed=now();
        for(unsigned p=ith;p<n;p+=nth) {
            uint8_t *packet=c->tx+(size_t)p*pb;
            header(packet,2,k,m,c->tag);
            size_t base=offset+16u*p;unsigned nt=t-base<16?(unsigned)(t-base):16;
            /* Only the last packet's invalid positions require clearing. */
            if(nt<16)memset(packet+16,0,16*k);
            unsigned j=0;
#ifdef QNC_NEON
            for(;j+4<=nt;j+=4) {
                unsigned i=0;
                for(;i+4<=k;i+=4) {
                    int32x4_t r[4];
                    for(unsigned lane=0;lane<4;lane++)r[lane]=quant4(x+(base+j+lane)*xs+i,vdupq_n_f32(sx[base+j+lane]));
                    int32x4x2_t a=vtrnq_s32(r[0],r[1]),b=vtrnq_s32(r[2],r[3]);
                    r[0]=vcombine_s32(vget_low_s32(a.val[0]),vget_low_s32(b.val[0]));
                    r[1]=vcombine_s32(vget_low_s32(a.val[1]),vget_low_s32(b.val[1]));
                    r[2]=vcombine_s32(vget_high_s32(a.val[0]),vget_high_s32(b.val[0]));
                    r[3]=vcombine_s32(vget_high_s32(a.val[1]),vget_high_s32(b.val[1]));
                    for(unsigned lane=0;lane<4;lane++) {
                        int16x4_t q16=vmovn_s32(r[lane]);
                        int8x8_t q8=vmovn_s16(vcombine_s16(q16,vdup_n_s16(0)));
                        int32_t word=vget_lane_s32(vreinterpret_s32_s8(q8),0);
                        memcpy(packet+16+(i+lane)*16+j,&word,4);
                    }
                }
                for(;i<k;i++)for(unsigned lane=0;lane<4;lane++)packet[16+i*16+j+lane]=(uint8_t)quant(x[(base+j+lane)*xs+i],sx[base+j+lane]);
            }
#endif
            for(;j<nt;j++)for(unsigned i=0;i<k;i++)packet[16+i*16+j]=(uint8_t)quant(x[(base+j)*xs+i],sx[base+j]);
        }
        qnc_ggml_sync(nth,barrier,opaque);
        if(!ith){c->profile.run_pack_seconds+=now()-packed;
            atomic_store(&qnc_ggml_result,transact(c,pb,rb,n,1));
            if(!atomic_load(&qnc_ggml_result))for(unsigned p=0;p<n;p++){
                int checked=ack(c,c->rx+(size_t)p*rb,k,m,c->tag);
                if(checked){atomic_store(&qnc_ggml_result,checked);break;}}
        }
        qnc_ggml_sync(nth,barrier,opaque);
        rc=atomic_load(&qnc_ggml_result);if(rc)return rc;
        packed=now();
        for(unsigned p=ith;p<n;p+=nth) {
            const uint8_t *packet=c->rx+(size_t)p*rb;
            size_t base=offset+16u*p;unsigned nt=t-base<16?(unsigned)(t-base):16;
            for(unsigned group=0;group<g;group++)for(unsigned j=0;j<nt;j++) {
                unsigned o=group*16,end=m-o<16?m-o:16,lane=0;
                const uint8_t *raw=packet+16+group*1024+j*64;
                float *dst=y+(base+j)*ys+o;
#ifdef QNC_NEON
                for(;lane+4<=end;lane+=4) {
                    float32x4_t scale=vmulq_n_f32(vld1q_f32(sw+o+lane),sx[base+j]);
                    float32x4_t value=vmulq_f32(vcvtq_f32_s32(vld1q_s32((const int32_t *)(raw+lane*4))),scale);
                    if(add)value=vaddq_f32(vld1q_f32(dst+lane),value);
                    vst1q_f32(dst+lane,value);
                }
#endif
                for(;lane<end;lane++) {
                    uint32_t bits=get32(raw+lane*4);int32_t v;memcpy(&v,&bits,4);
                    float value=(float)v*(sw[o+lane]*sx[base+j]);
                    dst[lane]=add?dst[lane]+value:value;
                }
            }
        }
        qnc_ggml_sync(nth,barrier,opaque);
        if(!ith){c->profile.unpack_seconds+=now()-packed;c->stats.runs+=n;}
        offset+=16u*n;
    }
    return 0;
}
int qnc_run_ggml(qnc *c,const float *x,size_t xs,size_t t,const float *sw,float *y,size_t ys) {
    return qnc_run_ggml_parallel(c,x,xs,t,sw,y,ys,1,0,1,NULL,NULL);
}
