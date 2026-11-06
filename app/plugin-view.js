// SPDX-License-Identifier: GPL-3.0-or-later
// LA FENÊTRE D'UN PLUGIN, DANS GOLEM (Linux — docs/plugin-window.md, 2026-10-14 : piste B).
// REAPER dessine sur un écran virtuel que personne ne voit : le bridge FILME la fenêtre de Vital (MJPEG, un simple
// <img>) et REJOUE ici nos gestes dedans (XTEST). Marche depuis l'écran de la machine comme depuis une tablette.
// « Done » ferme la fenêtre : golem_rig voit la fermeture, et le Designer range le son retouché (page-designer).
import { html, useState, useEffect, useRef, post } from './lib.js';

// Les gestes partent DANS L'ORDRE (down → move → up : un up arrivé avant son down laisserait le bouton enfoncé) ;
// un mouvement en attente est remplacé par le suivant — Vital n'a besoin que de la dernière position.
function gestureQueue(blockId) {
  const q = []; let busy = false;
  const pump = async () => {
    if (busy) return; busy = true;
    while (q.length) {
      const g = q.shift();
      await post('/api/plugin-view/' + encodeURIComponent(blockId) + '/input', g).catch(() => {});
    }
    busy = false;
  };
  return g => {
    if (g.ev === 'move' && q.length && q[q.length - 1].ev === 'move') q[q.length - 1] = g; else q.push(g);
    pump();
  };
}

export function PluginView({ blockId, title, w, h, saving, onDone }) {
  const img = useRef(null);
  const send = useRef(null);
  if (!send.current) send.current = gestureQueue(blockId);
  const [src, setSrc] = useState(() => '/api/plugin-view/' + encodeURIComponent(blockId) + '/stream?t=' + Date.now());
  // le flux s'arrête quand la fenêtre bouge ou se redimensionne : on le relance
  const restart = () => setTimeout(() => setSrc('/api/plugin-view/' + encodeURIComponent(blockId) + '/stream?t=' + Date.now()), 600);
  // (x, y) du doigt -> [0,1]² de la fenêtre : l'image est en « contain », il faut retirer les bandes
  const at = e => {
    const r = img.current.getBoundingClientRect();
    const k = Math.min(r.width / w, r.height / h), dw = w * k, dh = h * k;
    const ox = r.left + (r.width - dw) / 2, oy = r.top + (r.height - dh) / 2;
    return { x: (e.clientX - ox) / dw, y: (e.clientY - oy) / dh };
  };
  const inside = p => p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;
  const down = useRef(false);
  const lastMove = useRef(0);
  const onDown = e => {
    const p = at(e); if (!inside(p)) return;
    e.preventDefault(); img.current.setPointerCapture(e.pointerId); down.current = true;
    send.current({ ev: 'down', ...p });
  };
  const onMove = e => {
    const now = performance.now();
    if (now - lastMove.current < (down.current ? 25 : 90)) return;          // survol : moins souvent qu'un glissé
    lastMove.current = now;
    const p = at(e); if (!down.current && !inside(p)) return;
    send.current({ ev: 'move', ...p });
  };
  const onUp = e => { if (!down.current) return; down.current = false; send.current({ ev: 'up', ...at(e) }); };
  const onWheel = e => { const p = at(e); if (!inside(p)) return; e.preventDefault(); send.current({ ev: 'wheel', dy: e.deltaY, ...p }); };
  useEffect(() => {                                                          // molette : écouteur non passif
    const el = img.current; if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [w, h]);
  return html`<div class="pv">
    <div class="pv-bar">
      <b>${title}</b>
      <span class="muted">${saving ? 'Keeping your sound…' : 'Your changes are kept in this patch when you close the window'}</span>
      <span class="grow"></span>
      <button class="mini primary" disabled=${saving} onClick=${onDone}>Done</button>
    </div>
    <div class="pv-stage">
      <img ref=${img} class="pv-img" src=${src} alt="" draggable="false" onError=${restart} onLoad=${() => {}}
        onPointerDown=${onDown} onPointerMove=${onMove} onPointerUp=${onUp} onPointerCancel=${onUp}
        onContextMenu=${e => e.preventDefault()} />
    </div>
  </div>`;
}
