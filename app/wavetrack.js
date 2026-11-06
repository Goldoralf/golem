// SPDX-License-Identifier: GPL-3.0-or-later
// Mini-piste de DAW réutilisable : bouton play · nom · FORME D'ONDE cliquable · tête de lecture.
// Née dans Recordings (page-loops.js), extraite ici pour servir aussi la Library (samples, pads
// d'un kit) — « voir et écouter » est le même geste partout.
//
// Deux URL par piste, données par l'appelant, parce que les familles n'ont pas le même service :
//   audio  = ce que <audio> lit          (ex. /api/loop/… ou /api/sample?file=…)
//   peaks  = l'enveloppe d'amplitude     (ex. /api/loop-peaks/… ou /api/peaks?file=…)
import { html, useState, useEffect, useRef, cls, esc } from './lib.js';

export const mmss = s => !s || !isFinite(s) ? '—'
  : Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');

// Enveloppe -> UN seul <path> SVG : bord supérieur de gauche à droite, bord inférieur en retour.
// viewBox fixe + preserveAspectRatio="none" = le dessin s'étire à n'importe quelle largeur sans
// recalcul (et sans dépendre de la taille réelle en pixels au moment du rendu).
export const wavePath = pk => {
  if (!pk || !pk.length) return '';
  const n = pk.length, W = 1000, mid = 50;
  const up = [], dn = [];
  for (let i = 0; i < n; i++) {
    const x = (n === 1 ? 0 : i * W / (n - 1)).toFixed(1);
    const a = Math.max(0.6, pk[i] * 48);            // 0,6 = le trait de silence reste visible
    up.push(x + ' ' + (mid - a).toFixed(1));
    dn.push(x + ' ' + (mid + a).toFixed(1));
  }
  return 'M' + up.join('L') + 'L' + dn.reverse().join('L') + 'Z';
};

// Les crêtes ne sont demandées QUE quand la piste entre à l'écran : une page peut en afficher
// des centaines, on ne décode pas tout au montage.
export function WaveTrack({ label, name, audio, peaks, num, on, onToggle, tag, extra }) {
  const [pk, setPk] = useState(null);
  const [pos, setPos] = useState(0);                // 0..1, conservé à l'arrêt (comme un DAW)
  const au = useRef(null), box = useRef(null), asked = useRef(false), seekTo = useRef(0);

  useEffect(() => {
    const el = box.current;
    if (!el || asked.current || !peaks) return;
    const io = new IntersectionObserver(es => {
      if (!es.some(e => e.isIntersecting) || asked.current) return;
      asked.current = true; io.disconnect();
      fetch(peaks).then(r => r.json()).then(setPk).catch(() => setPk({ peaks: [], dur: 0 }));
    }, { rootMargin: '250px' });
    io.observe(el);
    return () => io.disconnect();
  }, [peaks]);

  // tête de lecture : rAF tant que ça joue (l'événement timeupdate est trop lâche, ~4 Hz)
  useEffect(() => {
    if (!on) return;
    // `autoplay` seul dépend de la politique du navigateur : on redemande explicitement la lecture
    // (le geste utilisateur qui vient de monter cet élément reste valide quelques secondes).
    if (au.current) { const p = au.current.play(); if (p && p.catch) p.catch(() => {}); }
    let raf;
    const tick = () => {
      const a = au.current;
      if (a && a.duration) setPos(a.currentTime / a.duration);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [on]);

  const d = wavePath(pk && pk.peaks);
  const dur = (pk && pk.dur) || 0;
  const pct = Math.max(0, Math.min(100, pos * 100));
  const click = e => {
    const r = box.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    setPos(ratio);
    seekTo.current = ratio;
    if (on && au.current && au.current.duration) au.current.currentTime = ratio * au.current.duration;
    else onToggle(true);                            // pas en lecture -> démarre À CET ENDROIT
  };

  return html`<div class=${cls('wv-row', on && 'on')}>
    ${num ? html`<span class="wv-n">${num}</span>` : ''}
    <span class="wv-info">
      <b class="wv-name">${esc(name)}</b>
      ${label ? html`<em class="wv-tech" title=${esc(label)}>${esc(label)}</em>` : ''}
    </span>
    ${tag ? html`<span class="wv-midi-tag">${esc(tag)}</span>` : ''}
    <button class="wv-play" title=${on ? 'pause' : 'play'}
      onClick=${() => { seekTo.current = pos < 0.999 ? pos : 0; onToggle(!on); }}>${on ? '❚❚' : '▶'}</button>
    <div class="wv" ref=${box} onClick=${click} title="click to play from here">
      ${d ? html`<svg class="wv-svg" viewBox="0 0 1000 100" preserveAspectRatio="none"><path d=${d} /></svg>
        <svg class="wv-svg done" viewBox="0 0 1000 100" preserveAspectRatio="none"
          style=${'clip-path:inset(0 ' + (100 - pct) + '% 0 0)'}><path d=${d} /></svg>
        <div class="wv-head" style=${'left:' + pct + '%'}></div>` : html`<div class="wv-load"></div>`}
    </div>
    <span class="wv-dur">${on || pos ? mmss(pos * dur) : mmss(dur)}</span>
    ${extra || ''}
    ${on ? html`<audio ref=${au} src=${audio} autoplay onEnded=${() => onToggle(false)}
      onLoadedMetadata=${e => { if (seekTo.current) e.target.currentTime = seekTo.current * e.target.duration; }} />` : ''}
  </div>`;
}
