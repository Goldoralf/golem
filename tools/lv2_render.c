/* Rendu hors ligne d'un plugin LV2 audio MONO quelconque : un .wav en entrée, un .wav en sortie,
 * les potards réglés par index. Sert à CAPTURER un plugin (tools/capture-plugin.py) : le signal
 * d'entraînement NAM passe dans le plugin, la sortie part à l'entraîneur. Blocs de 128, 48 kHz.
 *
 *   lv2_render <plugin.so> <uri|-> <in.wav> <out.wav> --in N --out M [--ctl IDX=VAL]…
 *
 * Entrée : WAV mono PCM 16/24/32 ou float32, 48 kHz. Sortie : WAV mono PCM 24 bits (l'entraîneur NAM
 * le lit), la crête est imprimée — une sortie qui écrête ne s'entraîne pas.
 * Features fournies : urid:map, options (taille de bloc, fréquence) — de quoi charger la plupart des
 * plugins « effet » ; un plugin qui exige un worker ou un état (fichier à charger) n'est pas pour ici. */
#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <lv2/atom/atom.h>
#include <lv2/buf-size/buf-size.h>
#include <lv2/core/lv2.h>
#include <lv2/options/options.h>
#include <lv2/parameters/parameters.h>
#include <lv2/urid/urid.h>

#define NF 128
#define SR 48000
#define MAXP 64

static char* uris[512];
static int   n_uris;
static LV2_URID
map_uri (LV2_URID_Map_Handle h, const char* u)
{
	for (int i = 0; i < n_uris; ++i)
		if (!strcmp (uris[i], u)) return i + 1;
	uris[n_uris] = strdup (u);
	return ++n_uris;
}
static LV2_URID_Map map = { NULL, map_uri };

static float*
read_wav (const char* path, long* n)
{
	FILE* f = fopen (path, "rb");
	if (!f) { perror (path); exit (2); }
	unsigned char hdr[12];
	if (fread (hdr, 1, 12, f) != 12 || memcmp (hdr, "RIFF", 4) || memcmp (hdr + 8, "WAVE", 4)) { fprintf (stderr, "%s : pas un WAV\n", path); exit (2); }
	unsigned fmt = 0, ch = 0, rate = 0, bits = 0;
	for (;;) {
		char id[4]; uint32_t sz;
		if (fread (id, 1, 4, f) != 4 || fread (&sz, 4, 1, f) != 1) { fprintf (stderr, "%s : pas de données\n", path); exit (2); }
		if (!memcmp (id, "fmt ", 4)) {
			unsigned char b[64];
			if (sz > sizeof b || fread (b, 1, sz, f) != sz) { fprintf (stderr, "%s : fmt illisible\n", path); exit (2); }
			fmt = b[0] | b[1] << 8; ch = b[2] | b[3] << 8;
			rate = b[4] | b[5] << 8 | b[6] << 16 | (unsigned)b[7] << 24; bits = b[14] | b[15] << 8;
			if (fmt == 0xFFFE && sz >= 26) fmt = b[24] | b[25] << 8;
		} else if (!memcmp (id, "data", 4)) {
			if (ch != 1 || rate != SR) { fprintf (stderr, "%s : il faut du mono 48 kHz (%u ch, %u Hz)\n", path, ch, rate); exit (2); }
			int w = bits / 8;
			*n = sz / w;
			unsigned char* raw = malloc (sz);
			if (fread (raw, 1, sz, f) != sz) { fprintf (stderr, "%s : données tronquées\n", path); exit (2); }
			float* x = malloc (*n * sizeof (float));
			for (long i = 0; i < *n; ++i) {
				unsigned char* p = raw + i * w;
				if (fmt == 3 && bits == 32) memcpy (&x[i], p, 4);
				else if (bits == 16) x[i] = (int16_t) (p[0] | p[1] << 8) / 32768.f;
				else if (bits == 24) x[i] = ((int32_t) ((uint32_t)p[0] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 24) >> 8) / 8388608.f;
				else if (bits == 32) x[i] = (int32_t) (p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24) / 2147483648.f;
				else { fprintf (stderr, "%s : %u bits non lus\n", path, bits); exit (2); }
			}
			free (raw); fclose (f);
			return x;
		} else fseek (f, sz + (sz & 1), SEEK_CUR);
	}
}

static void
write_wav24 (const char* path, const float* x, long n)
{
	FILE* f = fopen (path, "wb");
	uint32_t d = n * 3, r = 36 + d, sz = 16, rate = SR, br = SR * 3;
	uint16_t fmt = 1, ch = 1, ba = 3, bits = 24;
	fwrite ("RIFF", 1, 4, f); fwrite (&r, 4, 1, f); fwrite ("WAVEfmt ", 1, 8, f); fwrite (&sz, 4, 1, f);
	fwrite (&fmt, 2, 1, f); fwrite (&ch, 2, 1, f); fwrite (&rate, 4, 1, f); fwrite (&br, 4, 1, f);
	fwrite (&ba, 2, 1, f); fwrite (&bits, 2, 1, f); fwrite ("data", 1, 4, f); fwrite (&d, 4, 1, f);
	for (long i = 0; i < n; ++i) {
		float v = x[i] > 1.f ? 1.f : x[i] < -1.f ? -1.f : x[i];
		int32_t s = (int32_t)lrintf (v * 8388607.f);
		unsigned char b[3] = { (unsigned char)s, (unsigned char)(s >> 8), (unsigned char)(s >> 16) };
		fwrite (b, 1, 3, f);
	}
	fclose (f);
}

