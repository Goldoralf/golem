# SPDX-License-Identifier: GPL-3.0-or-later
# golem Capture, en LV2 : le MÊME lecteur que native/capture (engine.cpp, le cœur NAM paramétrique épinglé), derrière
# une interface LV2 — pour le Golem Engine (Ardour), qui n'héberge pas le CLAP. Linux seulement. Le lecteur CLAP, ses
# archives et leurs empreintes (native/capture/bin) ne sont pas touchés.
cmake_minimum_required(VERSION 3.22)
project(golem_capture_lv2 VERSION 1.0.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include(FetchContent)
set(GOLEM_NAM_SOURCE "" CACHE PATH "Existing NeuralAmpModelerCoreParametric checkout")
if(NOT GOLEM_NAM_SOURCE)
  # la même révision que native/capture/CMakeLists.txt
  FetchContent_Declare(nam GIT_REPOSITORY https://github.com/phillipmself/NeuralAmpModelerCoreParametric.git
    GIT_TAG fddcbc91e74ba79066a43c3b73cc690073529232 GIT_SUBMODULES Dependencies/eigen Dependencies/AudioDSPTools)
  FetchContent_GetProperties(nam)
  if(NOT nam_POPULATED)
    FetchContent_Populate(nam)
  endif()
  set(GOLEM_NAM_SOURCE "${nam_SOURCE_DIR}")
endif()
find_package(PkgConfig REQUIRED)
pkg_check_modules(LV2 REQUIRED lv2)
set(CAPTURE "${CMAKE_CURRENT_SOURCE_DIR}/../capture")
file(GLOB NAM_SOURCES CONFIGURE_DEPENDS "${GOLEM_NAM_SOURCE}/NAM/*.cpp" "${GOLEM_NAM_SOURCE}/NAM/*/*.cpp")
add_library(golem_capture_lv2 MODULE ${NAM_SOURCES} "${CAPTURE}/engine.cpp" lv2.cpp)
target_include_directories(golem_capture_lv2 PRIVATE "${CAPTURE}" ${LV2_INCLUDE_DIRS}
  "${GOLEM_NAM_SOURCE}/NAM" "${GOLEM_NAM_SOURCE}/Dependencies/eigen"
  "${GOLEM_NAM_SOURCE}/Dependencies/nlohmann" "${GOLEM_NAM_SOURCE}/Dependencies/AudioDSPTools")
target_compile_definitions(golem_capture_lv2 PRIVATE NAM_SAMPLE_FLOAT=1 EIGEN_MPL2_ONLY=1 EIGEN_NO_DEBUG=1 NOMINMAX)
if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  target_compile_options(golem_capture_lv2 PRIVATE -march=x86-64-v3)
endif()
# Le cœur NAM reste PRIVÉ : exporté, son registre serait partagé avec celui du plugin NAM chargé dans le même moteur, et
# la seconde inscription le tue (docs/pitfalls/plugins.md). Seul lv2_descriptor sort.
set_target_properties(golem_capture_lv2 PROPERTIES PREFIX "" OUTPUT_NAME "golem-capture"
  CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN ON POSITION_INDEPENDENT_CODE ON
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.map" "{ global: lv2_descriptor; local: *; };\n")
target_link_options(golem_capture_lv2 PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_BINARY_DIR}/golem-capture.map")
configure_file(manifest.ttl "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2/manifest.ttl" COPYONLY)
configure_file(golem-capture.ttl "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2/golem-capture.ttl" COPYONLY)
