// SPDX-License-Identifier: GPL-3.0-or-later
// Banc hors ligne : float32 mono entrée/sortie, aucun périphérique audio.
#include "engine.h"
#include <chrono>
#include <fstream>
#include <iostream>
int main(int argc, char** argv) {
    if (argc != 7) { std::cerr << "capture_render bundle.json input.f32 output.f32 values.json rate block\n"; return 2; }
    try {
        std::ifstream file(argv[1]); nlohmann::json bundle; file >> bundle;
        std::ifstream vf(argv[4]); nlohmann::json values; vf >> values;
        golem::Capture model(bundle);
        const unsigned block = unsigned(std::stoul(argv[6])); const double rate = std::stod(argv[5]);
        model.reset(rate, block);
        std::array<float, golem::max_controls> v{};
        auto set_values = [&](const nlohmann::json& settings, bool initial) {
            for (size_t i = 0; i < model.controls().size(); ++i) {
                const auto& c = model.controls()[i];
                if (!initial && !settings.contains(c.id)) continue;
                float value = settings.value(c.id, c.initial);
                if (!std::isfinite(value) || value < c.low || value > c.high || (c.toggle && value != 0 && value != 1))
                    throw std::runtime_error("Control out of range");
                v[i] = (value - c.low) / (c.high - c.low);
            }
        };
        set_values(values, true);
        auto events = values.value("events", nlohmann::json::array());
        size_t event_index = 0;
        std::ifstream in(argv[2], std::ios::binary); std::ofstream out(argv[3], std::ios::binary);
        if (!in || !out) throw std::runtime_error("Cannot open audio file");
        std::vector<float> x(block), y(block); size_t total = 0; double worst = 0;
        const auto begin = std::chrono::steady_clock::now();
        while (in.read(reinterpret_cast<char*>(x.data()), block * sizeof(float)) || in.gcount()) {
            while (event_index < events.size() && events[event_index].at("frame").get<size_t>() <= total) {
                set_values(events[event_index].at("values"), false); ++event_index;
            }
            const auto frames = unsigned(in.gcount() / sizeof(float));
            const auto t0 = std::chrono::steady_clock::now();
            model.process(x.data(), y.data(), frames, v);
            const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
            worst = std::max(worst, ms);
            for (unsigned i = 0; i < frames; ++i) if (!std::isfinite(y[i])) throw std::runtime_error("Non-finite output");
            out.write(reinterpret_cast<char*>(y.data()), frames * sizeof(float)); total += frames;
        }
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        std::cout << nlohmann::json{{"frames", total}, {"seconds", elapsed}, {"realtime_ratio", elapsed / (total / rate)}, {"worst_block_ms", worst}}.dump() << '\n';
    } catch (const std::exception& ex) { std::cerr << ex.what() << '\n'; return 1; }
}
