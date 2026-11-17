// SPDX-License-Identifier: GPL-3.0-or-later
// LA VUE PÉDALIER du Designer (docs/designer-glyphs-pedals.md §2) : la chaîne de la lane dessinée par les moteurs de
// golem-fx (app/golem-visuals.js) — depuis le 2026-11-17 PAR SECTIONS (GolemRig) : les pédales vues de dessus à leur
// taille réelle, l'ampli de face, l'outboard en rack, un onglet par section que la chaîne a. Elle LIT et BASCULE, elle ne règle pas : toucher une pédale l'allume
// ou l'éteint dans la scène courante (ce que fait la pastille d'une tuile), un appui long ouvre la feuille du bloc,
// toucher la bande d'une branche la coupe dans la scène. Ajouter, déplacer, retirer : la vue Blocks.
import { html, useState, useEffect, useRef } from './lib.js';
import { loadVisuals, visualsReady, rigSections, rigFloor } from './golem-visuals.js';

const LONG_MS = 500;

/** Le `ref` du Designer d'une position du dessin. golem-fx numérote comme son `fromGolem` : les blocs de `pre`, puis
 *  le split (s'il y en a un) comme UN élément dont les blocs sont « k.branche.bloc », puis ceux de `post`. */
export function refOfPath(path, chain, lane) {
  const parts = String(path).split('.').map(Number);
  if (parts.some(n => !Number.isInteger(n) || n < 0)) return null;
  const pre = (chain && chain.pre) || [], post = (chain && chain.post) || [];
  const hasSplit = !!(chain && chain.split && (chain.split.branches || []).length);
  const k = parts[0];
  if (parts.length === 3) return hasSplit && k === pre.length ? { lane, z: 'br', bi: parts[1], i: parts[2] } : null;
  if (k < pre.length) return { lane, z: 'pre', i: k };
  const j = k - pre.length - (hasSplit ? 1 : 0);
  return j >= 0 && j < post.length ? { lane, z: 'post', i: j } : null;
}

/** La chaîne DANS L'ORDRE DU SIGNAL, avec le chemin de chaque bloc (la numérotation de golem-fx, cf. refOfPath) : les
 *  sections trient les blocs par nature et perdent cet ordre — la bande sous la scène le garde. Rend
 *  [{path, id, type, branch?}] ; `branch` = la lettre de la branche d'un split. */
export function signalOrder(chain) {
  const pre = (chain && (chain.pre || chain.chain)) || [], post = (chain && chain.post) || [];
  const brs = (chain && chain.split && chain.split.branches) || [];
  const out = pre.map((b, i) => ({ path: String(i), id: b.id, type: b.type }));
  brs.forEach((br, bi) => ((br && br.blocks) || (Array.isArray(br) ? br : [])).forEach((b, i) =>
    out.push({ path: pre.length + '.' + bi + '.' + i, id: b.id, type: b.type, branch: String.fromCharCode(65 + bi) })));
  const k = pre.length + (brs.length ? 1 : 0);
  post.forEach((b, j) => out.push({ path: String(k + j), id: b.id, type: b.type }));
  return out;
}

export function PedalView({ lane, chain, sceneState, values, catalog, genre, seed, nameOf, onToggle, onOpen, onBranch }) {
  const [ok, setOk] = useState(visualsReady());
  const [tab, setTab] = useState(null);                  // la section montrée (sa clé) ; null = celle par défaut
  const [err, setErr] = useState('');
  useEffect(() => { if (!ok) loadVisuals(catalog).then(() => setOk(true)).catch(e => setErr(String(e.message || e))); }, []);
  const box = useRef(null);
  const press = useRef(null);
  if (err) return html`<div class="pv-msg">The pedal view could not load (${err}). Switch back to Blocks in the ⋯ menu.</div>`;
  if (!ok) return html`<div class="pv-msg">Drawing the pedalboard…</div>`;
  const secs = rigSections(chain, sceneState, { floor: rigFloor(genre), seed: seed || lane }, values);
  if (!secs.length) return html`<div class="pv-msg">This lane has no block to draw yet. Add one in Blocks (⋯ menu).</div>`;
  // la section par défaut : l'ampli s'il y en a un (c'est le son), sinon la première ; un onglet choisi qui n'existe
  // plus (le bloc a été retiré) retombe dessus
  const cur = secs.find(x => x.key === tab) || secs.find(x => x.key === 'amp') || secs[0];
  const svg = cur.svg;
  // la bande de la chaîne : chaque bloc dans l'ordre du signal, ceux de la section montrée en clair ; un baffle
  // empilé sous sa tête n'a pas de dessin à lui — il suit le bloc d'avant
  const order = signalOrder(chain);
  let last = null;
  const strip = order.map(b => {
    const sec = secs.find(x => x.paths.includes(b.path));
    last = sec || last;
    return Object.assign({}, b, { sec: (sec || last || cur).key });
  });
  // un geste = ce que le doigt a touché dans le dessin : une pédale (data-idx) ou la bande d'une branche (data-branch)
  const target = e => {
    const t = e.target.closest && e.target.closest('[data-idx],[data-branch]');
    if (!t || !box.current || !box.current.contains(t)) return null;
    if (t.hasAttribute('data-branch')) return { branch: t.getAttribute('data-branch') };
    const ref = refOfPath(t.getAttribute('data-idx'), chain, lane);
    return ref ? { ref } : null;
  };
  const down = e => {
    const t = target(e);
    if (!t || !t.ref) return;
    clearTimeout(press.current && press.current.timer);
    press.current = { t, long: false, timer: setTimeout(() => { press.current.long = true; onOpen(t.ref); }, LONG_MS) };
  };
  const up = () => { if (press.current) clearTimeout(press.current.timer); };
  const click = e => {
    const t = target(e);
    const p = press.current; press.current = null;
    if (!t || (p && p.long)) return;
    if (t.branch) onBranch(t.branch); else onToggle(t.ref);
  };
  return html`<div class="pv-wrap">
    ${secs.length > 1 ? html`<div class="pv-tabs" role="tablist">
      ${secs.map(x => html`<button role="tab" aria-selected=${x.key === cur.key} class=${'pv-tab' + (x.key === cur.key ? ' is-on' : '')}
        title=${x.count + (x.count > 1 ? ' units' : ' unit')} onClick=${() => setTab(x.key)}>${x.label}<small>${x.count}</small></button>`)}
    </div>` : ''}
    <div class="pv-stage" ref=${box} onPointerDown=${down} onPointerUp=${up} onPointerLeave=${up} onClick=${click}
      title="tap a unit: on / off in this scene · long press: its settings · tap a branch tape: mute it in this scene"
      dangerouslySetInnerHTML=${{ __html: svg }}></div>
    ${strip.length > 1 ? html`<div class="pv-chain" aria-label="the chain, in signal order">
      ${strip.map((b, i) => html`${i > 0 && b.branch !== strip[i - 1].branch ? html`<i class="pv-sep">${b.branch || '›'}</i>` : ''}
        <button class=${'pv-chip' + (b.sec === cur.key ? ' is-on' : '')} title="show its section"
          onClick=${() => setTab(b.sec)}>${nameOf ? nameOf(b.type) : b.type}</button>`)}
    </div>` : ''}
  </div>`;
}
