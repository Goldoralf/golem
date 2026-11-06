// SPDX-License-Identifier: GPL-3.0-or-later
// LES ERREURS DE L'APP (docs/diagnostics.md §7.2, 2026-10-27) : un écouteur global, posé UNE fois par page, qui envoie
// au bridge ce qu'une erreur JavaScript dit d'elle — la page sans ses paramètres, le message (200 caractères), le fichier
// et la ligne, au plus 5 frames de pile en « fichier:ligne ». Jamais l'adresse complète, jamais un état de l'app.
// La même erreur part une fois par chargement, au plus MAX_PER_LOAD en tout ; le bridge plafonne encore par session et
// scrubbe. `ui_error` n'est jamais un déclencheur : il part avec le paquet de session.

export const MAX_PER_LOAD = 20;

// « https://rack.local:8770/app/lib.js?v=3 » → « lib.js »
export const base = (u) => String(u || '').split(/[?#]/)[0].split(/[\\/]/).pop();

// la route sans ses paramètres ni ses ids : « #/songs/rs-abc?x=1 » → « /songs »
export function pageOf(loc) {
  const h = String((loc && loc.hash) || '').replace(/^#/, '').split('?')[0];
  const seg = h.split('/').filter(Boolean)[0];
  return seg ? '/' + seg : String((loc && loc.pathname) || '').split('/').pop() || '/';
}

// les frames d'une pile Chrome (« at f (url:12:5) ») ou Firefox/Safari (« f@url:12:5 ») → « fichier:ligne », 5 au plus
export function frames(stack) {
  const out = [];
  for (const line of String(stack || '').split('\n')) {
    const m = line.match(/([^\s()@]+?\.m?js)(?:\?[^:\s)]*)?:(\d+)(?::\d+)?\)?\s*$/);
    if (m) out.push(base(m[1]) + ':' + m[2]);
    if (out.length >= 5) break;
  }
  return out;
}

// un ErrorEvent ou un PromiseRejectionEvent → le corps de POST /api/diag/ui-error (ou null : rien à dire)
export function payload(ev, loc, client) {
  let err = ev && ('reason' in ev ? ev.reason : ev.error);
  let msg = ev && 'reason' in ev ? (err && err.message) || String(err) : (ev && ev.message) || (err && err.message) || '';
  if (!msg) return null;
  const st = err && err.stack ? frames(err.stack) : [];
  const src = (ev && ev.filename) || (st[0] ? st[0].split(':')[0] : '');
  const line = ev && ev.lineno != null ? ev.lineno : (st[0] ? Number(st[0].split(':')[1]) : null);
  return { page: pageOf(loc), msg: String(msg).slice(0, 200), src: base(src), line, col: ev && ev.colno != null ? ev.colno : null,
           frames: st, client };
}

// l'écouteur : `send(body)` poste ; rend une fonction qui le retire (les tests)
export function watch(win, client, send) {
  const seen = new Set();
  let n = 0;
  const on = (ev) => {
    try {
      const p = payload(ev, win.location, client);
      if (!p || n >= MAX_PER_LOAD) return;
      const key = p.msg + '@' + p.src + ':' + p.line;
      if (seen.has(key)) return;
      seen.add(key); n += 1;
      Promise.resolve(send(p)).catch(() => {});      // un envoi raté ne fait jamais une nouvelle erreur
    } catch (e) { /* l'écouteur ne casse jamais la page */ }
  };
  win.addEventListener('error', on);
  win.addEventListener('unhandledrejection', on);
  return () => { win.removeEventListener('error', on); win.removeEventListener('unhandledrejection', on); };
}

// le branchement réel : POST au bridge, sans passer par api() (une erreur de transport ne doit rien relancer)
export function watchErrors(client) {
  return watch(window, client, (body) => fetch('/api/diag/ui-error', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive: true,
  }));
}
