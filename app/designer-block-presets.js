// SPDX-License-Identifier: GPL-3.0-or-later
// L'ONGLET « PRESETS » DU TIROIR D'UN BLOC (mockups/block-presets-list.html, validée le 2026-10-11) : à gauche
// le réglage courant et sa sauvegarde en PRESET DE BLOC (pas un preset du golem : la phrase le dit) ; à droite la
// liste, avec la grammaire de la liste des VST — recherche, Guitar / All instruments, cases Factory / Mine, Recent,
// accordéon par instrument, une ligne = nom · signature · défaut · actions. Les presets viennent de
// /api/block-presets/<type> (library/block-presets/<type>/*.json) ; charger un preset écrit les paramètres de base
// du bloc et efface ses surcharges de scène (docs/archive/block-sheets.md §5).
import { html, useState, useAsync, cls, esc } from './lib.js';
import { fmtVal } from './designer-widgets.js';
import { INSTS, INST_LB, filterPresets, groupByInst, effectiveDefault, loadRecent, pushRecent, pickRecent } from './block-presets-model.mjs';

const api = (path, opts) => fetch('/api/block-presets/' + path, opts).then(r => r.json()).catch(() => null);

export function BlockPresetsList({ btype, inst, defs, current, sig, onLoad, blockName }) {
  const [rev, setRev] = useState(0);
  const { data } = useAsync(() => api(encodeURIComponent(btype)), [btype, rev]);
  const list = (data && data.presets) || [];
  const [q, setQ] = useState('');
  const [scope, setScope] = useState('inst');
  const [flags, setFlags] = useState({ factory: true, mine: true });
  const [open, setOpen] = useState(() => new Set([inst]));
  const [recent, setRecent] = useState(() => loadRecent(btype));
  const [nm, setNm] = useState('');
  const [svInst, setSvInst] = useState(inst);
  const [armDel, setArmDel] = useState(null);
  const [msg, setMsg] = useState('');
  const flash = m => { setMsg(m); setTimeout(() => setMsg(''), 2500); };
  const searching = !!q.trim();
  const shown = filterPresets(list, { inst, scope, q, factory: flags.factory, mine: flags.mine, sig });
  const groups = groupByInst(shown, inst);
  const effDef = effectiveDefault(list, inst);
  const rec = searching ? [] : pickRecent(shown, recent);
  const nF = list.filter(p => p.factory).length, nM = list.length - nF;
  const load = p => { onLoad(p.params); setRecent(pushRecent(btype, p.id)); flash('✓ « ' + p.name + ' » loaded — all scenes'); };
  const save = async () => {
    const name = nm.trim(); if (!name) return;
    const r = await api(encodeURIComponent(btype), { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, params: current, inst: svInst }) });
    if (r && r.error) { flash('✗ ' + r.error); return; }
    setNm(''); setRev(x => x + 1); setFlags(f => ({ ...f, mine: true })); flash('💾 block preset saved');
  };
  const setDef = async p => { await api(encodeURIComponent(btype) + '/' + encodeURIComponent(p.id) + '/set-default', { method: 'POST' }); setRev(x => x + 1); };
  const del = async p => {
    if (armDel !== p.id) { setArmDel(p.id); setTimeout(() => setArmDel(a => a === p.id ? null : a), 2500); return; }
    setArmDel(null);
    await api(encodeURIComponent(btype) + '/' + encodeURIComponent(p.id), { method: 'DELETE' }); setRev(x => x + 1);
  };
  const toggle = i => setOpen(s => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const allOpen = groups.every(g => open.has(g.inst));
  const row = p => html`<div class=${cls('vh-pl', 'bpl-row', p.id === effDef && 'def')} key=${p.id} title=${'load « ' + p.name + ' » — applies to ALL scenes (clears this block\'s scene overrides)'}
      onClick=${() => load(p)}>
    <span class=${cls('vh-ic', !p.factory && 'ins')}>${p.factory ? '◈' : '★'}</span>
    <span class="vh-nm bpl-nm"><span>${esc(p.name)}</span><small>${esc(sig ? sig(p.params) : '')}</small></span>
    ${p.id === effDef ? html`<span class="bpl-tag def" title="loaded when this block is added on this lane">● default</span>`
      : p.factory ? html`<span class="bpl-tag">factory</span>` : ''}
    ${!p.factory ? html`<span class="bpl-acts" onClick=${e => e.stopPropagation()}>
        ${p.id !== effDef ? html`<i title="make it the default for this instrument" onClick=${() => setDef(p)}>●</i>` : ''}
        <i class=${cls(armDel === p.id && 'arm')} title=${armDel === p.id ? 'tap again to delete' : 'delete this block preset'} onClick=${() => del(p)}>${armDel === p.id ? '?' : '✕'}</i>
      </span>` : ''}
  </div>`;
  return html`<div class="bpl">
    <div class="bpl-left">
      <div class="bpl-card"><h3>Current settings</h3>
        ${(defs || []).slice(0, 8).map(pm => html`<div class="bpl-kv"><span>${esc(pm.name || pm.label || pm.id)}</span><b>${esc(fmtVal(current[pm.id], pm))}${pm.unit ? ' ' + esc(pm.unit) : ''}</b></div>`)}
        ${(defs || []).length > 8 ? html`<div class="bpl-kv muted"><span>…</span><b>${(defs || []).length - 8} more</b></div>` : ''}
      </div>
      <div class="bpl-card bpl-save"><h3>Save as a block preset</h3>
        <input value=${nm} placeholder="preset name…" onInput=${e => setNm(e.target.value)} onKeyDown=${e => e.key === 'Enter' && save()} />
        <div class="bpl-row2"><span class="muted">for</span>
          <select value=${svInst} onChange=${e => setSvInst(e.target.value)}>${INSTS.map(i => html`<option value=${i} selected=${i === svInst}>${INST_LB[i]}</option>`)}</select></div>
        <button class="bpl-savebtn" disabled=${!nm.trim()} onClick=${save}>💾 Save${nm.trim() ? ' « ' + esc(nm.trim()) + ' »' : ''}</button>
        <p class="bpl-note"><b>A block preset</b> is this ${esc(blockName || 'block')}'s settings only, reusable in any golem preset. It does not save the song, the lanes or the other blocks.</p>
        ${msg ? html`<div class="bpl-msg">${esc(msg)}</div>` : ''}
      </div>
    </div>
    <div class="bpl-list">
      <div class="bpl-top">
        <div class="vh-srow"><input class="vst-host-search" placeholder="Search block presets" value=${q} onInput=${e => setQ(e.target.value)} />
          <span class="vh-count"><b>${shown.length}</b> of ${list.length}</span></div>
        <div class="vst-host-filters">
          <div class="tb-seg"><button class=${cls(scope === 'inst' && 'on')} onClick=${() => setScope('inst')}>${INST_LB[inst] || inst}</button>
            <button class=${cls(scope === 'all' && 'on')} onClick=${() => setScope('all')}>All instruments</button></div>
          <button class=${cls('vh-fmt', flags.factory && 'on')} onClick=${() => setFlags(f => ({ ...f, factory: !f.factory }))}><span class="vh-box"></span>Factory <small>${nF}</small></button>
          <button class=${cls('vh-fmt', flags.mine && 'on')} onClick=${() => setFlags(f => ({ ...f, mine: !f.mine }))}><span class="vh-box"></span>Mine <small>${nM}</small></button>
        </div>
      </div>
      ${!data ? html`<div class="di-group">Loading…</div>` : ''}
      ${data && !shown.length ? html`<div class="vh-empty">No block preset matches. Clear the search or tick another box.</div>` : ''}
      ${rec.length ? html`<div class="vh-sect">Recent</div><div class="vh-grid vh-recent bpl-grid">${rec.map(row)}</div>` : ''}
      ${!searching && groups.length ? html`<div class="vh-sect">By instrument · ${groups.length}
        <button class="vh-link" onClick=${() => setOpen(allOpen ? new Set() : new Set(groups.map(g => g.inst)))}>${allOpen ? 'Collapse all' : 'Expand all'}</button></div>` : ''}
      ${groups.map(g => { const isOpen = searching || open.has(g.inst);
        return html`<div class=${cls('vh-vd', isOpen && 'open')} key=${g.inst}>
          <button class="vh-vd-h" onClick=${() => !searching && toggle(g.inst)} aria-expanded=${isOpen}>
            <span class="vh-car">▸</span><b>${esc(g.label)}</b><span class="vh-kinds">${[g.factory && g.factory + ' factory', g.mine && g.mine + ' mine'].filter(Boolean).join(' · ')}</span><span class="vh-n">${g.items.length}</span></button>
          ${isOpen ? html`<div class="vh-grid bpl-grid">${g.items.map(row)}</div>` : ''}
        </div>`; })}
    </div>
  </div>`;
}