int
main (int argc, char** argv)
{
	if (argc < 5) {
		fprintf (stderr, "usage : %s plugin.so uri|- in.wav out.wav --in N --out M [--ctl IDX=VAL]…\n", argv[0]);
		return 2;
	}
	int pin = -1, pout = -1, nctl = 0, cidx[MAXP];
	float cval[MAXP];
	for (int a = 5; a < argc; ++a) {
		if (!strcmp (argv[a], "--in") && a + 1 < argc) pin = atoi (argv[++a]);
		else if (!strcmp (argv[a], "--out") && a + 1 < argc) pout = atoi (argv[++a]);
		else if (!strcmp (argv[a], "--ctl") && a + 1 < argc && nctl < MAXP) {
			char* eq = strchr (argv[++a], '=');
			if (!eq) { fprintf (stderr, "--ctl IDX=VAL\n"); return 2; }
			cidx[nctl] = atoi (argv[a]); cval[nctl++] = (float)atof (eq + 1);
		}
	}
	if (pin < 0 || pout < 0) { fprintf (stderr, "--in et --out sont requis\n"); return 2; }

	void* lib = dlopen (argv[1], RTLD_NOW | RTLD_LOCAL);
	if (!lib) { fprintf (stderr, "%s\n", dlerror ()); return 2; }
	LV2_Descriptor_Function df = (LV2_Descriptor_Function)dlsym (lib, "lv2_descriptor");
	const LV2_Descriptor* d = NULL;
	for (uint32_t i = 0; (d = df (i)); ++i)
		if (!strcmp (argv[2], "-") || !strcmp (d->URI, argv[2])) break;
	if (!d) { fprintf (stderr, "plugin %s introuvable\n", argv[2]); return 2; }

	static int32_t           nf = NF;
	static float             sr = SR;
	const LV2_Options_Option opts[] = {
		{ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_BUF_SIZE__nominalBlockLength), 4, map_uri (0, LV2_ATOM__Int), &nf },
		{ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_BUF_SIZE__maxBlockLength), 4, map_uri (0, LV2_ATOM__Int), &nf },
		{ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_PARAMETERS__sampleRate), 4, map_uri (0, LV2_ATOM__Float), &sr },
		{ LV2_OPTIONS_INSTANCE, 0, 0, 0, 0, NULL } };
	const LV2_Feature  fm = { LV2_URID__map, &map }, fo = { LV2_OPTIONS__options, (void*)opts };
	const LV2_Feature* feats[] = { &fm, &fo, NULL };
	char bundle[1024];
	snprintf (bundle, sizeof bundle, "%s", argv[1]);
	char* slash = strrchr (bundle, '/');
	if (slash) slash[1] = 0;
	LV2_Handle h = d->instantiate (d, SR, bundle, feats);
	if (!h) { fprintf (stderr, "instantiate : échec (%s)\n", d->URI); return 2; }

	static float a_in[NF], a_out[NF], ctl[MAXP];
	d->connect_port (h, pin, a_in);
	d->connect_port (h, pout, a_out);
	for (int i = 0; i < nctl; ++i) {
		ctl[i] = cval[i];
		d->connect_port (h, cidx[i], &ctl[i]);
	}
	if (d->activate) d->activate (h);

	long n;
	float* in = read_wav (argv[3], &n);
	float* out = calloc (n, sizeof (float));
	/* 1 s de silence d'abord : les lissages internes des potards se posent avant le signal */
	long warm = SR, total = warm + n, pos = 0;
	float peak = 0;
	while (pos < total) {
		for (int i = 0; i < NF; ++i) {
			long k = pos + i - warm;
			a_in[i] = (k >= 0 && k < n) ? in[k] : 0.f;
		}
		d->run (h, NF);
		for (int i = 0; i < NF; ++i) {
			long k = pos + i - warm;
			if (k >= 0 && k < n) {
				out[k] = a_out[i];
				if (fabsf (a_out[i]) > peak) peak = fabsf (a_out[i]);
			}
		}
		pos += NF;
	}
	write_wav24 (argv[4], out, n);
	fprintf (stdout, "rendu : %ld échantillons, crête %.2f dBFS%s\n", n, 20 * log10f (peak + 1e-12f),
	         peak >= 1.f ? " — ÉCRÊTÉ" : "");
	if (d->deactivate) d->deactivate (h);
	d->cleanup (h);
	return 0;
}
