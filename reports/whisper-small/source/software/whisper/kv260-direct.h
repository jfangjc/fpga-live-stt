/* GGML v1.8.3 hook. One model/context per process. Physical failures abort.
 * Native QNC2 transport quantizes and unpacks directly in GGML row layout.
 */
#include "qnc.h"
#if defined(__aarch64__)
#include <arm_neon.h>
#endif
static qnc *kv260_device;
static uint64_t kv260_calls,kv260_attention_calls;
static double kv260_seconds,kv260_prepare_seconds;
struct kv260_weight_cache {
    const void *source;
    int64_t k,m;
    enum ggml_type type;
    bool ready;
    int8_t *values;
    float *scales;
    struct kv260_weight_cache *next;
};
static struct kv260_weight_cache *kv260_weights;
static struct kv260_weight_cache *kv260_active_weights;
static bool kv260_fill_active_weights;
static int8_t *kv260_scratch_weights;
static float kv260_scratch_scales[1024];
static int kv260_status;
static void kv260_sync(void *opaque){ggml_barrier((struct ggml_threadpool *)opaque);}

static void kv260_report(void) {
    qnc_stats s={0};qnc_profile p={0};
    if(kv260_device){qnc_get_stats(kv260_device,&s);qnc_get_profile(kv260_device,&p);}
    fprintf(stderr,"KV260_STATS calls=%llu seconds=%.6f ioctls=%llu loads=%llu runs=%llu tx_bytes=%llu rx_bytes=%llu ioctl_seconds=%.6f attention_calls=%llu\n",
        (unsigned long long)kv260_calls,kv260_seconds,(unsigned long long)s.ioctls,
        (unsigned long long)s.loads,(unsigned long long)s.runs,(unsigned long long)s.tx_bytes,
        (unsigned long long)s.rx_bytes,s.ioctl_seconds,(unsigned long long)kv260_attention_calls);
    fprintf(stderr,"KV260_PROFILE prepare=%.6f transport_load_pack=%.6f transport_scan=%.6f transport_run_pack=%.6f transport_unpack=%.6f\n",
        kv260_prepare_seconds,p.load_pack_seconds,p.scan_seconds,p.run_pack_seconds,p.unpack_seconds);
    qnc_close(kv260_device);
    while(kv260_weights){struct kv260_weight_cache *next=kv260_weights->next;
        free(kv260_weights->values);free(kv260_weights->scales);free(kv260_weights);kv260_weights=next;}
}

static void kv260_open_device(void) {
    if(kv260_device)return;
    FILE *p=fopen("/sys/module/qn_tile/parameters/bulk_protocol","r");int protocol=0;
    if(p){if(fscanf(p,"%d",&protocol)!=1)protocol=0;fclose(p);}
    if(protocol!=1)GGML_ABORT("KV260 requires matching bulk image/driver");
    kv260_device=qnc_open("/dev/qn-tile");
    if(!kv260_device)GGML_ABORT("Cannot open physical FPGA");
    atexit(kv260_report);
}

static float kv260_quant_row(const float *row,int k,int8_t *dst) {
    float peak=0;int i=0;
#if defined(__aarch64__)
    float32x4_t max4=vdupq_n_f32(0);
    for(;i+4<=k;i+=4){float32x4_t v=vabsq_f32(vld1q_f32(row+i));
        if(vminvq_u32(vcleq_f32(v,vdupq_n_f32(FLT_MAX)))!=UINT_MAX)GGML_ABORT("Nonfinite weight");
        max4=vmaxq_f32(max4,v);}
    peak=vmaxvq_f32(max4);
#endif
    for(;i<k;i++){if(!isfinite(row[i]))GGML_ABORT("Nonfinite weight");float a=fabsf(row[i]);if(a>peak)peak=a;}
    float scale=peak/127.f;if(scale==0)scale=1;i=0;
#if defined(__aarch64__)
    for(;i+4<=k;i+=4){
        float32x4_t v=vdivq_f32(vld1q_f32(row+i),vdupq_n_f32(scale));
        v=vmaxq_f32(vdupq_n_f32(-127),vminq_f32(vdupq_n_f32(127),v));
        int16x4_t q=vmovn_s32(vcvtq_s32_f32(vrndnq_f32(v)));
        int8x8_t bytes=vmovn_s16(vcombine_s16(q,vdup_n_s16(0)));
        int32_t word=vget_lane_s32(vreinterpret_s32_s8(bytes),0);memcpy(dst+i,&word,4);
    }
#endif
    for(;i<k;i++){float v=row[i]/scale;if(v>127)v=127;if(v< -127)v=-127;
        float base=floorf(v),d=v-base;int q=(int)base;
        if(d>0.5f || (d==0.5f && q%2))q++;dst[i]=(int8_t)q;}
    return scale;
}

