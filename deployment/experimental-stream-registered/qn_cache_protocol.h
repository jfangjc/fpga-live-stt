/* SPDX-License-Identifier: GPL-2.0 */
#ifndef QN_CACHE_PROTOCOL_H
#define QN_CACHE_PROTOCOL_H
#include "qn_layer_protocol.h"
#define QN_STREAM_STAGE_BYTES 86016U
static inline int qn_cache_validate(void *packet, __u32 input_bytes,
                                   __u32 output_bytes, struct qn_layer_command *c)
{
 const unsigned char *h=packet;
 __u32 t,n,i,j,k,offset;
 if(input_bytes<48 || get_unaligned_le32(h)!=QN_LAYER_COMMAND_MAGIC ||
    get_unaligned_le32(h+4)!=(17U|(256U<<16)) ||
    (get_unaligned_le32(h+8)&0xffff)!=256 || !get_unaligned_le32(h+12))return -EINVAL;
 t=get_unaligned_le32(h+8)>>16;n=get_unaligned_le32(h+16)>>16;
 if(!t || t>256 || !n || n>8 || (get_unaligned_le32(h+16)&0xffff)>t ||
    get_unaligned_le32(h+20) || get_unaligned_le32(h+24) || get_unaligned_le32(h+28) ||
    input_bytes!=32+n*16+n*QN_STREAM_STAGE_BYTES+(n-1)*256+256*((t+15)/16)*16 ||
    output_bytes!=32+((t+15)/16)*16*256)return -EINVAL;
 offset=32+n*16;
 for(i=0;i<n;i++){
  const unsigned char *d=h+32+i*16;
  const unsigned char *pw=h+offset+65536,*dw=h+offset+69632,*dp=dw+12288;
  __u32 descriptor=get_unaligned_le32(d),kernel=(descriptor>>16)&63;
  if((descriptor&0xffc000e0U) || (descriptor&31)!=i || !kernel || kernel>41 || !(kernel&1) ||
     !get_unaligned_le32(d+4) || get_unaligned_le32(d+8) || get_unaligned_le32(d+12))return -EINVAL;
  for(j=0;j<256;j++){
   const unsigned char *p=pw+j*16;
   __u32 flags=get_unaligned_le32(p+8),mult=get_unaligned_le32(p+4);
   if((mult&0x8000007fU) || (flags&0xffff00c0U) || !(flags&63) || (flags&63)==63 || get_unaligned_le32(p+12))return -EINVAL;
   for(k=kernel;k<48;k++)if(dw[j*48+k])return -EINVAL;
   p=dp+j*16;flags=get_unaligned_le32(p+8);mult=get_unaligned_le32(p+4);
   if((mult&0x8000007fU) || (flags&0xffff00c0U) || !(flags&63) || (flags&63)==63 || get_unaligned_le32(p+12)>255)return -EINVAL;
  }
  offset+=QN_STREAM_STAGE_BYTES;
 }
 c->op=17;c->k=256;c->m=256;c->tag=get_unaligned_le32(h+12);c->times=t;
 return 0;
}
#endif
