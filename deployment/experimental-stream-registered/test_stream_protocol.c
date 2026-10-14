#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t __u32;
static __u32 get_unaligned_le32(const void *pointer){const unsigned char *p=pointer;return (__u32)p[0]|(__u32)p[1]<<8|(__u32)p[2]<<16|(__u32)p[3]<<24;}
#include "qn_cache_protocol.h"
static void put(unsigned char *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned checks;
static void require(int yes){checks++;if(!yes){fprintf(stderr,"FAIL stream packet check %u\n",checks);exit(1);}}
int main(void){
 unsigned char *p=calloc(1,800000);struct qn_layer_command c;
 for(unsigned n=1;n<=8;n++)for(unsigned t=1;t<=256;t++){
  unsigned len=32+n*16+n*QN_STREAM_STAGE_BYTES+(n-1)*256+256*((t+15)/16)*16;
  unsigned rx=32+((t+15)/16)*16*256;memset(p,0,len);
  put(p,QN_LAYER_COMMAND_MAGIC);put(p+4,17|(256<<16));put(p+8,256|(t<<16));put(p+12,701);put(p+16,t|(n<<16));
  for(unsigned i=0;i<n;i++){
   put(p+32+i*16,i|(37<<8)|(41<<16));put(p+36+i*16,801+i);
   unsigned base=32+n*16+i*QN_STREAM_STAGE_BYTES;
   for(unsigned j=0;j<256;j++){
    put(p+base+65536+j*16+4,0x40000000);put(p+base+65536+j*16+8,37|(128<<8));
    put(p+base+81920+j*16+4,0x40000000);put(p+base+81920+j*16+8,37|(127<<8));put(p+base+81920+j*16+12,128);
   }
  }
  require(qn_cache_validate(p,len,rx,&c)==0 && c.op==17 && c.times==t && c.tag==701);
  require(qn_cache_validate(p,len-16,rx,&c)==-EINVAL);require(qn_cache_validate(p,len,rx-16,&c)==-EINVAL);
  unsigned header_offsets[]={0,4,5,6,8,12,17,18,20,24,28};
  for(unsigned h=0;h<sizeof(header_offsets)/sizeof(header_offsets[0]);h++){
   unsigned o=header_offsets[h];unsigned char saved=p[o];p[o]^=h==6?128:1;
   if(o==12){p[o]=0;p[o+1]=0;}
   require(qn_cache_validate(p,len,rx,&c)==-EINVAL);
   p[o]=saved;if(o==12)p[o+1]=(701>>8);
  }
  unsigned saved_meta=get_unaligned_le32(p+16);
  put(p+16,0);require(qn_cache_validate(p,len,rx,&c)==-EINVAL);
  put(p+16,t|(9<<16));require(qn_cache_validate(p,len,rx,&c)==-EINVAL);
  put(p+16,(t+1)|(n<<16));require(qn_cache_validate(p,len,rx,&c)==-EINVAL);put(p+16,saved_meta);
  unsigned saved_shape=get_unaligned_le32(p+8);
  put(p+8,256);require(qn_cache_validate(p,len,rx,&c)==-EINVAL);
  put(p+8,256|(257<<16));require(qn_cache_validate(p,len,rx,&c)==-EINVAL);put(p+8,saved_shape);
  for(unsigned i=0;i<n;i++){
   unsigned d=32+i*16,base=32+n*16+i*QN_STREAM_STAGE_BYTES;
   unsigned offsets[]={d,d+2,d+3,d+8,d+12,base+65536+4,base+65536+7,base+65536+8,base+65536+12,
                       base+69632+41,base+81920+4,base+81920+7,base+81920+8,base+81920+13};
   unsigned masks[]={1,1,1,1,1,1,128,64,1,1,1,128,64,1};
   for(unsigned k=0;k<sizeof(offsets)/sizeof(offsets[0]);k++){
    unsigned o=offsets[k];unsigned char saved=p[o];p[o]^=masks[k];
    require(qn_cache_validate(p,len,rx,&c)==-EINVAL);p[o]=saved;
   }
   unsigned saved=get_unaligned_le32(p+d+4);put(p+d+4,0);require(qn_cache_validate(p,len,rx,&c)==-EINVAL);put(p+d+4,saved);
  }
 }
 free(p);printf("PASS: %u streamed block bounds, descriptors, weight padding and exact-scale checks\n",checks);return 0;
}