static void kv260_read_row(const struct ggml_tensor *w,int64_t o,float *row) {
    const char *p=(const char *)w->data+o*w->nb[1];
    if(w->type==GGML_TYPE_F32)memcpy(row,p,(size_t)w->ne[0]*sizeof(float));
    else ggml_get_type_traits(w->type)->to_float(p,row,w->ne[0]);
}

static struct kv260_weight_cache *kv260_get_weights(const struct ggml_tensor *w) {
    int64_t K=w->ne[0],M=w->ne[1];
    for(struct kv260_weight_cache *c=kv260_weights;c;c=c->next)
        if(c->source==w->data && c->k==K && c->m==M && c->type==w->type)return c;
    struct kv260_weight_cache *c=calloc(1,sizeof(*c));
    if(!c)GGML_ABORT("Weight allocation failed");
    c->source=w->data;c->k=K;c->m=M;c->type=w->type;
    c->values=malloc((size_t)K*M);c->scales=malloc((size_t)M*((K+1023)/1024)*sizeof(float));
    if(!c->values || !c->scales)GGML_ABORT("Weight allocation failed");
    c->next=kv260_weights;kv260_weights=c;return c;
}

static void kv260_fill_weights(const struct ggml_tensor *w,struct kv260_weight_cache *c,
                               unsigned ith,unsigned nth) {
    const int64_t K=c->k,M=c->m;
    float row[5120];
    for(int64_t o=ith;o<M;o+=nth){kv260_read_row(w,o,row);
        for(int64_t ko=0;ko<K;ko+=1024){int k=(int)MIN(1024,K-ko);
            c->scales[(ko/1024)*M+o]=kv260_quant_row(row+ko,k,c->values+ko*M+o*k);}}
}

static bool kv260_attention(const struct ggml_compute_params *params,struct ggml_tensor *dst) {
    const char *enabled=getenv("WHISPER_KV260_ATTENTION");
    if(!enabled || strcmp(enabled,"1"))return false;
    const struct ggml_tensor *w=dst->src[0],*x=dst->src[1];
    if((w->ne[2]!=8 && w->ne[2]!=12 && w->ne[2]!=20) || x->ne[2]!=w->ne[2] || w->ne[3]!=1 || x->ne[3]!=1 ||
       x->type!=GGML_TYPE_F32 || dst->type!=GGML_TYPE_F32 ||
       (w->type!=GGML_TYPE_F16 && w->type!=GGML_TYPE_F32) ||
       !ggml_is_contiguous(dst) || x->nb[0]!=sizeof(float) ||
       x->ne[0]!=w->ne[0] || x->ne[1]<16 || x->ne[1]>1500 ||
       !((w->ne[0]==64 && w->ne[1]==1500) || (w->ne[0]==1500 && w->ne[1]==64)))return false;
    int64_t started=ggml_time_us();
    if(!params->ith){kv260_open_device();kv260_scratch_weights=malloc(1024*1024);
        if(!kv260_scratch_weights)GGML_ABORT("Attention weight allocation failed");}
    ggml_barrier(params->threadpool);
    int64_t K=w->ne[0],M=w->ne[1],T=x->ne[1];
    int8_t *qw=kv260_scratch_weights;float *sw=kv260_scratch_scales,row[1024];
    for(int h=0;h<w->ne[2];h++)for(int64_t ko=0;ko<K;ko+=1024)for(int64_t mo=0;mo<M;mo+=1024){
        int k=(int)MIN(1024,K-ko),m=(int)MIN(1024,M-mo);int64_t prep=ggml_time_us();
        for(int o=params->ith;o<m;o+=params->nth){
            for(int i=0;i<k;i++){const char *p=(const char *)w->data+h*w->nb[2]+(mo+o)*w->nb[1]+(ko+i)*w->nb[0];
                row[i]=w->type==GGML_TYPE_F16?ggml_fp16_to_fp32(*(const ggml_fp16_t *)p):*(const float *)p;}
            sw[o]=kv260_quant_row(row,k,qw+(size_t)o*k);
        }
        ggml_barrier(params->threadpool);
        if(!params->ith){kv260_prepare_seconds+=(ggml_time_us()-prep)*1e-6;
            kv260_status=qnc_load(kv260_device,qw,m,k);}
        ggml_barrier(params->threadpool);
        if(kv260_status)GGML_ABORT("Physical attention weight load failed: %d",kv260_status);
        const float *input=(const float *)((const char *)x->data+h*x->nb[2])+ko;
        float *out=(float *)((char *)dst->data+h*dst->nb[2])+mo;
        int rc=qnc_run_ggml_parallel(kv260_device,input,x->nb[1]/sizeof(float),T,sw,out,M,
            ko!=0,params->ith,params->nth,kv260_sync,params->threadpool);
        if(rc)GGML_ABORT("Physical attention failed: %d",rc);
    }
    if(!params->ith){free(qw);kv260_calls++;kv260_attention_calls++;kv260_seconds+=(ggml_time_us()-started)*1e-6;}
    return true;
}

