#define _GNU_SOURCE
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define SAMPLES_PER_SEC (48000.0)

// Core utility functions and helpers
#include "util.h"
#include "lfo.h"
#include "effect.h"
#include "biquad.h"
#include "process.h"

// Effects
#include "flanger.h"
#include "echo.h"
#include "fm.h"
#include "am.h"
#include "phaser.h"
#include "discont.h"
#include "distortion.h"

static void magnitude_describe(float pot[4]) { fprintf(stderr, "\n"); }
static void magnitude_init(float pot[4]) {}
static float magnitude_step(float in) { return u32_to_fraction(magnitude); }

#define EFF(x) { #x, x##_describe, x##_init, x##_step }
struct effect {
	const char *name;
	void (*describe)(float[4]);
	void (*init)(float[4]);
	float (*step)(float);
} effects[] = {
	EFF(discont),
	EFF(distortion),
	EFF(echo),
	EFF(flanger),
	EFF(phaser),

	/* "Helper" effects */
	EFF(am),
	EFF(fm),
	EFF(magnitude),
};

#define UPDATE(x) x += 0.001 * (target_##x - x)

#define BLOCKSIZE 200
static inline int make_one_noise(int in, int out, struct effect *eff)
{
	s32 input[BLOCKSIZE], output[BLOCKSIZE];
	int nr = read(in, input, sizeof(input));
	if (nr <= 0)
		return nr;

	nr /= 4;
	for (int i = 0; i < nr; i++) {
		UPDATE(effect_delay);

		float val = process_input(input[i]);

		val = eff->step(val);

		output[i] = process_output(val);
	}
	write(out, output, nr * 4);
	return nr * 4;
}

int main(int argc, char **argv)
{
	float pot[4] = { 0.5, 0.5, 0.5, 0.5 };
	struct effect *eff = NULL;
	int input = -1, output = -1;
	int potnr = 0;

	for (int i = 1; i < argc; i++) {
		const char *arg = argv[i];
		char *endptr;

		// Is the argument a floating point number?
		// The we assume it's a default pot value
		float val = strtof(arg, &endptr);
		if (endptr != arg) {
			if (potnr < 4) {
				pot[potnr++] = val;
				continue;
			}
			fprintf(stderr, "Too many pot values\n");
			exit(1);
		}

		// Is it the name of an effect and we don't have one yet?
		if (!eff) {
			for (int i = 0; i < ARRAY_SIZE(effects); i++) {
				if (!strcmp(arg, effects[i].name))
					eff = effects+i;
			}
			if (eff)
				continue;
		}

		if (input < 0) {
			// We assume first filename is an input file
			if (!strcmp(arg, "-")) {
				input = 0;
				continue;
			}

			int fd = open(arg, O_RDONLY);
			if (fd < 0) {
				perror(arg);
				exit(1);
			}
			input = fd;
			continue;
		}

		if (output < 0) {
			// We assume second filename is an output file
			if (!strcmp(arg, "-")) {
				output = 1;
				continue;
			}

			int fd = open(arg, O_CREAT | O_WRONLY, 0666);
			if (fd < 0) {
				perror(arg);
				exit(1);
			}
			output = fd;
			continue;
		}

		fprintf(stderr, "Unrecognized option '%s'\n", arg);
		exit(1);
	}

	if (input < 0)
		input = 0;

	if (output < 0)
		output = 1;

#ifdef F_SETPIPE_SZ
	// Limit the output buffer size if we are
	// writing to a pipe. At least on Linux,
	// because I have no idea how to do it for
	// anything else
	fcntl(output, F_SETPIPE_SZ, 4096);
#endif

	fprintf(stderr, "Playing %s: ",	eff->name);
	eff->describe(pot);

	for (;;) {
		eff->init(pot);
		if (make_one_noise(input, output, eff) <= 0)
			break;
	}
	return 0;
}
