// captions in a terminal
#ifndef TERM_H
#define TERM_H
#include <stddef.h>
#include <stdio.h>

// setup -> called once at startup and returns -1 when stdout is not a terminal
// with status a line under the captions shows term_status and term_level
int term_open(int status);
// the same on any stream for test_term -> cols is the width when the stream has no terminal size
int term_attach(FILE* out, unsigned cols, int status);
// captions -> earlier phrases as two dim lines then the live phrase with its first stable characters settled
void term_show(const char* history, const char* live, size_t stable);
// status line -> a speaking dot and the backend and timing
void term_status(int speaking, const char* detail);
// microphone level for the status line's meter from 0 to 1
void term_level(double level);

#endif
