// SPDX-License-Identifier: GPL-3.0-or-later
#include "engine.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <unordered_map>
namespace iplug { inline constexpr double PI = std::numbers::pi_v<double>; }
#define DEFAULT_BLOCK_SIZE 1024
#include "dsp/ResamplingContainer/ResamplingContainer.h"
#include "activations.h"

namespace golem {
struct Capture::Resampling {
    ::dsp::ResamplingContainer<float, 1, 12> container{48000};
    std::function<void(float**, float**, int)> callback;
    bool active = false;
};
Capture::~Capture() = default;
Capture::Capture(const nlohmann::json& b) : bundle_(b), resampling_(std::make_unique<Resampling>()) {
    // La tanh rapide du cœur, comme le plugin NAM : std::tanh coûtait plus de la moitié du calcul, et l'écart
    // (−50 dB) reste sous l'erreur de la capture. Avant get_dsp : chaque couche fixe son activation au chargement.
    nam::activations::Activation::enable_fast_tanh();
    if (b.value("format", "") != "golem-capture-1" || !b.at("controls").is_array()
        || b.at("controls").size() > max_controls || b.at("stages").empty() || b.at("stages").size() > 8)
        throw std::runtime_error("Unsupported capture bundle");
    std::unordered_map<std::string, unsigned> indices;
    for (const auto& c : b.at("controls")) {
        Control ctl{c.at("id"), c.at("name"), c.value("min", 0.f), c.value("max", 1.f),
                    c.at("default"), c.value("kind", "knob") == "toggle"};
        if (ctl.id.empty() || indices.contains(ctl.id) || !std::isfinite(ctl.low) || !std::isfinite(ctl.high)
            || !std::isfinite(ctl.initial) || ctl.low >= ctl.high || ctl.initial < ctl.low || ctl.initial > ctl.high)
            throw std::runtime_error("Invalid capture control");
        indices.emplace(ctl.id, unsigned(controls_.size()));
        current_[controls_.size()] = ctl.initial;
        controls_.push_back(std::move(ctl));
    }
    for (const auto& s : b.at("stages")) {
        const auto& model = s.at("model");
        const std::string arch = model.at("architecture");
        if ((arch != "HyperWaveNet" && arch != "WaveNet") || model.at("weights").size() > 2000000
            || model.at("sample_rate").get<double>() != 48000.)
            throw std::runtime_error("Capture needs a supported 48 kHz NAM model");
        Stage stage;
        stage.model = nam::get_dsp(model, nam::DspLoadOptions{false});
        if (stage.model->NumInputChannels() != 1 || stage.model->NumOutputChannels() != 1)
            throw std::runtime_error("Capture models must be mono");
        stage.parametric = dynamic_cast<nam::IParametricControl*>(stage.model.get());
        for (const auto& id : s.at("controls")) stage.controls.push_back(indices.at(id.get<std::string>()));
        if (stage.controls.size() != size_t(stage.parametric ? stage.parametric->ParamDim() : 0))
            throw std::runtime_error("Capture control count does not match its model");
        stage.values.resize(stage.controls.size());
        if (s.contains("enable")) {
            stage.enable = int(indices.at(s.at("enable")));
            if (!controls_[stage.enable].toggle) throw std::runtime_error("Stage enable must be a toggle");
            stage.wet = current_[stage.enable] >= .5f ? 1.f : 0.f;
        }
        // Les plages annoncées ne doivent jamais sortir du domaine appris du modèle.
        if (stage.parametric) {
            const auto& specs = stage.parametric->GetParamSpecs();
            for (size_t i = 0; i < specs.size(); ++i) {
                const auto& c = controls_[stage.controls[i]];
                if (c.low < specs[i].min - 1e-6f || c.high > specs[i].max + 1e-6f || c.toggle)
                    throw std::runtime_error("Capture range exceeds the trained model range");
            }
        }
        stages_.push_back(std::move(stage));
    }
    resampling_->callback = [this](float** in, float** out, int n) { process_models(in, out, n); };
}
void Capture::reset(double rate, unsigned frames, bool prewarm) {
    if (!std::isfinite(rate) || rate < 8000 || rate > 192000 || !frames || frames > 65536)
        throw std::runtime_error("Invalid capture audio configuration");
    max_frames_ = frames;
    host_rate_ = rate;
    const unsigned inner = unsigned(std::ceil(frames * 48000. / rate)) + 128;
    scratch_a_.resize(inner); scratch_b_.resize(inner);
    for (auto& s : stages_) {
        s.model->SetPrewarmOnReset(prewarm);
        s.model->Reset(48000., int(inner));
        s.model->SetPrewarmOnReset(false);
    }
    resampling_->active = std::abs(rate - 48000.) > .5;
    if (resampling_->active) resampling_->container.Reset(rate, int(frames));
    first_ = true;
}
void Capture::process(float* input, float* output, unsigned n, std::span<const float> norm) {
    if (n > max_frames_ || norm.size() < controls_.size()) throw std::runtime_error("Invalid capture process block");
    for (size_t i = 0; i < controls_.size(); ++i) {
        const auto& c = controls_[i];
        float v = std::isfinite(norm[i]) ? std::clamp(norm[i], 0.f, 1.f) : (c.initial - c.low) / (c.high - c.low);
        if (c.toggle) v = v >= .5f ? 1.f : 0.f;
        const float target = c.low + v * (c.high - c.low);
        // Les potards convergent en douceur ; un réglage initial est exact dès le premier bloc.
        if (first_ || c.toggle || std::abs(target - current_[i]) < 1e-6f) current_[i] = target;
        else current_[i] += float(1. - std::exp(-double(n) / (.008 * host_rate_))) * (target - current_[i]);
    }
    float* in[] = {input}; float* out[] = {output};
    if (resampling_->active) resampling_->container.ProcessBlock(in, out, int(n), resampling_->callback);
    else process_models(in, out, int(n));
    first_ = false;
}
void Capture::process_models(float** input, float** output, int n) {
    std::copy_n(input[0], n, scratch_a_.data());
    for (auto& s : stages_) {
        if (s.parametric) {
            for (size_t i = 0; i < s.controls.size(); ++i) s.values[i] = current_[s.controls[i]];
            s.parametric->SetParams(s.values);
        }
        float* in[] = {scratch_a_.data()}; float* out[] = {scratch_b_.data()};
        s.model->process(in, out, n);
        const float target = s.enable < 0 || current_[s.enable] >= .5f ? 1.f : 0.f;
        if (first_) s.wet = target;
        // Huit millisecondes de fondu, sans couper le calcul : l'état d'une pédale reste chaud.
        for (int i = 0; i < n; ++i) {
            s.wet += std::clamp(target - s.wet, -1.f / 384.f, 1.f / 384.f);
            scratch_a_[i] += s.wet * (scratch_b_[i] - scratch_a_[i]);
        }
    }
    std::copy_n(scratch_a_.data(), n, output[0]);
}
}
