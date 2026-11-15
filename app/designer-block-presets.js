// SPDX-License-Identifier: GPL-3.0-or-later
// LES PRESETS D'UN BLOC DANS SON TIROIR (maquette « Chorus drawer » validée le 2026-11-15, remplace l'onglet Presets
// du 2026-10-11) : choisir un preset et voir ses potards bouger sont UN geste — la liste est la colonne de gauche du
// tiroir, sur toute sa hauteur, et la façade de la pédale est à droite (les enfants). En bas à droite, le preset en
// jeu : « modified • » dès qu'un potard s'en écarte, Revert, Save as… Les presets viennent de
// /api/block-presets/<type> (library/block-presets/<type>/*.json) ; charger un preset écrit les paramètres de base
// du bloc et efface ses surcharges de scène (docs/archive/block-sheets.md §5).
import { html, useState, useAsync, cls, esc } from './lib.js';
import { INSTS, INST_LB, filterPresets, effectiveDefault, pushRecent, matchPreset } from './block-presets-model.mjs';

const api = (path, opts) => fetch('/api/block-presets/' + path, opts).then(r => r.json()).catch(() => null);

// le dernier preset chargé, par bloc (le temps de la session de l'app) : ce qui permet de dire « modified »
const LOADED = new Map();

export function BlockPresetsPane({ btype, blockId, inst, current, sig, onLoad, children }) {
  const [rev, setRev] = useState(0);
  const { data } = useAsync(() => api(encodeURIComponent(btype)), [btype, rev]);
  const list = (data && data.presets) || [];
  const [q, setQ] = useState('');
  const [scope, setScope] = useState('inst');
  const [, setTick] = useState(0);
  const [saving, setSaving] = useState(false);
  const [nm, setNm] = useState('');
  const [svInst, setSvInst] = useState(inst);
  const [armDel, setArmDel] = useState(null);
  const [msg, setMsg] = useState('');
  const flash = m => { setMsg(m); setTimeout(() => setMsg(''), 2500); };
  const effDef = effectiveDefault(list, inst);
  const shown = filterPresets(list, { inst, scope, q, sig })
    .sort((a, b) => (b.id === effDef) - (a.id === effDef) || (!!b.factory) - (!!a.factory) || String(a.name).localeCompare(String(b.name)));
  // le preset en jeu : celui dont chaque réglage est la valeur courante, sinon le dernier chargé (alors modifié)
  const exact = matchPreset(list, current);
  const lastId = LOADED.get(blockId);
  const cur = exact || list.find(p => p.id === lastId) || null;
  const modified = !!cur && cur !== exact;
  const load = p => { LOADED.set(blockId, p.id); onLoad(p.params); pushRecent(btype, p.id); setTick(x => x + 1); };
  const save = async () => {
    const name = nm.trim(); if (!name) return;
    const r = await api(encodeURIComponent(btype), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, params: current, inst: svInst }) });
    if (r && r.error) { flash('✗ ' + r.error); return; }
    if (r && r.id) LOADED.set(blockId, r.id);
    setNm(''); setSaving(false); setRev(x => x + 1); flash('Saved as a block preset');
  };
  const setDef = async p => { await api(encodeURIComponent(btype) + '/' + encodeURIComponent(p.id) + '/set-default', { method: 'POST' }); setRev(x => x + 1); };
  const del = async p => {
    if (armDel !== p.id) { setArmDel(p.id); setTimeout(() => setArmDel(a => a === p.id ? null : a), 2500); return; }
    setArmDel(null);
    await api(encodeURIComponent(btype) + '/' + encodeURIComponent(p.id), { method: 'DELETE' }); setRev(x => x + 1);
  };
  const row = p => html`<div class=${cls('bp2-row', cur && p.id === cur.id && 'on')} key=${p.id}
      title=${'load « ' + p.name + ' » — applies to ALL scenes (clears this block\'s scene overrides)'} onClick=${() => load(p)}>
    <span class="bp2-nm"><span>${esc(p.name)}</span><small>${esc(sig ? sig(p.params) : '')}</small></span>
    ${cur && p.id === cur.id && modified ? html`<span class="bp2-mod">modified</span>` : ''}
    ${p.id === effDef ? html`<span class="bp2-tag def" title="loaded when this block is added on this lane">default</span>`
      : !p.factory ? html`<span class="bp2-tag mine">mine</span>` : ''}
    ${!p.factory ? html`<span class="bpl-acts" onClick=${e => e.stopPropagation()}>
        ${p.id !== effDef ? html`<i title="make it the default for this instrument" onClick=${() => setDef(p)}>●</i>` : ''}
        <i class=${cls(armDel === p.id && 'arm')} title=${armDel === p.id ? 'tap again to delete' : 'delete this block preset'} onClick=${() => del(p)}>${armDel === p.id ? '?' : '✕'}</i>
      </span>` : ''}
  </div>`;
  return html`<div class="bp2">
    <div class="bp2-col">
      <div class="bp2-top">
        <input class="bp2-q" placeholder=${'Search ' + list.length + ' presets'} value=${q} onInput=${e => setQ(e.target.value)} />
        <button class="bp2-scope" title="this lane's instrument, or every instrument"
          onClick=${() => setScope(s => s === 'inst' ? 'all' : 'inst')}>${scope === 'inst' ? (INST_LB[inst] || inst) : 'All'}</button>
      </div>
      <div class="bp2-list">
        ${!data ? html`<div class="bp2-empty">Loading…</div>` : ''}
        ${data && !shown.length ? html`<div class="bp2-empty">No preset matches.${scope === 'inst' ? ' Try All.' : ''}</div>` : ''}
        ${shown.map(row)}
      </div>
    </div>
    <div class="bp2-main">
      <div class="bp2-face">${children}</div>
      <div class="bp2-foot">
        ${saving ? html`
          <input class="bp2-name" placeholder="preset name…" value=${nm} onInput=${e => setNm(e.target.value)} onKeyDown=${e => e.key === 'Enter' && save()} />
          <select class="bp2-inst" value=${svInst} onChange=${e => setSvInst(e.target.value)}>${INSTS.map(i => html`<option value=${i} selected=${i === svInst}>${INST_LB[i]}</option>`)}</select>
          <button class="bp2-btn" onClick=${() => setSaving(false)}>Cancel</button>
          <button class="bp2-btn pri" disabled=${!nm.trim()} onClick=${save}>Save</button>`
        : html`
          <span class="muted">Preset</span>
          <b class="bp2-cur">${cur ? esc(cur.name) : 'none'}</b>
          ${modified ? html`<span class="bp2-mod">modified •</span>` : ''}
          ${msg ? html`<span class="bp2-msg">${esc(msg)}</span>` : ''}
          <span class="grow"></span>
          ${modified ? html`<button class="bp2-btn" title="back to the preset's settings" onClick=${() => load(cur)}>↺ Revert</button>` : ''}
          <button class="bp2-btn pri" title="save this block's settings as a block preset — reusable in any golem preset"
            onClick=${() => { setNm(modified && cur ? cur.name + ' 2' : ''); setSaving(true); }}>Save as…</button>`}
      </div>
    </div>
  </div>`;
}
