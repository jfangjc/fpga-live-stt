/* SPDX-License-Identifier: GPL-2.0 */
#ifndef QN_CACHE_PROTOCOL_H
#define QN_CACHE_PROTOCOL_H
#include "qn_layer_protocol.h"
/* Normalize a private packet during validation, restoring every byte before DMA. */
static inline int qn_cache_validate(void *packet, __u32 input_bytes,
                                   __u32 output_bytes, struct qn_layer_command *c)
{
 unsigned char *h=packet;
 unsigned char op,flags;
 int result;
 if(input_bytes<16)return -EINVAL;
 op=h[4];flags=h[5];
 if(op==15) {
   __u32 times=get_unaligned_le32(h+8)>>16, n, i;
   if(input_bytes<48 || flags || get_unaligned_le32(h)!=QN_LAYER_COMMAND_MAGIC ||
     (get_unaligned_le32(h+4)>>16)!=256 || (get_unaligned_le32(h+8)&0xffff)!=256 ||
     !get_unaligned_le32(h+12) || !times || times>256)return -EINVAL;
   n=get_unaligned_le32(h+16)>>16;
   if(!n || n>32 || (get_unaligned_le32(h+16)&0xffff)>times ||
     get_unaligned_le32(h+20) || get_unaligned_le32(h+24) || get_unaligned_le32(h+28) ||
     input_bytes!=32+n*16+(n-1)*256+256*((times+15)/16)*16 ||
     output_bytes!=32+((times+15)/16)*16*256)return -EINVAL;
   for(i=0;i<n;i++) {
     const unsigned char *d=h+32+i*16;
     if((get_unaligned_le32(d)&0xffff00e0U) || !get_unaligned_le32(d+4) ||
       get_unaligned_le32(d+8) || get_unaligned_le32(d+12))return -EINVAL;
   }
   c->op=15;c->k=256;c->m=256;c->tag=get_unaligned_le32(h+12);c->times=times;
   return 0;
 }
 if(flags>31 || (op!=12 && op!=13 && op!=14) ||
    (get_unaligned_le32(h+8)&0xffff)!=256 ||
    (op!=13 && (get_unaligned_le32(h+4)>>16)!=256))return -EINVAL;
 h[4]=op==12?4:op==13?7:8;h[5]=0;
 result=qn_layer_validate(packet,input_bytes,output_bytes,c);
 h[4]=op;h[5]=flags;c->op=op;
 return result;
}
#endif
