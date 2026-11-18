/*
    captions in a terminal with ansi escapes -> over ssh, the serial console or the text console on the monitor
    -> the same layout as the monitor -> two dim history lines above two live lines then the status line
    -> the screen is cleared once and each line is redrawn in place at a fixed row
    -> the cursor rests under the layout so anything printed to stderr lands below the captions
    -> the terminal keeps its own colours so --theme only applies to the monitor
*/
#define _GNU_SOURCE
#include "term.h"
#include "display.h"
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define MARGIN 2      // spaces before every line
#define METER 7       // bars in the level meter
#define HISTORY_ROW 2 // two history lines from here
#define LIVE_ROW 5    // two live lines from here
#define STATUS_ROW 8  // the status line
#define REST_ROW 10   // where the cursor waits

#define DIM "\033[2m"
#define SETTLED "\033[1m"
#define TENTATIVE "\033[33m"
#define LIT "\033[32m"
#define PLAIN "\033[0m"

static FILE* out;
static unsigned fallback, level;
static int status, speaking;
static char detail[96];

// characters per line -> the terminal's width less the margins
static unsigned width(void) {
    struct winsize size;
    unsigned cols = ioctl(fileno(out), TIOCGWINSZ, &size) || !size.ws_col ? fallback : size.ws_col;
    return cols > 2 * MARGIN + 10 ? cols - 2 * MARGIN : 10;
}

// moves to the start of a row and writes the margin
static void row(unsigned r) { fprintf(out, "\033[%u;1H%*s", r, MARGIN, ""); }

// ends a row -> back to plain and the rest of the row erased
static void end(void) { fputs(PLAIN "\033[K", out); }

// writes text from a to b with anything unprintable as a space
static void text(const char* s, size_t a, size_t b) {
    for (size_t i = a; i < b; i++)
        fputc(s[i] >= ' ' && s[i] < 127 ? s[i] : ' ', out);
}

// sends the frame with the cursor under the layout
static void flush(void) {
    fprintf(out, "\033[%u;1H", REST_ROW);
    fflush(out);
}

// the status line -> the speaking dot then the meter then the detail
static void draw_status(void) {
    if (!status)
        return;
    row(STATUS_ROW);
    fputs(speaking ? LIT "*" PLAIN " " : DIM "*" PLAIN " ", out);
    for (unsigned i = 0; i < METER; i++)
        fputs(i < level ? LIT "|" PLAIN : DIM "|" PLAIN, out);
    // -> cut short instead of running off the line
    size_t length = strlen(detail), room = width() > METER + 4 ? width() - METER - 4 : 0;
    fputs("  " DIM, out);
    text(detail, 0, length < room ? length : room);
    end();
}

// sets up on a stream -> clears the screen and draws the empty layout
int term_attach(FILE* stream, unsigned cols, int with_status) {
    out = stream;
    fallback = cols;
    status = with_status;
    speaking = 0;
    level = 0;
    detail[0] = 0;
    fputs(PLAIN "\033[H\033[2J", out);
    draw_status();
    flush();
    return 0;
}

// stdout only when it is a terminal since the escapes would garble a file or a pipe
int term_open(int with_status) {
    if (!isatty(STDOUT_FILENO))
        return -1;
    // -> one write per frame instead of one per line
    setvbuf(stdout, NULL, _IOFBF, 16384);
    return term_attach(stdout, 80, with_status);
}

// draws the history and the live phrase -> called by emit on every preview and final
void term_show(const char* history, const char* live, size_t stable) {
    size_t start[64], stop[64];
    if (!out)
        return;
    unsigned cols = width();
    // -> history is the newest two lines and sits on the lower line when there is only one
    const char* past = display_past(history, live, cols);
    unsigned n = display_wrap(past, cols, start, stop, 2);
    for (unsigned i = 0; i < 2; i++) {
        row(HISTORY_ROW + i);
        if (i >= 2 - n) {
            fputs(DIM, out);
            text(past, start[i + n - 2], stop[i + n - 2]);
        }
        end();
    }
    // -> live is two lines with the characters before stable settled and the rest tentative
    n = display_wrap(live, cols, start, stop, 2);
    for (unsigned i = 0; i < 2; i++) {
        row(LIVE_ROW + i);
        if (i < n) {
            size_t split = stable < start[i] ? start[i] : stable > stop[i] ? stop[i] : stable;
            fputs(SETTLED, out);
            text(live, start[i], split);
            fputs(PLAIN TENTATIVE, out);
            text(live, split, stop[i]);
        }
        end();
    }
    flush();
}

// redraws the status line
void term_status(int now_speaking, const char* now) {
    if (!out || !status)
        return;
    speaking = now_speaking;
    snprintf(detail, sizeof detail, "%s", now);
    draw_status();
    flush();
}

// sets the meter from a 0 to 1 level -> only redraws when the number of bars changes
void term_level(double value) {
    unsigned bars = value <= 0 ? 0 : value >= 1 ? METER : (unsigned)(value * METER + 0.5);
    if (!out || !status || bars == level)
        return;
    level = bars;
    draw_status();
    flush();
}
