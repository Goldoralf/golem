/* Minimal LV2 host reproducing a zeroconvo.lv2 lifetime bug: two state restores
 * in quick succession on a freshly instantiated plugin.
 *
 *   cc -O1 -g -fsanitize=address -pthread zc-double-restore.c -o zc-double-restore -ldl
 *   ./zc-double-restore /path/to/zeroconvolv.so a.wav b.wav [seq|threads] [iterations]
 *
 * seq     : deterministic, single thread. Restores A then B, then reads back the IR with
 *           save(). Expected "B", observed "A": the IR of the second restore is discarded.
 * threads : worker thread + "audio" thread calling run() every 2.7 ms, like a real host.
 *           Same two restores, repeated on fresh instances. Use an ASan build of the plugin.
 */
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <lv2/atom/atom.h>
#include <lv2/buf-size/buf-size.h>
#include <lv2/core/lv2.h>
#include <lv2/options/options.h>
#include <lv2/state/state.h>
#include <lv2/urid/urid.h>
#include <lv2/worker/worker.h>

#define URI_CFGMONO "http://gareus.org/oss/lv2/zeroconvolv#CfgMono"
#define URI_IR "http://gareus.org/oss/lv2/zeroconvolv#ir"
#define NFRAMES 128

/* ---- urid:map ---------------------------------------------------------------------- */
static char*           uris[256];
static int             n_uris;
static pthread_mutex_t uri_lock = PTHREAD_MUTEX_INITIALIZER;
static LV2_URID
map_uri (LV2_URID_Map_Handle h, const char* uri)
{
	pthread_mutex_lock (&uri_lock);
	for (int i = 0; i < n_uris; ++i) {
		if (!strcmp (uris[i], uri)) {
			pthread_mutex_unlock (&uri_lock);
			return i + 1;
		}
	}
	uris[n_uris] = strdup (uri);
	LV2_URID r   = ++n_uris;
	pthread_mutex_unlock (&uri_lock);
	return r;
}
static LV2_URID_Map map = { NULL, map_uri };

/* ---- worker: a FIFO of jobs, a FIFO of responses (both under one lock) ------------- */
typedef struct { uint32_t size; void* data; } Msg;
static Msg             jobs[64], resps[64];
static int             n_jobs, n_resps;
static pthread_mutex_t q_lock = PTHREAD_MUTEX_INITIALIZER;

static void
push (Msg* q, int* n, uint32_t size, const void* data)
{
	pthread_mutex_lock (&q_lock);
	q[*n].size = size;
	q[*n].data = malloc (size);
	memcpy (q[*n].data, data, size);
	++*n;
	pthread_mutex_unlock (&q_lock);
}
static int
pop (Msg* q, int* n, Msg* out)
{
	pthread_mutex_lock (&q_lock);
	if (*n == 0) {
		pthread_mutex_unlock (&q_lock);
		return 0;
	}
	*out = q[0];
	memmove (q, q + 1, (*n - 1) * sizeof (Msg));
	--*n;
	pthread_mutex_unlock (&q_lock);
	return 1;
}
static LV2_Worker_Status
schedule_work (LV2_Worker_Schedule_Handle h, uint32_t size, const void* data)
{
	push (jobs, &n_jobs, size, data);
	return LV2_WORKER_SUCCESS;
}
static LV2_Worker_Status
respond (LV2_Worker_Respond_Handle h, uint32_t size, const void* data)
{
	push (resps, &n_resps, size, data);
	return LV2_WORKER_SUCCESS;
}
static LV2_Worker_Schedule sched = { NULL, schedule_work };

/* ---- the plugin ---------------------------------------------------------------------- */
static const LV2_Descriptor*       desc;
static const LV2_Worker_Interface* worker;
static const LV2_State_Interface*  state;
static LV2_Handle                  inst;

static float in[NFRAMES], out[NFRAMES], latency, ctl[4] = { 0, 0, 0, 1 }; /* buffered off, dry 0 dB?, wet, enable */
static union { LV2_Atom_Sequence seq; uint8_t buf[4096]; } control, notify;

static int
work_one (void)
{
	Msg m;
	if (!pop (jobs, &n_jobs, &m)) {
		return 0;
	}
	worker->work (inst, respond, NULL, m.size, m.data);
	free (m.data);
	return 1;
}
static void
run_cycle (void)
{
	control.seq.atom.size = sizeof (LV2_Atom_Sequence_Body);
	control.seq.atom.type = map_uri (NULL, LV2_ATOM__Sequence);
	notify.seq.atom.size  = sizeof (notify) - sizeof (LV2_Atom);
	desc->run (inst, NFRAMES);
	Msg m; /* like jalv: responses are delivered right after run() */
	while (pop (resps, &n_resps, &m)) {
		worker->work_response (inst, m.size, m.data);
		free (m.data);
	}
}

/* ---- state ----------------------------------------------------------------------------- */
static const char* ir_to_restore;
static const void*
retrieve (LV2_State_Handle h, uint32_t key, size_t* size, uint32_t* type, uint32_t* flags)
{
	if (key != map_uri (NULL, URI_IR)) {
		return NULL;
	}
	*size  = strlen (ir_to_restore) + 1;
	*type  = map_uri (NULL, LV2_ATOM__Path);
	*flags = LV2_STATE_IS_POD | LV2_STATE_IS_PORTABLE;
	return ir_to_restore;
}
static char saved_ir[1024];
static LV2_State_Status
store (LV2_State_Handle h, uint32_t key, const void* value, size_t size, uint32_t type, uint32_t flags)
{
	if (key == map_uri (NULL, URI_IR)) {
		snprintf (saved_ir, sizeof (saved_ir), "%s", (const char*)value);
	}
	return LV2_STATE_SUCCESS;
}
static char* abs_path (LV2_State_Map_Path_Handle h, const char* p) { return strdup (p); }
static LV2_State_Map_Path map_path = { NULL, abs_path, abs_path };