static bool kv260_mul_mat(const struct ggml_compute_params *params,struct ggml_tensor *dst) {
    const char *enabled=getenv("WHISPER_KV260");if(!enabled || strcmp(enabled,"1"))return false;
    if(kv260_attention(params,dst))return true;
    const struct ggml_tensor *w=dst->src[0],*x=dst->src[1];
    const char *decode=getenv("WHISPER_KV260_DECODE");
    bool decoder=decode && !strcmp(decode,"1") && !strncmp(w->name,"decoder.",8);
    if(!strstr(w->name,".weight") ||
       (!decoder && strncmp(w->name,"encoder.blocks.",15) &&
        !strstr(w->name,".cross_attn.key.weight") && !strstr(w->name,".cross_attn.value.weight")) ||
       (w->type!=GGML_TYPE_F16 && w->type!=GGML_TYPE_F32 && w->type!=GGML_TYPE_Q8_0 && w->type!=GGML_TYPE_Q5_0) ||
       x->type!=GGML_TYPE_F32 || dst->type!=GGML_TYPE_F32 || x->nb[0]!=sizeof(float) ||
       w->ne[2]!=1 || w->ne[3]!=1 || x->ne[2]!=1 || x->ne[3]!=1 ||
       x->ne[1]<(decoder?1:16) || x->ne[1]>1500 || w->ne[0]<64 || w->ne[0]>5120 ||
       w->ne[1]<64 || w->ne[1]>(decoder?51866:5120) || x->ne[0]!=w->ne[0] || !ggml_is_contiguous(dst))return false;
    int64_t started=ggml_time_us();if(!params->ith)kv260_open_device();
    int64_t K=w->ne[0],M=w->ne[1],T=x->ne[1],prep=ggml_time_us();
    if(!params->ith){kv260_active_weights=kv260_get_weights(w);
        kv260_fill_active_weights=!kv260_active_weights->ready;}
    ggml_barrier(params->threadpool);
    struct kv260_weight_cache *weights=kv260_active_weights;
    if(kv260_fill_active_weights)kv260_fill_weights(w,weights,params->ith,params->nth);
    ggml_barrier(params->threadpool);
    if(!params->ith){weights->ready=true;kv260_prepare_seconds+=(ggml_time_us()-prep)*1e-6;}
    for(int64_t ko=0;ko<K;ko+=1024)for(int64_t mo=0;mo<M;mo+=1024){
        int k=(int)MIN(1024,K-ko),m=(int)MIN(1024,M-mo);
        if(!params->ith)kv260_status=qnc_load(kv260_device,weights->values+ko*M+mo*k,m,k);
        ggml_barrier(params->threadpool);
        if(kv260_status)GGML_ABORT("Physical matrix weight load failed: %d",kv260_status);
        const float *input=(const float *)x->data+ko;
        int rc=qnc_run_ggml_parallel(kv260_device,input,x->nb[1]/sizeof(float),T,
            weights->scales+(ko/1024)*M+mo,(float *)dst->data+mo,M,
            ko!=0,params->ith,params->nth,kv260_sync,params->threadpool);
        if(rc)GGML_ABORT("Physical matrix failed: %d",rc);
    }
    if(!params->ith){kv260_calls++;kv260_seconds+=(ggml_time_us()-started)*1e-6;}return true;
}
