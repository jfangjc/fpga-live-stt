#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int qn_depthwise_f32(const float *,const float *,const float *,float *,
                    size_t,size_t,size_t,size_t,size_t,size_t,size_t,size_t,unsigned);
int main(void) {
    for (size_t t=1;t<=67;t+=3) for(size_t k=1;k<=17;k+=4)
    for(size_t st=1;st<=3;++st) for(size_t di=1;di<=3;++di) {
        size_t n=2,c=7,left=13,right=12,ext=di*(k-1)+1;
        if(t+left+right<ext) continue;
        size_t out=(t+left+right-ext)/st+1;
        float *x=malloc(n*c*t*sizeof(float)),*w=malloc(c*k*sizeof(float));
        float *b=malloc(c*sizeof(float)),*y=malloc(n*c*out*sizeof(float));
        float *z=malloc(n*c*out*sizeof(float));
        assert(x&&w&&b&&y&&z);
        for(size_t i=0;i<n*c*t;++i)x[i]=(float)((int)(i%31)-15)/17;
        for(size_t i=0;i<c*k;++i)w[i]=(float)((int)(i%13)-6)/9;
        for(size_t i=0;i<c;++i)b[i]=(float)i/13;
        assert(!qn_depthwise_f32(x,w,b,y,n,c,t,k,st,di,left,right,1));
        assert(!qn_depthwise_f32(x,w,b,z,n,c,t,k,st,di,left,right,4));
        assert(!memcmp(y,z,n*c*out*sizeof(float)));
        assert(!qn_depthwise_f32(x,w,NULL,z,n,c,t,k,st,di,left,right,4));
        assert(qn_depthwise_f32(x,w,b,x,n,c,t,k,st,di,left,right,1)<0);
        assert(qn_depthwise_f32(x,w,b,y,n,c,t,k,0,di,left,right,1)<0);
        free(x);free(w);free(b);free(y);free(z);
    }
    float f[4]={0};
    assert(qn_depthwise_f32(f,f,NULL,f,SIZE_MAX,2,1,1,1,1,0,0,1)<0);
    assert(qn_depthwise_f32(f,f,NULL,(float *)(UINTPTR_MAX-3),1,1,2,1,1,1,0,0,1)<0);
    puts("PASS: ASan/UBSan padding, stride, dilation, threading and invalid request checks");
    return 0;
}