static void
restore (const char* ir)
{
	const LV2_Feature f_path  = { LV2_STATE__mapPath, &map_path };
	const LV2_Feature f_sched = { LV2_WORKER__schedule, &sched }; /* state:threadSafeRestore */
	const LV2_Feature* feats[] = { &f_path, &f_sched, NULL };
	ir_to_restore              = ir;
	state->restore (inst, retrieve, NULL, 0, feats);
}
static const char*
current_ir (void)
{
	const LV2_Feature  f_path  = { LV2_STATE__mapPath, &map_path };
	const LV2_Feature* feats[] = { &f_path, NULL };
	saved_ir[0]                = 0;
	state->save (inst, store, NULL, 0, feats);
	return saved_ir;
}

static void
new_instance (void)
{
	static int32_t           nominal = NFRAMES;
	const LV2_Options_Option opts[]  = {
                { LV2_OPTIONS_INSTANCE, 0, map_uri (NULL, LV2_BUF_SIZE__nominalBlockLength), sizeof (int32_t), map_uri (NULL, LV2_ATOM__Int), &nominal },
                { LV2_OPTIONS_INSTANCE, 0, 0, 0, 0, NULL } };
	const LV2_Feature  f_map   = { LV2_URID__map, &map };
	const LV2_Feature  f_sched = { LV2_WORKER__schedule, &sched };
	const LV2_Feature  f_opts  = { LV2_OPTIONS__options, (void*)opts };
	const LV2_Feature* feats[] = { &f_map, &f_sched, &f_opts, NULL };

	inst = desc->instantiate (desc, 48000, "", feats);
	if (!inst) {
		fprintf (stderr, "instantiate failed\n");
		exit (2);
	}
	desc->connect_port (inst, 0, &control);
	desc->connect_port (inst, 1, &notify);
	for (int i = 0; i < 4; ++i) {
		desc->connect_port (inst, 2 + i, &ctl[i]);
	}
	desc->connect_port (inst, 6, &latency);
	desc->connect_port (inst, 7, out);
	desc->connect_port (inst, 8, in);
	desc->activate (inst);
}

/* ---- threaded mode ---------------------------------------------------------------------- */
static volatile int stop_threads;
static void*
audio_thread (void* arg)
{
	while (!stop_threads) {
		run_cycle ();
		usleep (2667); /* 128 frames @ 48 kHz */
	}
	return NULL;
}
static void*
worker_thread (void* arg)
{
	while (!stop_threads) {
		if (!work_one ()) {
			usleep (200);
		}
	}
	return NULL;
}

int
main (int argc, char** argv)
{
	if (argc < 4) {
		fprintf (stderr, "usage: %s zeroconvolv.so a.wav b.wav [seq|threads] [iterations]\n", argv[0]);
		return 2;
	}
	void* lib = dlopen (argv[1], RTLD_NOW);
	if (!lib) {
		fprintf (stderr, "%s\n", dlerror ());
		return 2;
	}
	LV2_Descriptor_Function df = (LV2_Descriptor_Function)dlsym (lib, "lv2_descriptor");
	for (uint32_t i = 0; (desc = df (i)); ++i) {
		if (!strcmp (desc->URI, URI_CFGMONO)) {
			break;
		}
	}
	worker = (const LV2_Worker_Interface*)desc->extension_data (LV2_WORKER__interface);
	state  = (const LV2_State_Interface*)desc->extension_data (LV2_STATE__interface);

	const char* mode  = argc > 4 ? argv[4] : "seq";
	int         iters = argc > 5 ? atoi (argv[5]) : 1;

	if (!strcmp (mode, "seq")) {
		new_instance ();
		restore (argv[2]);      /* schedules LOAD A                              */
		work_one ();            /* worker: A loaded into clv_offline, SWAP queued */
		restore (argv[3]);      /* schedules LOAD B (worker is idle)              */
		run_cycle ();           /* SWAP: A goes online; nothing to retire; FREE   */
		while (work_one ()) {   /* worker: LOAD B -> clv_offline = B, SWAP queued */
		}                       /*         FREE   -> deletes clv_offline (= B)    */
		for (int i = 0; i < 4; ++i) {
			run_cycle ();
			while (work_one ()) {
			}
		}
		printf ("restored A then B, plugin now holds: %s\n", current_ir ());
		int ok = strcmp (saved_ir, argv[3]) == 0;
		printf ("%s\n", ok ? "OK (B)" : "BUG: the second restore was discarded");
		desc->cleanup (inst);
		return ok ? 0 : 1;
	}

	int wrong = 0;
	for (int it = 0; it < iters; ++it) {
		pthread_t a, w;
		stop_threads = 0;
		new_instance ();
		pthread_create (&w, NULL, worker_thread, NULL);
		pthread_create (&a, NULL, audio_thread, NULL);
		restore (argv[2]);
		usleep (30000 + (rand () % 30000)); /* roughly one IR load later */
		restore (argv[3]);
		usleep (300000);
		stop_threads = 1;
		pthread_join (a, NULL);
		pthread_join (w, NULL);
		if (strcmp (current_ir (), argv[3])) {
			++wrong;
		}
		desc->cleanup (inst);
		n_jobs = n_resps = 0;
	}
	printf ("%d iterations, %d ended with the wrong IR (A instead of B)\n", iters, wrong);
	return 0;
}
