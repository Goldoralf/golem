// SPDX-License-Identifier: GPL-3.0-or-later
// Modal « + New » — naviguer TONE3000 (via le proxy bridge) et installer des amplis/pédales.
// Recherche + filtre gear + tri serveur ; détail d'un tone = cocher les modèles voulus ; Install
// avec progression (poll /api/t3k/status) ; à la fin le catalogue local est invalidé (refreshCatalog).
import { html, useState, useEffect, useRef, post, cls, esc, go, refreshCatalog } from './lib.js';

const GEARS = [['', 'All'], ['amp', 'Heads'], ['amp-cab', 'Heads+Cab'], ['cab', 'Cabs/IR'], ['pedal', 'Pedals'], ['outboard', 'Outboard']];

export function T3kModal({ onClose, onInstalled, initGear = '' }) {
  const [q, setQ] = useState('');
  const [gear, setGear] = useState(initGear);
  const [res, setRes] = useState(null);         // {tones, total} | {error}
  const [sel, setSel] = useState(null);         // détail d'un tone (avec models)
  const [checked, setChecked] = useState({});   // model id -> bool
  const [inst, setInst] = useState(null);       // état d'install en cours (status poll)
  const timer = useRef(null);

  const search = async (query, g) => {
    setRes(null);
    const u = `/api/t3k/search?q=${encodeURIComponent(query)}${g ? '&gears=' + g : ''}`;
    setRes(await fetch(u).then(r => r.json()).catch(e => ({ error: String(e) })));
  };
  useEffect(() => {                             // debounce de recherche
    clearTimeout(timer.current);
    timer.current = setTimeout(() => search(q, gear), q ? 400 : 0);
    return () => clearTimeout(timer.current);
  }, [q, gear]);

  const openTone = async t => {
    const d = await fetch('/api/t3k/tone/' + t.id).then(r => r.json()).catch(() => null);
    if (!d) return;
    setSel(d);
    // précoche les A2 quand il y en a (le serveur les renvoie en tête), sinon les 8 premiers
    const a2 = (d.models || []).filter(m => String(m.arch) === '2');
    const ck = {}; (a2.length ? a2 : d.models || []).slice(0, 8).forEach(m => { ck[m.id] = true; });
    setChecked(ck);
  };

  const install = async () => {
    const ids = Object.entries(checked).filter(([, v]) => v).map(([k]) => Number(k));
    if (!ids.length) return;
    const r = await post('/api/t3k/install', { id: sel.id, model_ids: ids }).catch(e => ({ error: String(e) }));
    if (r.error) { setInst({ phase: 'error', msg: r.error }); return; }
    setInst({ phase: 'meta', msg: '…' });
    const poll = setInterval(async () => {
      const s = await fetch('/api/t3k/status').then(x => x.json()).catch(() => null);
      if (!s) return;
      setInst(s);
      if (s.phase === 'done' || s.phase === 'error') {
        clearInterval(poll);
        if (s.phase === 'done') { refreshCatalog(); onInstalled && onInstalled(); search(q, gear); }
      }
    }, 1000);
  };

  const nInst = inst && ['meta', 'download', 'classify', 'photo'].includes(inst.phase);

  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && !nInst && onClose()}>
    <div class="detail-card t3k">
      <button class="close" onClick=${onClose} disabled=${nInst}>×</button>
      <h2>TONE3000 <small>add amps & pedals</small></h2>

      ${!sel ? html`
        <div class="t3k-bar">
          <input class="search" autofocus placeholder="Search TONE3000… (5150, Klon, AC30…)"
            value=${q} onInput=${e => setQ(e.target.value)} />
          <select class="flt-sel" value=${gear} onChange=${e => setGear(e.target.value)}>
            ${GEARS.map(([v, l]) => html`<option value=${v} selected=${v === gear}>${l}</option>`)}
          </select>
          <button class=${cls('chip', /\bbass\b/.test(q) && 'on')} title="quick filter — bass gear"
            onClick=${() => setQ(/\bbass\b/.test(q) ? q.replace(/\s*\bbass\b\s*/, ' ').trim() : ('bass ' + q).trim())}>🎸 Bass</button>
        </div>
        <div class="t3k-list">
          ${!res ? html`<div class="muted pad">Searching…</div>`
            /* une ligne et le geste, pas deux phrases qui disent la même chose (audit 31/10, #6) */
            : res.error ? html`<div class="muted pad">✗ ${esc(String(res.error).replace(/ — (sign in|reconnect it|set it) .*$/, ''))}
                <button class="chip" onClick=${() => { onClose && onClose(); go('system/connect/tone3000'); }}>Connect TONE3000 ›</button></div>`
            : !res.tones.length ? html`<div class="muted pad">No result.</div>`
            : res.tones.map(t => html`<button class=${cls('t3k-row', t.installed && 'have')} onClick=${() => openTone(t)}>
                <b>${esc(t.title)}</b>
                <span class="t3k-meta">${esc(t.gear)} · ⬇ ${t.downloads} · ♥ ${t.favorites} · ${esc(t.creator)}</span>
                ${t.a2 ? html`<span class="t3k-badge a2">A2</span>` : ''}
                ${t.installed ? html`<span class="t3k-badge">installed</span>` : ''}
              </button>`)}
        </div>`

      : html`
        <button class="mini" onClick=${() => { setSel(null); setInst(null); }} disabled=${nInst}>‹ back</button>
        <h3 class="t3k-ttl">${esc(sel.title)} ${sel.installed ? html`<span class="t3k-badge">installed — reinstall replaces</span>` : ''}</h3>
        <div class="muted">${esc(sel.gear)} · ⬇ ${sel.downloads} · ♥ ${sel.favorites} · by ${esc(sel.creator)}
          ${sel.makes && sel.makes.length ? ' · ' + esc(sel.makes.slice(0, 3).join(', ')) : ''}</div>
        <div class="t3k-models">
          ${(sel.models || []).map((m, i) => html`<label class=${cls('t3k-mdl', i >= 8 && !checked[m.id] && 'over')}>
            <input type="checkbox" checked=${!!checked[m.id]}
              onChange=${e => setChecked({ ...checked, [m.id]: e.target.checked })} />
            <span>${esc(m.name || 'model')}</span>
            <em>${esc(m.size || '')}${m.arch ? html` · ${String(m.arch) === '2' ? html`<span class="a2">A2</span>` : 'A' + m.arch}` : ''}</em>
          </label>`)}
        </div>
        <div class="t3k-foot">
          ${inst ? html`<span class=${cls('t3k-st', inst.phase === 'error' && 'ko', inst.phase === 'done' && 'ok')}>
              ${inst.phase === 'download' ? `⬇ ${inst.done}/${inst.total} ` : ''}${esc(inst.msg || inst.phase)}</span>` : ''}
          <span class="grow"></span>
          <button class="primary big" disabled=${nInst} onClick=${install}>
            ${nInst ? '⏳ Installing…' : '⬇ Add to golem'}</button>
        </div>`}
    </div></div>`;
}
