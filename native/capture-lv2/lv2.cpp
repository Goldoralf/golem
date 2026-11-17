// SPDX-License-Identifier: GPL-3.0-or-later
// golem Capture en LV2 : le lecteur de native/capture (golem::Capture) pour un hôte LV2 — le Golem Engine.
// Un port audio mono en entrée et en sortie, 32 contrôles normalisés (les mêmes emplacements que le CLAP), et la
// capture donnée comme un FICHIER (patch:Set de <…#bundle>) : le JSON {"bundle": …} que le compileur de golem range
// dans assets/.cache/capture-modules. Le fichier est lu et le modèle construit dans le fil du worker, jamais dans le
// fil audio ; l'ancien modèle y retourne pour être détruit.
#include "engine.h"
#include <lv2/atom/atom.h>
#include <lv2/atom/forge.h>
#include <lv2/atom/util.h>
#include <lv2/core/lv2.h>
#include <lv2/patch/patch.h>
#include <lv2/state/state.h>
#include <lv2/urid/urid.h>
#include <lv2/worker/worker.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <sstream>

#define GOLEM_CAPTURE_URI "https://golem.fm/lv2/capture"

namespace {
enum { P_CONTROL, P_NOTIFY, P_IN, P_OUT, P_FIRST };
enum class Job : uint32_t { load, drop };
struct Msg { Job job; golem::Capture* capture; char path[1024]; };

struct Plugin {
    LV2_URID_Map* map = nullptr;
    LV2_Worker_Schedule* schedule = nullptr;
    LV2_Atom_Forge forge{};
    LV2_URID bundle, atom_path, patch_set, patch_get, patch_property, patch_value;
    const LV2_Atom_Sequence* control = nullptr;
    LV2_Atom_Sequence* notify = nullptr;
    const float* in = nullptr;
    float* out = nullptr;
    const float* knobs[golem::max_controls] = {};
    golem::Capture* capture = nullptr;      // possédé par le fil audio ; échangé dans work_response
    char path[1024] = "";
    bool announce = false;
    double rate = 48000;
};

LV2_Handle instantiate(const LV2_Descriptor*, double rate, const char*, const LV2_Feature* const* features) {
    auto* s = new Plugin();
    s->rate = rate;
    for (int i = 0; features[i]; ++i) {
        if (!std::strcmp(features[i]->URI, LV2_URID__map)) s->map = static_cast<LV2_URID_Map*>(features[i]->data);
        else if (!std::strcmp(features[i]->URI, LV2_WORKER__schedule)) s->schedule = static_cast<LV2_Worker_Schedule*>(features[i]->data);
    }
    if (!s->map || !s->schedule) { delete s; return nullptr; }
    auto id = [s](const char* uri) { return s->map->map(s->map->handle, uri); };
    s->bundle = id(GOLEM_CAPTURE_URI "#bundle");
    s->atom_path = id(LV2_ATOM__Path);
    s->patch_set = id(LV2_PATCH__Set); s->patch_get = id(LV2_PATCH__Get);
    s->patch_property = id(LV2_PATCH__property); s->patch_value = id(LV2_PATCH__value);
    lv2_atom_forge_init(&s->forge, s->map);
    return s;
}

void connect_port(LV2_Handle h, uint32_t port, void* data) {
    auto* s = static_cast<Plugin*>(h);
    if (port == P_CONTROL) s->control = static_cast<const LV2_Atom_Sequence*>(data);
    else if (port == P_NOTIFY) s->notify = static_cast<LV2_Atom_Sequence*>(data);
    else if (port == P_IN) s->in = static_cast<const float*>(data);
    else if (port == P_OUT) s->out = static_cast<float*>(data);
    else if (port < P_FIRST + golem::max_controls) s->knobs[port - P_FIRST] = static_cast<const float*>(data);
}

// le fil du worker : lire le fichier, construire le modèle (ou détruire l'ancien)
LV2_Worker_Status work(LV2_Handle h, LV2_Worker_Respond_Function respond, LV2_Worker_Respond_Handle handle, uint32_t, const void* data) {
    auto* s = static_cast<Plugin*>(h);
    const auto* msg = static_cast<const Msg*>(data);
    if (msg->job == Job::drop) { delete msg->capture; return LV2_WORKER_SUCCESS; }
    Msg reply{Job::load, nullptr, {}};
    std::snprintf(reply.path, sizeof(reply.path), "%s", msg->path);
    try {
        std::ifstream file(msg->path, std::ios::binary);
        if (!file) return LV2_WORKER_ERR_UNKNOWN;
        std::stringstream text; text << file.rdbuf();
        auto state = nlohmann::json::parse(text.str());
        auto model = std::make_unique<golem::Capture>(state.contains("bundle") ? state.at("bundle") : state);
        model->reset(s->rate, 8192);
        reply.capture = model.release();
    } catch (...) { return LV2_WORKER_ERR_UNKNOWN; }
    respond(handle, sizeof(reply), &reply);
    return LV2_WORKER_SUCCESS;
}

// le fil audio : le modèle prêt prend la place, l'ancien repart au worker
LV2_Worker_Status work_response(LV2_Handle h, uint32_t, const void* data) {
    auto* s = static_cast<Plugin*>(h);
    const auto* msg = static_cast<const Msg*>(data);
    Msg old{Job::drop, s->capture, {}};
    s->capture = msg->capture;
    std::snprintf(s->path, sizeof(s->path), "%s", msg->path);
    s->announce = true;
    if (old.capture) s->schedule->schedule_work(s->schedule->handle, sizeof(old), &old);
    return LV2_WORKER_SUCCESS;
}

void say_path(Plugin* s) {                       // « voici la capture chargée » : l'hôte y lit que le fichier est en place
    LV2_Atom_Forge_Frame frame;
    lv2_atom_forge_frame_time(&s->forge, 0);
    lv2_atom_forge_object(&s->forge, &frame, 0, s->patch_set);
    lv2_atom_forge_key(&s->forge, s->patch_property); lv2_atom_forge_urid(&s->forge, s->bundle);
    lv2_atom_forge_key(&s->forge, s->patch_value); lv2_atom_forge_path(&s->forge, s->path, uint32_t(std::strlen(s->path)));
    lv2_atom_forge_pop(&s->forge, &frame);
}

void run(LV2_Handle h, uint32_t frames) {
    auto* s = static_cast<Plugin*>(h);
    const uint32_t space = s->notify->atom.size;
    lv2_atom_forge_set_buffer(&s->forge, reinterpret_cast<uint8_t*>(s->notify), space);
    LV2_Atom_Forge_Frame seq;
    lv2_atom_forge_sequence_head(&s->forge, &seq, 0);
    LV2_ATOM_SEQUENCE_FOREACH (s->control, ev) {
        if (!lv2_atom_forge_is_object_type(&s->forge, ev->body.type)) continue;
        const auto* obj = reinterpret_cast<const LV2_Atom_Object*>(&ev->body);
        if (obj->body.otype == s->patch_get) { s->announce = true; continue; }
        if (obj->body.otype != s->patch_set) continue;
        const LV2_Atom *property = nullptr, *value = nullptr;
        lv2_atom_object_get(obj, s->patch_property, &property, s->patch_value, &value, 0);
        if (!property || !value || property->type != s->forge.URID || value->type != s->atom_path) continue;
        if (reinterpret_cast<const LV2_Atom_URID*>(property)->body != s->bundle) continue;
        Msg msg{Job::load, nullptr, {}};
        const uint32_t n = std::min<uint32_t>(value->size, sizeof(msg.path) - 1);
        std::memcpy(msg.path, LV2_ATOM_BODY_CONST(value), n); msg.path[n] = 0;
        s->schedule->schedule_work(s->schedule->handle, sizeof(msg), &msg);
    }
    if (s->announce && s->path[0]) { say_path(s); s->announce = false; }
    lv2_atom_forge_pop(&s->forge, &seq);
    if (!s->capture) { std::fill_n(s->out, frames, 0.f); return; }   // sans capture : le silence, comme le lecteur CLAP
    std::array<float, golem::max_controls> v;
    for (unsigned i = 0; i < golem::max_controls; ++i) {
        const float x = s->knobs[i] ? *s->knobs[i] : .5f;
        v[i] = std::isfinite(x) ? std::clamp(x, 0.f, 1.f) : .5f;
    }
    uint32_t done = 0;
    try {
        while (done < frames) {                  // le modèle est préparé pour 8192 échantillons par appel
            const uint32_t n = std::min<uint32_t>(frames - done, 8192);
            s->capture->process(const_cast<float*>(s->in) + done, s->out + done, n, v);
            done += n;
        }
    } catch (...) { std::fill_n(s->out + done, frames - done, 0.f); }
    for (uint32_t i = 0; i < frames; ++i) if (!std::isfinite(s->out[i])) s->out[i] = 0;
}

void cleanup(LV2_Handle h) { auto* s = static_cast<Plugin*>(h); delete s->capture; delete s; }

// l'état : le chemin de la capture (golem le repose de toute façon à chaque rappel)
LV2_State_Status save(LV2_Handle h, LV2_State_Store_Function store, LV2_State_Handle handle, uint32_t, const LV2_Feature* const*) {
    auto* s = static_cast<Plugin*>(h);
    if (!s->path[0]) return LV2_STATE_SUCCESS;
    return store(handle, s->bundle, s->path, std::strlen(s->path) + 1, s->atom_path, LV2_STATE_IS_POD);
}
LV2_State_Status restore(LV2_Handle h, LV2_State_Retrieve_Function retrieve, LV2_State_Handle handle, uint32_t, const LV2_Feature* const*) {
    auto* s = static_cast<Plugin*>(h);
    size_t size = 0; uint32_t type = 0, flags = 0;
    const void* value = retrieve(handle, s->bundle, &size, &type, &flags);
    if (!value || type != s->atom_path || !size) return LV2_STATE_SUCCESS;
    Msg msg{Job::load, nullptr, {}};
    std::snprintf(msg.path, sizeof(msg.path), "%s", static_cast<const char*>(value));
    s->schedule->schedule_work(s->schedule->handle, sizeof(msg), &msg);
    return LV2_STATE_SUCCESS;
}

const void* extension_data(const char* uri) {
    static const LV2_Worker_Interface worker{work, work_response, nullptr};
    static const LV2_State_Interface state{save, restore};
    if (!std::strcmp(uri, LV2_WORKER__interface)) return &worker;
    if (!std::strcmp(uri, LV2_STATE__interface)) return &state;
    return nullptr;
}

const LV2_Descriptor descriptor{GOLEM_CAPTURE_URI, instantiate, connect_port, nullptr, run, nullptr, cleanup, extension_data};
}

extern "C" __attribute__((visibility("default"))) const LV2_Descriptor* lv2_descriptor(uint32_t index) {
    return index ? nullptr : &descriptor;
}
