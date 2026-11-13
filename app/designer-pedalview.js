// SPDX-License-Identifier: GPL-3.0-or-later
// LA VUE PÉDALIER du Designer (docs/designer-glyphs-pedals.md §2) : la chaîne de la lane dessinée en vrai pédalier par
// les moteurs de golem-fx (app/golem-visuals.js). Elle LIT et BASCULE, elle ne règle pas : toucher une pédale l'allume
// ou l'éteint dans la scène courante (ce que fait la pastille d'une tuile), un appui long ouvre la feuille du bloc,
// toucher la bande d'une branche la coupe dans la scène. Ajouter, déplacer, retirer : la vue Blocks.
import { html, useState, useEffect, useRef } from './lib.js';
import { loadVisuals, visualsReady, stageSvg } from './golem-visuals.js';

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

export function PedalView({ lane, chain, sceneState, values, catalog, onToggle, onOpen, onBranch }) {
  const [ok, setOk] = useState(visualsReady());
  const [err, setErr] = useState('');
  useEffect(() => { if (!ok) loadVisuals(catalog).then(() => setOk(true)).catch(e => setErr(String(e.message || e))); }, []);
  const box = useRef(null);
  const press = useRef(null);
  if (err) return html`<div class="pv-msg">The pedal view could not load (${err}). Switch back to Blocks in the ⋯ menu.</div>`;
  if (!ok) return html`<div class="pv-msg">Drawing the pedalboard…</div>`;
  const svg = stageSvg(chain, sceneState, { floor: 'stage', guitar: true }, values);
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
  return html`<div class="pv-stage" ref=${box} onPointerDown=${down} onPointerUp=${up} onPointerLeave=${up} onClick=${click}
    title="tap a pedal: on / off in this scene · long press: its settings · tap a branch tape: mute it in this scene"
    dangerouslySetInnerHTML=${{ __html: svg }}></div>`;
}
