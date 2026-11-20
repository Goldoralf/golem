# SPDX-License-Identifier: GPL-3.0-or-later
# golem Capture en LV2, compilé pour WINDOWS (MSYS2 UCRT64, MinGW-w64) : les MÊMES sources que ../CMakeLists.txt
# (../lv2.cpp, ../../capture/engine.cpp, le cœur NAM paramétrique à la même révision), sans les toucher — l'archive
# Linux épingle leurs empreintes (bin/manifest.json). Ce qui change sous Windows :
#  · les exports : un fichier .def ne publie que lv2_descriptor (le script de version ELF n'existe pas en PE) ;
#  · l'édition de liens statique (libstdc++, libgcc, winpthread), comme le lecteur CLAP sous MinGW ;
#  · le manifeste LV2 nomme golem-capture.dll.
#   cmake -S native/capture-lv2/windows -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build
cmake_minimum_required(VERSION 3.22)
project(golem_capture_lv2_windows VERSION 1.0.0 LANGUAGES CXX)
if(NOT MINGW)
  message(FATAL_ERROR "native/capture-lv2/windows builds with MinGW-w64 (MSYS2 UCRT64); Linux: native/capture-lv2")
endif()
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include(FetchContent)
set(GOLEM_NAM_SOURCE "" CACHE PATH "Existing NeuralAmpModelerCoreParametric checkout")
if(NOT GOLEM_NAM_SOURCE)
  # la même révision que ../CMakeLists.txt et native/capture/CMakeLists.txt
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
set(LV2SRC "${CMAKE_CURRENT_SOURCE_DIR}/..")
set(CAPTURE "${LV2SRC}/../capture")
file(GLOB NAM_SOURCES CONFIGURE_DEPENDS "${GOLEM_NAM_SOURCE}/NAM/*.cpp" "${GOLEM_NAM_SOURCE}/NAM/*/*.cpp")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.def" "EXPORTS\n    lv2_descriptor\n")
add_library(golem_capture_lv2 MODULE ${NAM_SOURCES} "${CAPTURE}/engine.cpp" "${LV2SRC}/lv2.cpp"
  "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.def")
target_include_directories(golem_capture_lv2 PRIVATE "${CAPTURE}" ${LV2_INCLUDE_DIRS}
  "${GOLEM_NAM_SOURCE}/NAM" "${GOLEM_NAM_SOURCE}/Dependencies/eigen"
  "${GOLEM_NAM_SOURCE}/Dependencies/nlohmann" "${GOLEM_NAM_SOURCE}/Dependencies/AudioDSPTools")
target_compile_definitions(golem_capture_lv2 PRIVATE NAM_SAMPLE_FLOAT=1 EIGEN_MPL2_ONLY=1 EIGEN_NO_DEBUG=1 NOMINMAX)
# la même cible que Linux (x86-64-v3 : AVX2, FMA) — le moteur ne tourne pas sur des processeurs plus anciens
target_compile_options(golem_capture_lv2 PRIVATE -march=x86-64-v3)
target_link_options(golem_capture_lv2 PRIVATE -static -static-libgcc -static-libstdc++)
set_target_properties(golem_capture_lv2 PROPERTIES PREFIX "" OUTPUT_NAME "golem-capture" SUFFIX ".dll"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2")
file(READ "${LV2SRC}/manifest.ttl" GOLEM_MANIFEST)
string(REPLACE "<golem-capture.so>" "<golem-capture.dll>" GOLEM_MANIFEST "${GOLEM_MANIFEST}")
# NEWLINE_STYLE UNIX : le cmake de MSYS2 écrit file(WRITE) en mode texte (CRLF) ; le paquet ne dépend pas de la copie
file(CONFIGURE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2/manifest.ttl" CONTENT "${GOLEM_MANIFEST}" @ONLY
  NEWLINE_STYLE UNIX)
configure_file("${LV2SRC}/golem-capture.ttl" "${CMAKE_CURRENT_BINARY_DIR}/golem-capture.lv2/golem-capture.ttl" COPYONLY)
