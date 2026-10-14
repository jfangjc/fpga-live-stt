#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
static __inline uint32_t get_unaligned_le32(const void *p) {
    const unsigned char *v=p;return v[0]|(uint32_t)v[1]<<8|(uint32_t)v[2]<<16|(uint32_t)v[3]<<24;
}
#include "qn_stream_registered.h"
static unsigned checks;
static void require(int yes) {checks++;if(!yes){fprintf(stderr,"FAIL registered bounds %u\n",checks);exit(1);}}
int main(void) {
    require(sizeof(struct qn_stream_register)==32 && sizeof(struct qn_stream_run)==40);
    require(_IOC_SIZE(QN_STREAM_REGISTER)==32 && _IOC_SIZE(QN_STREAM_RUN)==40);
    for(unsigned t=1;t<=256;t++)for(unsigned v=0;v<=t;v++){
        unsigned bytes=256*((t+15)/16)*16;
        struct qn_stream_run r={0,0,1,t,v,bytes,bytes+32};
        require(qn_stream_run_bounds(&r)==0);
        r.handle=0;require(qn_stream_run_bounds(&r)==-EINVAL);r.handle=1;
        r.valid_times=t+1;require(qn_stream_run_bounds(&r)==-EINVAL);r.valid_times=v;
        r.input_bytes=bytes-1;require(qn_stream_run_bounds(&r)==-EINVAL);r.input_bytes=bytes;
        r.output_bytes=bytes+31;require(qn_stream_run_bounds(&r)==-EINVAL);r.output_bytes=bytes+32;
        r.times=0;require(qn_stream_run_bounds(&r)==-EINVAL);
        r.times=257;require(qn_stream_run_bounds(&r)==-EINVAL);
    }
    for(unsigned n=1;n<=8;n++)for(unsigned align=32;align<=256;align*=2){
        unsigned prefix=qn_stream_prefix_bytes(n),cap=(prefix+65536+align-1)&~(align-1);
        unsigned head=(32+align-1)&~(align-1),tail=prefix&~(align-1);
        require(head<tail && !(head%align) && !(tail%align) && !(cap%align));
        require(tail<=prefix && prefix+65536<=cap && cap<=800000);
    }
    printf("PASS: %u registered ABI, request bounds and cache-line range checks\n",checks);
    return 0;
}
