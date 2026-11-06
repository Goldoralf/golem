/* Rendu hors ligne de la chaîne cœur du rack Linux : NAM LV2 (Mike Oliphant) -> x42 zeroconvo
 * (CfgMono), exactement les binaires que Reaper charge, sans Reaper. Blocs de 128, 48 kHz.
 *
 *   core_render_lv2 MODE in.wav out.wav [model.nam] [ir.wav]
 *   MODE : amp (NAM seul) | ir (convolveur seul) | dual (NAM puis convolveur)
 * Entrée : WAV mono float32 48 kHz. Sortie : idem.
 * Plugins : $NAM_SO (défaut ~/.lv2/neural_amp_modeler.lv2/neural_amp_modeler.so),
 *           $ZC_SO  (défaut ~/.lv2/zeroconvo.lv2/zeroconvolv.so). */
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <lv2/atom/atom.h>
#include <lv2/atom/forge.h>
#include <lv2/buf-size/buf-size.h>
#include <lv2/core/lv2.h>
#include <lv2/options/options.h>
#include <lv2/parameters/parameters.h>
#include <lv2/patch/patch.h>
#include <lv2/state/state.h>
#include <lv2/urid/urid.h>
#include <lv2/worker/worker.h>

#define NF 128
#define SR 48000

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
static const char* unmap_uri (LV2_URID_Unmap_Handle h, LV2_URID u) { return u && u <= (LV2_URID)n_uris ? uris[u - 1] : NULL; }
static LV2_URID_Map   map   = { NULL, map_uri };
static LV2_URID_Unmap unmap = { NULL, unmap_uri };

/* worker synchrone, un par plugin : les travaux s'exécutent après run(), les réponses au run() suivant */
typedef struct { uint32_t size; void* data; } Msg;
typedef struct {
	const LV2_Descriptor*       d;
	LV2_Handle                  h;
	const LV2_Worker_Interface* w;
	Msg                         jobs[64], resps[64];
	int                         nj, nr;
	LV2_Worker_Schedule         sched;
} Plug;
static LV2_Worker_Status
sched_fn (LV2_Worker_Schedule_Handle hd, uint32_t size, const void* data)
{
	Plug* p = hd;
	p->jobs[p->nj].size = size;
	p->jobs[p->nj].data = malloc (size);
	memcpy (p->jobs[p->nj++].data, data, size);
	return LV2_WORKER_SUCCESS;
}
static LV2_Worker_Status
resp_fn (LV2_Worker_Respond_Handle hd, uint32_t size, const void* data)
{
	Plug* p = hd;
	p->resps[p->nr].size = size;
	p->resps[p->nr].data = malloc (size);
	memcpy (p->resps[p->nr++].data, data, size);
	return LV2_WORKER_SUCCESS;
}
static void
pump (Plug* p)
{
	for (int guard = 0; guard < 16 && (p->nj || p->nr); ++guard) {
		while (p->nj) {
			Msg m = p->jobs[0];
			memmove (p->jobs, p->jobs + 1, --p->nj * sizeof (Msg));
			p->w->work (p->h, resp_fn, p, m.size, m.data);
			free (m.data);
		}
		while (p->nr) {
			Msg m = p->resps[0];
			memmove (p->resps, p->resps + 1, --p->nr * sizeof (Msg));
			p->w->work_response (p->h, m.size, m.data);
			free (m.data);
		}
	}
}
static const LV2_Descriptor*
load (const char* so, const char* uri)
{
	void* lib = dlopen (so, RTLD_NOW | RTLD_LOCAL);
	if (!lib) { fprintf (stderr, "%s\n", dlerror ()); exit (2); }
	LV2_Descriptor_Function df = (LV2_Descriptor_Function)dlsym (lib, "lv2_descriptor");
	const LV2_Descriptor* d;
	for (uint32_t i = 0; (d = df (i)); ++i)
		if (!uri || !strcmp (d->URI, uri)) return d;
	fprintf (stderr, "descripteur %s introuvable dans %s\n", uri, so);
	exit (2);
}
static void
instantiate (Plug* p, const char* bundle)
{
	static int32_t           nf = NF, mx = NF;
	static float             sr = SR;
	static LV2_Options_Option opts[4];
	opts[0] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_BUF_SIZE__nominalBlockLength), 4, map_uri (0, LV2_ATOM__Int), &nf };
	opts[1] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_BUF_SIZE__maxBlockLength), 4, map_uri (0, LV2_ATOM__Int), &mx };
	opts[2] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, map_uri (0, LV2_PARAMETERS__sampleRate), 4, map_uri (0, LV2_ATOM__Float), &sr };
	opts[3] = (LV2_Options_Option){ LV2_OPTIONS_INSTANCE, 0, 0, 0, 0, NULL };
	p->sched = (LV2_Worker_Schedule){ p, sched_fn };
	const LV2_Feature fm = { LV2_URID__map, &map }, fu = { LV2_URID__unmap, &unmap },
	                  fs = { LV2_WORKER__schedule, &p->sched }, fo = { LV2_OPTIONS__options, opts };
	const LV2_Feature* f[] = { &fm, &fu, &fs, &fo, NULL };
	p->h = p->d->instantiate (p->d, SR, bundle, f);
	if (!p->h) { fprintf (stderr, "instantiate %s : échec\n", p->d->URI); exit (2); }
	p->w = p->d->extension_data (LV2_WORKER__interface);
}

