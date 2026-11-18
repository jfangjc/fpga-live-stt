/*
    live captions on the monitor or in a terminal
    usage -> screen hybrid|cpu MODEL running_prior.json [--no-status] [--clear-after SEC] [--theme night|butter]
             [--settle N] [--output monitor|terminal]
    -> live.c finds and decodes the phrases the same as for caption and calls back here for each one
    -> emit decides which words are settled and hands the history and the live phrase to the display
    -> frame runs every 10 ms for the level meter and to clear the screen after a silence
    -> the display is the monitor through the framebuffer (display.c) or this terminal (term.c)
*/
#define _GNU_SOURCE
#include "display.h"
#include "live.h"
#include "phrase.h"
#include "settle.h"
#include "term.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int status = 1, theme = DISPLAY_BUTTER;
static double clear_after = 5; // seconds of silence before the screen clears -> 0 means never
static int settle;             // previews that must agree before a word settles -> 0 means just the previous preview
_Static_assert(SETTLE_TEXT == TEXT, "settle.h buffers match phrase.h");
static char captions[4096];    // finals before the live phrase for the history lines
static const char* label;      // the runner for the status strip
static long caption_at;        // the frame of the last caption

// where the captions go -> the same three calls for the monitor and the terminal
typedef struct {
    void (*show)(const char* history, const char* live, size_t stable);
    void (*status)(int speaking, const char* detail);
    void (*level)(double level);
} output;
static const output monitor = {display_show, display_status, display_level},
                    terminal = {term_show, term_status, term_level};
static const output* out = &monitor;

// status strip -> the speaking dot then the last decode's engine time and the caption delay
static void show_status(int speaking, double decode_ms, long waiting) {
    char line[96];
    if (!status)
        return;
    if (decode_ms > 0)
        snprintf(line, sizeof line, "%s  decode %.0f ms  delay %.0f ms", label, decode_ms, decode_ms + 10.0 * waiting);
    else
        snprintf(line, sizeof line, "%s", label);
    out->status(speaking, line);
}

// one caption out to the screen
static void emit(long t, const char* text, size_t kept, int final) {
    static char shown[TEXT], previous[TEXT];
    const char* heard = text;
    size_t stable = 0;
    (void)kept;
    // -> with --settle N a word settles once N previews in a row agree on it and then stays settled (settle.c)
    if (!final && settle) {
        stable = settle_preview(text, settle, shown);
        text = shown;
    }
    // -> with --settle 0 the words this preview shares with the previous one count as stable
    else
        for (size_t i = 0; !final && text[i] && text[i] == previous[i]; i++)
            if (text[i + 1] == ' ' || (!text[i + 1] && !previous[i + 1]))
                stable = i + 1;
    // -> the screen gets earlier finals dim then this phrase large with its stable words solid and the rest tentative
    // -> a final counts as all stable and stays on the live line until the next phrase moves it up
    out->show(captions, text, final ? strlen(text) : stable);
    if (final && *text) {
        size_t n = strlen(captions), m = strlen(text);
        if (n + m + 2 > sizeof captions) { // full so keep the newest half
            memmove(captions, captions + n / 2, n - n / 2 + 1);
            n = strlen(captions);
        }
        snprintf(captions + n, sizeof captions - n, "%s%s", n ? " " : "", text);
    }
    caption_at = t;
    // -> a final ends the phrase so the next preview starts with nothing settled
    strcpy(previous, final ? "" : heard);
    if (final)
        settle_reset();
}

// every 10 ms frame -> the level meter and clearing after a silence
static void frame(long t, int speaking) {
    static double loudest;
    // -> the meter shows the loudest of every 50 ms at 4 db a bar so two bars is about the speech threshold
    loudest = fmax(loudest, phrase_level());
    if (t % 5 == 4) {
        out->level(loudest / 28);
        loudest = 0;
    }
    // -> after clear_after seconds of silence the next phrase starts on an empty screen
    if (clear_after > 0 && !speaking && *captions && t - caption_at >= clear_after * 100) {
        captions[0] = 0;
        out->show("", "", 0);
    }
}

int main(int argc, char** argv) {
    // -> anything unknown sets argc to 0 so the usage line gets printed
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i], "--no-status"))
            status = 0;
        else if (!strcmp(argv[i], "--clear-after") && i + 1 < argc)
            clear_after = atof(argv[++i]);
        else if (!strcmp(argv[i], "--theme") && i + 1 < argc && !strcmp(argv[i + 1], "night")) {
            theme = DISPLAY_NIGHT;
            i++;
        }
        else if (!strcmp(argv[i], "--theme") && i + 1 < argc && !strcmp(argv[i + 1], "butter"))
            i++;
        else if (!strcmp(argv[i], "--settle") && i + 1 < argc)
            settle = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--output") && i + 1 < argc && !strcmp(argv[i + 1], "terminal")) {
            out = &terminal;
            i++;
        }
        else if (!strcmp(argv[i], "--output") && i + 1 < argc && !strcmp(argv[i + 1], "monitor"))
            i++;
        else
            argc = 0;
    }
    const runner* model = argc >= 4 ? runner_find(argv[1]) : NULL;
    if (!model) {
        fprintf(stderr, "usage: screen hybrid|cpu MODEL running_prior.json [--no-status] [--clear-after SEC] "
                        "[--theme night|butter] [--settle N] [--output monitor|terminal]\n");
        return 2;
    }
    // -> nothing to draw on means there is no point loading the model
    if (out == &terminal && term_open(status)) {
        fprintf(stderr, "screen: stdout is not a terminal; use caption to print captions\n");
        return 1;
    }
    if (out == &monitor && display_open(status, theme)) {
        fprintf(stderr, "screen: no framebuffer; captions are not drawn\n");
        return 1;
    }
    label = model == &hybrid_runner ? "fpga engine" : "cpu int8";
    show_status(0, 0, 0);
    return live_run(model, argv[2], argv[3], &(live_events){.caption = emit, .status = show_status, .frame = frame});
}
