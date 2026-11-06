// SPDX-License-Identifier: GPL-3.0-or-later
#include "engine.h"
#include <clap/clap.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cstdlib>

namespace {
const char* features[] = {CLAP_PLUGIN_FEATURE_AUDIO_EFFECT, CLAP_PLUGIN_FEATURE_MONO, nullptr};
const clap_plugin_descriptor_t descriptor{CLAP_VERSION, "fm.golem.capture", "golem Capture", "golem",
    "https://github.com/Goldoralf/golem", "", "", "1.0.0", "Autonomous parametric NAM capture", features};
struct Plugin {
    clap_plugin_t api{};
    const clap_host_t* host;
    std::array<std::atomic<float>, golem::max_controls> values{};
    std::atomic<golem::Capture*> capture{nullptr};
    // Les anciens états restent possédés par le thread principal jusqu'à la désactivation.
    std::vector<std::unique_ptr<golem::Capture>> states;
    std::atomic<double> rate{48000};
    std::atomic<unsigned> frames{1024};
    std::atomic<bool> active{false};
    explicit Plugin(const clap_host_t* h) : host(h) {}
    static Plugin& self(const clap_plugin_t* p) { return *static_cast<Plugin*>(p->plugin_data); }
    void events(const clap_input_events_t* events) {
        if (!events) return;
        for (uint32_t i = 0; i < events->size(events); ++i) {
            const auto* event = events->get(events, i);
            if (event && event->space_id == CLAP_CORE_EVENT_SPACE_ID && event->type == CLAP_EVENT_PARAM_VALUE
                && event->size >= sizeof(clap_event_param_value_t)) {
                const auto* param = reinterpret_cast<const clap_event_param_value_t*>(event);
                if (param->param_id < golem::max_controls && std::isfinite(param->value))
                    values[param->param_id].store(std::clamp(float(param->value), 0.f, 1.f));
            }
        }
    }
};
bool CLAP_ABI init(const clap_plugin_t*) { return true; }
void CLAP_ABI destroy(const clap_plugin_t* p) { delete &Plugin::self(p); }
bool CLAP_ABI activate(const clap_plugin_t* p, double rate, uint32_t, uint32_t frames) {
    auto& s = Plugin::self(p);
    try {
        if (auto* c = s.capture.load()) c->reset(rate, frames);
        s.rate = rate; s.frames = frames; s.active = true;
        return true;
    } catch (...) { return false; }
}
void CLAP_ABI deactivate(const clap_plugin_t* p) {
    auto& s = Plugin::self(p); s.active = false;
    const auto* keep = s.capture.load();
    std::erase_if(s.states, [keep](const auto& c) { return c.get() != keep; });
}
bool CLAP_ABI start(const clap_plugin_t*) { return true; }
void CLAP_ABI stop(const clap_plugin_t*) {}
void CLAP_ABI reset(const clap_plugin_t* p) {
    auto& s = Plugin::self(p);
    // Appel audio : conserver les tailles déjà allouées, sans préchauffage de 0,5 s.
    if (auto* c = s.capture.load()) c->reset(s.rate.load(), s.frames.load(), false);
}
clap_process_status CLAP_ABI process(const clap_plugin_t* p, const clap_process_t* block) {
    auto& s = Plugin::self(p); s.events(block->in_events);
    if (block->audio_outputs_count != 1 || !block->audio_outputs[0].data32) return CLAP_PROCESS_ERROR;
    float* out = block->audio_outputs[0].data32[0];
    auto* c = s.capture.load();
    if (!c || block->audio_inputs_count != 1 || !block->audio_inputs[0].data32) {
        std::fill_n(out, block->frames_count, 0.f); return CLAP_PROCESS_CONTINUE;
    }
    std::array<float, golem::max_controls> v;
    for (size_t i = 0; i < v.size(); ++i) v[i] = s.values[i].load();
    try { c->process(block->audio_inputs[0].data32[0], out, block->frames_count, v); }
    catch (...) { std::fill_n(out, block->frames_count, 0.f); return CLAP_PROCESS_ERROR; }
    for (uint32_t i = 0; i < block->frames_count; ++i) if (!std::isfinite(out[i])) out[i] = 0;
    return CLAP_PROCESS_CONTINUE;
}
uint32_t CLAP_ABI count(const clap_plugin_t*) { return golem::max_controls; }
bool CLAP_ABI info(const clap_plugin_t* p, uint32_t i, clap_param_info_t* out) {
    if (i >= golem::max_controls) return false;
    *out = {}; out->id = i; out->flags = CLAP_PARAM_IS_AUTOMATABLE;
    std::snprintf(out->name, sizeof(out->name), "Control %02u", i + 1);
    out->min_value = 0; out->max_value = 1; out->default_value = .5;
    auto* c = Plugin::self(p).capture.load();
    if (c && i < c->controls().size()) {
        const auto& ctl = c->controls()[i];
        out->default_value = (ctl.initial - ctl.low) / (ctl.high - ctl.low);
    }
    return true;
}
bool CLAP_ABI value(const clap_plugin_t* p, clap_id i, double* out) {
    if (i >= golem::max_controls) return false;
    *out = Plugin::self(p).values[i].load(); return true;
}
bool CLAP_ABI to_text(const clap_plugin_t*, clap_id i, double value, char* out, uint32_t size) {
    if (i >= golem::max_controls) return false;
    std::snprintf(out, size, "%.2f%%", value * 100); return true;
}
bool CLAP_ABI from_text(const clap_plugin_t*, clap_id i, const char* text, double* out) {
    if (i >= golem::max_controls) return false;
    char* end; const double value = std::strtod(text, &end);
    if (end == text || !std::isfinite(value)) return false;
    *out = std::clamp(value / 100., 0., 1.); return true;
}
void CLAP_ABI flush(const clap_plugin_t* p, const clap_input_events_t* in, const clap_output_events_t*) { Plugin::self(p).events(in); }
const clap_plugin_params_t params{count, info, value, to_text, from_text, flush};
uint32_t CLAP_ABI port_count(const clap_plugin_t*, bool) { return 1; }
bool CLAP_ABI port_info(const clap_plugin_t*, uint32_t i, bool input, clap_audio_port_info_t* out) {
    if (i) return false;
    *out = {}; out->id = 0; out->flags = CLAP_AUDIO_PORT_IS_MAIN; out->channel_count = 1;
    out->port_type = CLAP_PORT_MONO; out->in_place_pair = 0;
    std::snprintf(out->name, sizeof(out->name), "%s", input ? "Input" : "Output"); return true;
}
const clap_plugin_audio_ports_t ports{port_count, port_info};
bool CLAP_ABI save(const clap_plugin_t* p, const clap_ostream_t* stream) {
    auto& s = Plugin::self(p);
    try {
        nlohmann::json state{{"values", nlohmann::json::array()}};
        if (auto* c = s.capture.load()) state["bundle"] = c->bundle();
        for (auto& v : s.values) state["values"].push_back(v.load());
        const auto data = state.dump(); size_t pos = 0;
        while (pos < data.size()) {
            auto n = stream->write(stream, data.data() + pos, data.size() - pos);
            if (n <= 0 || size_t(n) > data.size() - pos) return false;
            pos += size_t(n);
        }
        return true;
    } catch (...) { return false; }
}
bool CLAP_ABI load(const clap_plugin_t* p, const clap_istream_t* stream) {
    auto& s = Plugin::self(p);
    try {
        std::string data; char buf[8192];
        for (;;) {
            auto n = stream->read(stream, buf, sizeof(buf));
            if (n < 0 || n > int64_t(sizeof(buf))) return false;
            if (!n) break;
            if (data.size() + size_t(n) > 32 * 1024 * 1024) return false;
            data.append(buf, size_t(n));
        }
        auto state = nlohmann::json::parse(data);
        std::unique_ptr<golem::Capture> model;
        if (state.contains("bundle")) model = std::make_unique<golem::Capture>(state.at("bundle"));
        std::array<float, golem::max_controls> values{};
        if (model) {
            for (size_t i = 0; i < model->controls().size(); ++i) {
                const auto& c = model->controls()[i]; values[i] = (c.initial - c.low) / (c.high - c.low);
            }
            if (s.active) model->reset(s.rate.load(), s.frames.load());
        }
        if (state.contains("values")) {
            const auto& array = state.at("values");
            if (!array.is_array() || array.size() > values.size()) return false;
            for (size_t i = 0; i < array.size(); ++i) {
                values[i] = array[i].get<float>();
                if (!std::isfinite(values[i]) || values[i] < 0 || values[i] > 1) return false;
            }
        }
        auto* ptr = model.get();
        if (model) s.states.push_back(std::move(model));
        for (size_t i = 0; i < values.size(); ++i) s.values[i] = values[i];
        s.capture.store(ptr);
        // Nombre, ids, noms et plages restent fixes : aucun rescan structurel à chaud.
        return true;
    } catch (...) { return false; }
}
const clap_plugin_state_t state_ext{save, load};
const void* CLAP_ABI extension(const clap_plugin_t*, const char* id) {
    if (!std::strcmp(id, CLAP_EXT_PARAMS)) return &params;
    if (!std::strcmp(id, CLAP_EXT_AUDIO_PORTS)) return &ports;
    if (!std::strcmp(id, CLAP_EXT_STATE)) return &state_ext;
    return nullptr;
}
void CLAP_ABI on_main(const clap_plugin_t*) {}
uint32_t CLAP_ABI plugin_count(const clap_plugin_factory_t*) { return 1; }
const clap_plugin_descriptor_t* CLAP_ABI get_descriptor(const clap_plugin_factory_t*, uint32_t i) { return i ? nullptr : &descriptor; }
const clap_plugin_t* CLAP_ABI create(const clap_plugin_factory_t*, const clap_host_t* host, const char* id) {
    if (!clap_version_is_compatible(host->clap_version) || std::strcmp(id, descriptor.id)) return nullptr;
    auto* s = new Plugin(host);
    s->api = {&descriptor, s, init, destroy, activate, deactivate, start, stop, reset, process, extension, on_main};
    return &s->api;
}
const clap_plugin_factory_t factory{plugin_count, get_descriptor, create};
bool CLAP_ABI entry_init(const char*) { return true; }
void CLAP_ABI entry_deinit() {}
const void* CLAP_ABI get_factory(const char* id) { return std::strcmp(id, CLAP_PLUGIN_FACTORY_ID) ? nullptr : &factory; }
}
extern "C" CLAP_EXPORT const clap_plugin_entry_t clap_entry{CLAP_VERSION, entry_init, entry_deinit, get_factory};