/* --- WAV float32 mono ---------------------------------------------------------------- */
static float*
read_wav (const char* path, long* n)
{
	FILE* f = fopen (path, "rb");
	if (!f) { perror (path); exit (2); }
	char hdr[12]; if (fread (hdr, 1, 12, f) != 12) { fprintf (stderr, "%s : en-tête illisible\n", path); exit (2); }
	unsigned fmt = 0, ch = 0, rate = 0, bits = 0;
	for (;;) {
		char id[4]; uint32_t sz;
		if (fread (id, 1, 4, f) != 4 || fread (&sz, 4, 1, f) != 1) { fprintf (stderr, "pas de data\n"); exit (2); }
		if (!memcmp (id, "fmt ", 4)) {
			unsigned char b[64]; if (sz > sizeof b || fread (b, 1, sz, f) != sz) { fprintf (stderr, "%s : fmt illisible\n", path); exit (2); }
			fmt = b[0] | b[1] << 8; ch = b[2] | b[3] << 8; rate = b[4] | b[5] << 8 | b[6] << 16 | (unsigned)b[7] << 24; bits = b[14] | b[15] << 8;
		} else if (!memcmp (id, "data", 4)) {
			if ((fmt != 3 && fmt != 0xFFFE) || ch != 1 || rate != SR || bits != 32) { fprintf (stderr, "%s : il faut du float32 mono 48 kHz\n", path); exit (2); }
			*n = sz / 4;
			float* x = malloc (sz);
			if (fread (x, 4, *n, f) != (size_t)*n) { fprintf (stderr, "%s : données tronquées\n", path); exit (2); }
			fclose (f);
			return x;
		} else fseek (f, sz, SEEK_CUR);
	}
}
static void
write_wav (const char* path, const float* x, long n)
{
	FILE* f = fopen (path, "wb");
	uint32_t d = n * 4, r = 36 + d, sz = 16, rate = SR, br = SR * 4;
	uint16_t fmt = 3, ch = 1, ba = 4, bits = 32;
	fwrite ("RIFF", 1, 4, f); fwrite (&r, 4, 1, f); fwrite ("WAVEfmt ", 1, 8, f); fwrite (&sz, 4, 1, f);
	fwrite (&fmt, 2, 1, f); fwrite (&ch, 2, 1, f); fwrite (&rate, 4, 1, f); fwrite (&br, 4, 1, f);
	fwrite (&ba, 2, 1, f); fwrite (&bits, 2, 1, f); fwrite ("data", 1, 4, f); fwrite (&d, 4, 1, f);
	fwrite (x, 4, n, f);
	fclose (f);
}

