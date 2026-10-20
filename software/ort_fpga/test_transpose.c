/* Independent scalar indexing checks vector transpose, partial channels and guards. */
#include "qnc_transport.c"
#include <assert.h>
#include <stdio.h>
int main(void) {
#ifndef QNC_NEON
 puts("ARM64 NEON execution required");return 1;
#else
 uint8_t input[257],actual[16*1030],expected[16*1030];unsigned checks=0;
 uint32_t state=20261009;
 for(unsigned stride=16;stride<=1024;stride+=17)for(unsigned lanes=1;lanes<=16;lanes++) {
  for(unsigned i=0;i<257;i++) {state^=state<<13;state^=state>>17;state^=state<<5;input[i]=(uint8_t)state;}
  memset(actual,0xa5,sizeof(actual));memset(expected,0xa5,sizeof(expected));
  unsigned offset=3;
  for(unsigned c=0;c<lanes;c++)for(unsigned t=0;t<16;t++)expected[offset+c*stride+t]=input[1+t*16+c];
  output16_u8(input+1,actual+offset,stride,lanes);
  assert(!memcmp(actual,expected,sizeof(actual)));checks+=lanes*16;
 }
 printf("PASS: %u independently indexed bytes, partial channel counts, unaligned input/output and guard regions\n",checks);
 return 0;
#endif
}
