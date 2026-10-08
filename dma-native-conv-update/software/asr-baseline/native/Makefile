CC ?= cc
CFLAGS ?= -O3 -std=c11 -Wall -Wextra -Werror
# Required independently of caller flags: preserve unfused FP32 accumulation.
FPFLAGS = -fno-fast-math -ffp-contract=off
all: libqn_depthwise.so
libqn_depthwise.so: qn_depthwise.c
	$(CC) $(CFLAGS) $(FPFLAGS) -fPIC -shared -pthread -o $@ $<
clean:
	rm -f libqn_depthwise.so