/* --- restauration d'état du convolveur (comme Reaper : avec le scheduler du worker) ------ */
static const char* zc_ir_path;
static const void*
zc_retrieve (LV2_State_Handle h, uint32_t key, size_t* size, uint32_t* type, uint32_t* flags)
{
	if (key != map_uri (0, "http://gareus.org/oss/lv2/zeroconvolv#ir")) return NULL;
	*size = strlen (zc_ir_path) + 1; *type = map_uri (0, LV2_ATOM__Path); *flags = LV2_STATE_IS_POD;
	return zc_ir_path;
}
static char* abs_path (LV2_State_Map_Path_Handle h, const char* p) { return strdup (p); }

int
main (int argc, char** argv)
{
	if (argc < 4) { fprintf (stderr, "usage : %s amp|ir|dual in.wav out.wav [model.nam] [ir.wav]\n", argv[0]); return 2; }
	const char* mode = argv[1];
	int use_amp = strcmp (mode, "ir") != 0, use_ir = strcmp (mode, "amp") != 0;
	const char* model = argc > 4 ? argv[4] : NULL;
	const char* ir    = argc > 5 ? argv[5] : (strcmp (mode, "ir") == 0 ? argv[4] : NULL);
	if (use_amp && !model) { fprintf (stderr, "modèle manquant\n"); return 2; }
	if (use_ir && !ir) { fprintf (stderr, "IR manquante\n"); return 2; }

	char nam_so[1024], zc_so[1024];
	const char* home = getenv ("HOME");
	snprintf (nam_so, sizeof nam_so, "%s", getenv ("NAM_SO") ? getenv ("NAM_SO") : "");
	if (!*nam_so) snprintf (nam_so, sizeof nam_so, "%s/.lv2/neural_amp_modeler.lv2/neural_amp_modeler.so", home);
	snprintf (zc_so, sizeof zc_so, "%s", getenv ("ZC_SO") ? getenv ("ZC_SO") : "");
	if (!*zc_so) snprintf (zc_so, sizeof zc_so, "%s/.lv2/zeroconvo.lv2/zeroconvolv.so", home);

	long   n;
	float* in  = read_wav (argv[2], &n);
	float* out = calloc (n, 4);
	static float a_in[NF], a_mid[NF], a_out[NF];

	/* --- NAM --- */
	Plug  nam = { 0 };
	float n_inlvl = 0, n_outlvl = 0, n_quality = 1;
	static union { LV2_Atom_Sequence s; uint8_t b[8192]; } n_ctl, n_ntf;
	if (use_amp) {
		nam.d = load (nam_so, NULL);
		instantiate (&nam, "");
		nam.d->connect_port (nam.h, 0, &n_ctl);
		nam.d->connect_port (nam.h, 1, &n_ntf);
		nam.d->connect_port (nam.h, 2, a_in);
		nam.d->connect_port (nam.h, 3, a_mid);
		nam.d->connect_port (nam.h, 4, &n_inlvl);
		nam.d->connect_port (nam.h, 5, &n_outlvl);
		nam.d->connect_port (nam.h, 6, &n_quality);
		nam.d->activate (nam.h);
	}
	/* --- convolveur --- */
	Plug  zc = { 0 };
	float z_buf = 1, z_dry = -60, z_wet = 0, z_en = 1, z_lat = 0;
	static union { LV2_Atom_Sequence s; uint8_t b[8192]; } z_ctl, z_ntf;
	if (use_ir) {
		zc.d = load (zc_so, "http://gareus.org/oss/lv2/zeroconvolv#CfgMono");
		instantiate (&zc, "");
		zc.d->connect_port (zc.h, 0, &z_ctl);
		zc.d->connect_port (zc.h, 1, &z_ntf);
		zc.d->connect_port (zc.h, 2, &z_buf);
		zc.d->connect_port (zc.h, 3, &z_dry);
		zc.d->connect_port (zc.h, 4, &z_wet);
		zc.d->connect_port (zc.h, 5, &z_en);
		zc.d->connect_port (zc.h, 6, &z_lat);
		zc.d->connect_port (zc.h, 7, a_out);
		zc.d->connect_port (zc.h, 8, use_amp ? a_mid : a_in);
		zc.d->activate (zc.h);
		const LV2_State_Interface* st = zc.d->extension_data (LV2_STATE__interface);
		LV2_State_Map_Path mp = { NULL, abs_path, abs_path };
		const LV2_Feature  fp = { LV2_STATE__mapPath, &mp }, fs = { LV2_WORKER__schedule, &zc.sched };
		const LV2_Feature* f[] = { &fp, &fs, NULL };
		zc_ir_path = ir;
		st->restore (zc.h, zc_retrieve, NULL, 0, f);
	}

	LV2_URID seq_t = map_uri (0, LV2_ATOM__Sequence);
	int      model_sent = 0;
	/* 2 s de silence pour laisser charger modèle et IR, puis le signal */
	long warm = 2 * SR, total = warm + n, pos = 0, lat = 0;
	while (pos < total) {
		for (int i = 0; i < NF; ++i) {
			long k = pos + i - warm;
			a_in[i] = (k >= 0 && k < n) ? in[k] : 0.f;
		}
		if (use_amp) {
			LV2_Atom_Forge forge;
			lv2_atom_forge_init (&forge, &map);
			lv2_atom_forge_set_buffer (&forge, n_ctl.b, sizeof n_ctl.b);
			LV2_Atom_Forge_Frame seq;
			lv2_atom_forge_sequence_head (&forge, &seq, 0);
			if (!model_sent) {
				LV2_Atom_Forge_Frame obj;
				lv2_atom_forge_frame_time (&forge, 0);
				lv2_atom_forge_object (&forge, &obj, 0, map_uri (0, LV2_PATCH__Set));
				lv2_atom_forge_key (&forge, map_uri (0, LV2_PATCH__property));
				lv2_atom_forge_urid (&forge, map_uri (0, "http://github.com/mikeoliphant/neural-amp-modeler-lv2#model"));
				lv2_atom_forge_key (&forge, map_uri (0, LV2_PATCH__value));
				lv2_atom_forge_path (&forge, model, strlen (model) + 1);
				lv2_atom_forge_pop (&forge, &obj);
				model_sent = 1;
			}
			lv2_atom_forge_pop (&forge, &seq);
			n_ntf.s.atom.size = sizeof n_ntf.b - sizeof (LV2_Atom);
			n_ntf.s.atom.type = seq_t;
			nam.d->run (nam.h, NF);
			pump (&nam);
		} else {
			memcpy (a_mid, a_in, sizeof a_in);
		}
		if (use_ir) {
			z_ctl.s.atom.size = sizeof (LV2_Atom_Sequence_Body);
			z_ctl.s.atom.type = seq_t;
			z_ntf.s.atom.size = sizeof z_ntf.b - sizeof (LV2_Atom);
			z_ntf.s.atom.type = seq_t;
			zc.d->run (zc.h, NF);
			pump (&zc);
			lat = (long)z_lat;
		}
		const float* res = use_ir ? a_out : a_mid;
		for (int i = 0; i < NF; ++i) {
			long k = pos + i - warm - lat;   /* la latence déclarée est retirée ici */
			if (k >= 0 && k < n) out[k] = res[i];
		}
		pos += NF;
	}
	/* la queue de latence */
	write_wav (argv[3], out, n);
	fprintf (stderr, "rendu %s : %ld échantillons, latence convolveur %ld\n", mode, n, lat);
	if (use_amp) nam.d->cleanup (nam.h);
	if (use_ir) zc.d->cleanup (zc.h);
	return 0;
}
