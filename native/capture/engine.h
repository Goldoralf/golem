// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <functional>
#include <memory>
#include <span>
#include <string>
#include <vector>
#include "get_dsp.h"
#include "parametric_control.h"

namespace golem {
constexpr unsigned max_controls = 32;
struct Control { std::string id, name; float low, high, initial; bool toggle; };
class Capture {
public:
    explicit Capture(const nlohmann::json& bundle);
    ~Capture();
    void reset(double sample_rate, unsigned max_frames, bool prewarm = true);
    void process(float* input, float* output, unsigned frames, std::span<const float> normalized);
    const std::vector<Control>& controls() const { return controls_; }
    const nlohmann::json& bundle() const { return bundle_; }
private:
    struct Stage {
        std::unique_ptr<nam::DSP> model;
        nam::IParametricControl* parametric;
        std::vector<unsigned> controls;
        std::vector<float> values;
        int enable = -1;
        float wet = 1;
    };
    struct Resampling;
    void process_models(float** input, float** output, int frames);
    nlohmann::json bundle_;
    std::vector<Control> controls_;
    std::vector<Stage> stages_;
    std::array<float, max_controls> current_{};
    std::vector<float> scratch_a_, scratch_b_;
    std::unique_ptr<Resampling> resampling_;
    unsigned max_frames_ = 0;
    double host_rate_ = 48000;
    bool first_ = true;
};
}
