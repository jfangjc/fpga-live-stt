// Terminal layouts on a file standing in for the terminal: ctest --test-dir build/app
#define _GNU_SOURCE // fileno and ftruncate under -std=c11
#include "term.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static FILE* file;

// Everything written since the last call
static const char* take(void) {
    static char got[4096];
    size_t n;
    fflush(file);
    rewind(file);
    n = fread(got, 1, sizeof got - 1, file);
    got[n] = 0;
    rewind(file);
    assert(!ftruncate(fileno(file), 0));
    return got;
}

#define HAS(got, s) assert(strstr(got, s))

int main(void) {
    const char* got;
    file = tmpfile();

    // 34 columns, so 30 characters a line between the margins: the screen clears and the status line is idle
    assert(!term_attach(file, 34, 1));
    got = take();
    assert(!strncmp(got, "\033[0m\033[H\033[2J", 10));
    HAS(got, "\033[8;1H  \033[2m*\033[0m \033[2m|");
    HAS(got, "\033[10;1H"); // the cursor waits under the layout

    // A live phrase on the first live line: settled words bold, the rest tentative, and no history
    term_show("", "hello world and", 11);
    got = take();
    HAS(got, "\033[5;1H  \033[1mhello world\033[0m\033[33m and\033[0m\033[K");
    HAS(got, "\033[2;1H  \033[0m\033[K\033[3;1H  \033[0m\033[K");
    // The next phrase moves the last one up into the history on the lower history line
    term_show("hello world and more", "next", 0);
    got = take();
    HAS(got, "\033[3;1H  \033[2mhello world and more\033[0m\033[K");
    HAS(got, "\033[5;1H  \033[1m\033[0m\033[33mnext");
    // A long phrase keeps its newest two lines and its first line moves up into the history
    term_show("", "one two three four five six seven eight nine ten eleven twelve", 90);
    got = take();
    HAS(got, "\033[3;1H  \033[2mone two three four five six\033[0m");
    HAS(got, "\033[5;1H  \033[1mseven eight nine ten eleven\033[0m");
    HAS(got, "\033[6;1H  \033[1mtwelve\033[0m");
    // Anything unprintable becomes a space
    term_show("", "a\tb", 3);
    HAS(take(), "\033[1ma b");

    // The status line: speaking lights the dot, the meter follows the level, the detail is cut to fit
    term_status(1, "fpga engine  decode 70 ms  delay 90 ms");
    got = take();
    HAS(got, "\033[8;1H  \033[32m*");
    HAS(got, "\033[2mfpga engine  decode\033[0m"); // 30 - 7 bars - 4 = 19 characters
    term_level(0.3); // two bars
    got = take();
    HAS(got, "\033[32m|\033[0m\033[32m|\033[0m\033[2m|");
    assert(!strstr(got, "\033[32m|\033[0m\033[32m|\033[0m\033[32m|"));
    term_level(0.3); // no change, nothing written
    assert(!*take());
    // Clearing empties the captions and leaves the status line alone
    term_show("", "", 0);
    got = take();
    HAS(got, "\033[5;1H  \033[0m\033[K\033[6;1H  \033[0m\033[K");
    assert(!strstr(got, "\033[8;1H"));

    // Without the status line the status calls write nothing
    assert(!term_attach(file, 80, 0));
    got = take();
    assert(!strstr(got, "\033[8;1H"));
    term_status(1, "ignored");
    term_level(1);
    assert(!*take());

    fclose(file);
    puts("PASS term: captions, history, overflow, status line, no status");
    return 0;
}
