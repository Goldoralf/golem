// SPDX-License-Identifier: GPL-3.0-or-later
// LA PASTILLE DES SERVICES (mockups/settings-badges.html, validée le 2026-10-11) : la même source que l'écran
// de chargement (state.boot.services), affichée sur ⚙ → API → golem.fm / Tone3000. Pur, testé (services-model.test.mjs).
// Deux natures : 'missing' (anneau — jamais réglé) et 'error' (plein — réglé mais ça ne répond pas). null = rien :
// ça marche, ou pas encore vérifié (jamais une pastille pour un doute).

const GRACE_S = 15;                                  // le lien golem.fm met quelques secondes à s'ouvrir après le démarrage

export const serviceBadges = st => {
  const boot = (st && st.boot) || {};
  const sv = boot.services;
  const out = { fm: null, t3k: null, api: null, settings: null };
  if (!sv) return out;
  const age = (boot.now || 0) - (boot.t0 || 0);
  const fm = sv.fm || {};
  // golem.fm JAMAIS appairé : pas de pastille — il est optionnel, un golem neuf ne porte pas d'anneau à vie (2026-10-31)
  if (fm.configured && fm.ok === false && age > GRACE_S) out.fm = { kind: 'error', text: 'golem.fm is paired but not reachable — check the network or golem.fm.' };
  const tk = sv.t3k || {};
  if (tk.ok === false) {
    out.t3k = tk.configured === false
      ? { kind: 'missing', text: 'TONE3000 is not connected — tones to install come from TONE3000. Tap to connect.' }
      : { kind: 'error', text: 'TONE3000: ' + (tk.why || 'not connected') + ' — tap to sign in again.' };
  }
  const worst = (...xs) => xs.some(x => x && x.kind === 'error') ? 'error' : (xs.some(x => x && x.kind === 'missing') ? 'missing' : null);
  out.api = worst(out.fm, out.t3k);
  out.settings = out.api;                            // d'autres onglets (Soundcard, Network) s'y ajouteront, au cas par cas
  return out;
};

// golem.fm appairé ? true seulement si le contrôle de démarrage l'a vu réglé : un bouton qui ne mène qu'à golem.fm
// (☁ Pull, ↻ Sync, ☁ push) est ABSENT tant que ce n'est pas le cas (docs/private/launch-plan.md §3 : un bouton isolé est absent)
export const fmPaired = st => !!(st && st.boot && st.boot.services && st.boot.services.fm && st.boot.services.fm.configured);

// DEV : ?svc=demo — golem.fm non appairé, TONE3000 en erreur (captures de vérification)
export const demoServicesState = () => ({ boot: { t0: 0, now: 100, services: { fm: { configured: false, ok: false, why: 'not paired' }, t3k: { configured: true, ok: false, why: 'token expired' } } } });
export const withDemo = st => (/[?&]svc=demo/.test(location.search) ? { ...(st || {}), ...demoServicesState() } : st);
