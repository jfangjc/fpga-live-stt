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
 if(flags>3 || (op!=9 && op!=10 && op!=11) ||
    (get_unaligned_le32(h+8)&0xffff)!=256 ||
    (get_unaligned_le32(h+4)>>16)!=(op==10?11:256))return -EINVAL;
 h[4]=op==9?4:op==10?7:8;h[5]=0;
 result=qn_layer_validate(packet,input_bytes,output_bytes,c);
 h[4]=op;h[5]=flags;c->op=op;
 return result;
}
#endif
