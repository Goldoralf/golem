// SPDX-License-Identifier: GPL-3.0-or-later
// LE MOTEUR NE PART JAMAIS EN SWAP (2026-11-26, provision/system-tuning.md « Engine memory ») — le Golem Engine
// (luasession) comme REAPER : le même jour, REAPER avait 128 Mo en swap pour 113 Mo en RAM, Firefox jouant à côté.
//
// luasession (le Golem Engine) ne verrouille que sa réserve temps réel (~80 Mo, des mlock() ponctuels) : le reste de
// son tas part en swap sur une machine juste en mémoire, et un thread DSP qui retouche une page swappée attend le
// disque — un décrochage. Mesuré sur le rack Linux (3 Go) : VmSwap 0 → 228 Mo en une heure, la page Live ouverte.
// La limite memlock est déjà illimitée (limits.d/95-golem-audio.conf) : il manquait l'APPEL. Chargée par LD_PRELOAD
// (bridge/engine/ardour.py, provision/lib-engine.sh ; provision/start.sh pour REAPER), cette bibliothèque le fait au
// démarrage d'un moteur seulement.
//
// MCL_ONFAULT : une page touchée ne quitte plus la RAM, mais rien n'est préchargé — sans lui, MCL_CURRENT chargerait
// tout l'espace mappé (~1,5 Go) au lieu de l'empreinte réelle. À retirer quand le moteur fera mlockall lui-même.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#ifndef MCL_ONFAULT
#define MCL_ONFAULT 4
#endif

__attribute__((constructor)) static void golem_mlock(void) {
  char exe[4096];
  ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
  if (n < 0) return;
  exe[n] = 0;
  const char *b = strrchr(exe, '/');
  b = b ? b + 1 : exe;
  // les deux moteurs de golem ; bash run.sh, python run.py, setsid… : rien, la variable passe au moteur
  if (strcmp(b, "luasession") != 0 && strcmp(b, "reaper") != 0) return;
  unsetenv("LD_PRELOAD");                       // les enfants du moteur n'en héritent pas
  if (mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT))
    fprintf(stderr, "golem-mlock: mlockall failed: %m\n");
  else
    fprintf(stderr, "golem-mlock: mlockall(onfault) ok\n");
}
