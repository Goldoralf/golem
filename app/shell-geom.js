// SPDX-License-Identifier: GPL-3.0-or-later
// MÉMOIRE DE FENÊTRE du poste de travail — taille et zoom d'une fenêtre `golem ui|device|phone`.
// Contrat : docs/ui-architecture.md § « la fenêtre du poste de travail ». Le rack (kiosk) n'est
// PAS concerné : là-bas la fenêtre fait l'écran, il n'y a rien à retenir.
//
// ── POURQUOI LA PAGE, ET PAS UN OUTIL DE FENÊTRAGE ──
// La session est en Wayland : un client ne peut PAS interroger la géométrie d'une fenêtre
// (xdotool/wmctrl n'existent d'ailleurs pas sur cette machine). La seule source fiable est la
// page elle-même. Mesuré le 2026-07-31 dans une fenêtre `--app` : `outerWidth/outerHeight`
// valent EXACTEMENT ce que `--window-size` a demandé (1024,600 -> 1024,600, aucune bordure
// comptée) — l'aller-retour est donc exact, sans correctif à deviner.
//
// ── DEUX NOMBRES ORTHOGONAUX ──
// `w/h` sont des px CSS, `dpr` l'échelle d'affichage. Mesuré : `--force-device-scale-factor=1.5`
// change `devicePixelRatio` SANS toucher `outerWidth` — les deux se relisent séparément et se
// rejouent séparément. La taille physique à l'écran est leur produit.
//
// ── `base` : ne JAMAIS figer l'échelle de quelqu'un qui n'a rien demandé ──
// Sur un écran HiDPI, `dpr` vaut 2 sans que personne n'ait zoomé. Rejouer 2 en dur épinglerait
// l'échelle du bureau pour toujours. `base` = le dpr AU CHARGEMENT, avant tout Ctrl+/- — d'où
// le drapeau `first` ci-dessous. Tant que `dpr == base`, le lanceur ne passe aucun drapeau et le
// navigateur reste maître ; et `base` se remet à jour à chaque ouverture non forcée, donc un
// changement de mise à l'échelle du bureau est suivi tout seul.

const near = (a, b) => Math.abs(a - b) <= 4;

export function trackShellGeometry() {
  // Le nom de la coquille vient du LANCEUR (?shell=ui|device|phone) — jamais d'une heuristique.
  // Sans lui : la même app ouverte dans un onglet du navigateur personnel, ou dans l'iframe de
  // la coquille, écrirait la taille de la fenêtre de quelqu'un d'autre.
  let shell = null;
  try { shell = new URLSearchParams(location.search).get('shell'); } catch { /* rien */ }
  if (!shell || window.top !== window) return;

  // `first` : le rapport du CHARGEMENT. C'est le seul instant où `devicePixelRatio` vaut
  // l'échelle de l'écran et rien d'autre — après, il porte aussi le Ctrl+/- de l'utilisateur.
  // Le bridge s'en sert pour ne jamais confondre « son écran est HiDPI » et « il a zoomé ».
  let first = true;
  const send = beacon => {
    const body = JSON.stringify({ shell, w: window.outerWidth, h: window.outerHeight,
                                  dpr: window.devicePixelRatio || 1, first });
    first = false;
    if (beacon && navigator.sendBeacon) {
      navigator.sendBeacon('/api/ui/geometry', new Blob([body], { type: 'application/json' }));
      return;
    }
    fetch('/api/ui/geometry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
      .catch(() => { /* le bridge peut être en train de recharger : ce n'est pas une erreur */ });
  };

  // RATTRAPAGE — le cas qui rend la mémoire fiable au lieu d'« à peu près ».
  // Chrome est un SINGLETON par `--user-data-dir` : si une fenêtre GoleM tourne déjà, le second
  // `golem …` lui passe l'URL et s'arrête — ses `--window-size`/`--force-device-scale-factor`
  // sont ignorés en silence (mesuré : la fenêtre device demandée en 700×500 est sortie en
  // 1024×600). La page se remet donc elle-même à sa taille. `window.resizeTo` fonctionne dans
  // une fenêtre `--app` (vérifié sur cette session Wayland : 1024×600 -> 1300×820).
  // Il ne se déclenche QUE si l'écart est réel : quand le lanceur a pu poser ses drapeaux, la
  // taille est déjà la bonne et rien ne bouge — pas de sursaut à l'ouverture.
  // ⚠ ON REJOUE LA CORRECTION. Chrome arrête les dimensions d'une fenêtre recyclée APRÈS que sa
  // page ait fini de charger : un `resizeTo` posé au chargement est écrasé par le placement qui
  // arrive ensuite. Mesuré — la même fenêtre refusait la correction à l'ouverture et l'acceptait
  // deux secondes plus tard. Trois essais espacés, et on s'arrête dès que la taille est bonne :
  // on ne se bat pas avec l'utilisateur qui redimensionne, on rattrape un placement en retard.
  fetch('/api/ui/geometry').then(r => r.json()).then(d => {
    const m = (d || {})[shell];
    if (!m || !m.w || !m.h) return;
    const fits = () => near(window.outerWidth, m.w) && near(window.outerHeight, m.h);
    [0, 500, 1600].forEach(ms => setTimeout(() => {
      if (fits()) return;
      try { window.resizeTo(m.w, m.h); } catch { /* refusé : on garde la taille reçue */ }
    }, ms));
  }).catch(() => { /* première fois, ou bridge muet */ }).finally(() => send(false));

  let t = null;
  addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => send(false), 600); });
  // `pagehide` plutôt que `beforeunload` : c'est le seul qui parte à coup sûr quand la fenêtre
  // se ferme, et `sendBeacon` survit à la mort du document.
  addEventListener('pagehide', () => send(true));
}
