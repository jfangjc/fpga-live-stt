CC ?= cc
CFLAGS ?= -O3 -std=c11 -Wall -Wextra -Werror -fno-fast-math -ffp-contract=off
all: libqnc.so test_qnc
libqnc.so: qnc.c qnc.h
	$(CC) $(CFLAGS) -fPIC -shared qnc.c -lm -o $@
test_qnc: qnc.c qnc.h test_qnc.c
	$(CC) $(CFLAGS) qnc.c test_qnc.c -lm -o $@
test: test_qnc
	./test_qnc
clean:
	rm -f libqnc.so test_qnc
.PHONY: all test clean
