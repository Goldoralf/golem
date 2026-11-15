// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Kits (hub Library ▸ Drums) — docs/drums-library.md, maquette validée le 2026-11-14 : les BATTERIES et les
// kits de PADS dans un seul onglet (ils étaient deux, « Drums » et « Kits »), en cartes DESSINÉES par golem-fx
// (drumKit : jazz, rock, metal, vintage, électronique, hybride ; padKit : un contrôleur 4×4), rangées par origine —
// « Ships with golem » et « Yours » plutôt qu'un badge. Toucher une batterie la fait ENTENDRE (sa démo : une phrase de
// référence jouée par le kit, bridge/drum_preview.py) et ouvre sa fiche : les quatre démos, un groove de la
// bibliothèque sur ce kit, « Use this kit ». Un kit de pads s'écoute pad par pad.
// Ce qui ne change pas : les batteries d'usine arrivent avec le rack (lecture seule) ; une batterie IMPORTÉE (dossier,
// clé USB, URL : drums-import.js) reste sur ce golem et se supprime ; un kit de pads s'importe (.golemkit) et s'exporte.
import { useFactoryShow } from './factory-show.js';
import { html, useState, useRef, useAsync, cls, esc, setTopAction, setSubToolbar, useEffect, useRev, saveClick, openInDesigner } from './lib.js';
import { DrumImportSheet } from './drums-import.js';
import { useVisuals, Drawing, GP } from './tones-ui.js';
import { useClip, Mark, ClipBar, dur } from './keys-ui.js';
import { usePlayIt, PlayBanner, ActionBar } from './library-actions.js';

const kitSvg = (k, opts) => { const P = GP(); if (!P || !P.drumKit) return '';
  return k.type === 'pads'
    ? P.padKit({ title: k.name, pads: (k.pads || []).filter(p => p.sample).slice(0, 16).map(p => ({ label: String(p.note) })), ...opts })
    : P.drumKit({ type: k.type, title: k.name, ...opts }); };
const REF_NAMES = ['rock', 'funk', 'jazz', 'metal'];
const firstClip = k => { const c = (k.demo && k.demo.clips) || {}; const r = Object.keys(c)[0]; return r ? { ...c[r], ref: r } : null; };
const clipOf = (k, ref) => { const c = ((k.demo && k.demo.clips) || {})[ref]; return c && { sound: k.id + ':' + ref, clip: c.clip, seconds: c.seconds,
  title: k.name + ' · ' + (c.name || ref.split('/').pop()), phrase: (c.name || ref.split('/').pop()) + ' phrase' }; };

export function KitsPage() {
  const facShow = useFactoryShow();
  const [tick, setTick] = useState(0);
  const libRev = useRev('library_rev');
  const { data } = useAsync(() => fetch('/api/drums/kits').then(r => r.json()), [tick, libRev]);
  const vis = useVisuals();
  const cl = useClip();
  const [fam, setFam] = useState('all');
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState(null);
  const [menu, setMenu] = useState(false);
  const [addSheet, setAddSheet] = useState(() => /[?&]drumadd=1/.test(location.search));
  const kitFileRef = useRef(null);
  const reload = () => setTick(t => t + 1);
  useEffect(() => {
    setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${() => setMenu(m => !m)}>+ Import</button></div>`);
    return () => setTopAction(null);
  }, []);
  useEffect(() => {
    setSubToolbar(html`<input class="search" type="search" placeholder="Search kit…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      ${busy ? html`<span class="syn-busy">${esc(busy)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [busy]);
  const importKit = async f => {
    setBusy('importing…');
    const r = await fetch('/api/kit/import', { method: 'POST', body: f }).then(x => x.json()).catch(e => ({ error: String(e) }));
    setBusy(r.ok ? null : (r.error || 'import failed'));
    if (r.ok) reload();
  };
  // l'usine masquée (Settings ▸ Content ▸ Factory) : les kits de PADS d'usine seulement ; les batteries du rack restent
  const all = ((data && data.kits) || []).filter(k => !(k.factory && k.type === 'pads' && facShow.kits === false));
  const shown = all.filter(k => (fam === 'all' || (fam === 'pads') === (k.type === 'pads')) && (!q || (k.name || '').toLowerCase().includes(q)));
  const open = all.find(k => k.id === sel);
  const sheets = html`${addSheet ? html`<${DrumImportSheet} onClose=${() => setAddSheet(false)} onInstalled=${() => reload()} />` : ''}
    <input ref=${kitFileRef} type="file" accept=".golemkit,.zip" style="display:none"
      onChange=${e => { if (e.target.files[0]) importKit(e.target.files[0]); e.target.value = ''; }} />
    ${menu ? html`<div class="dk-menu" role="menu">
      <button role="menuitem" onClick=${() => { setMenu(false); setAddSheet(true); }}><b>A drum set</b><span>a DrumGizmo or SFZ kit, from a folder, a USB key or a URL · stays on this golem</span></button>
      <button role="menuitem" onClick=${() => { setMenu(false); kitFileRef.current && kitFileRef.current.click(); }}><b>A pad kit</b><span>a .golemkit file</span></button>
    </div>` : ''}`;
  if (open) return html`<div class="library tn-page">${sheets}<${KitDetail} k=${open} vis=${vis} cl=${cl} all=${all}
    onClose=${() => setSel(null)} onChanged=${() => { setSel(null); reload(); }} /></div>`;

  const touch = k => { setSel(k.id); const c = firstClip(k); if (c && !cl.playing({ sound: k.id + ':' + c.ref })) cl.play(clipOf(k, c.ref)); };
  const card = k => { const c = firstClip(k), ready = k.demo && k.demo.status === 'ready';
    return html`<button class=${cls('dk-card', cl.st.cur && cl.st.cur.sound.startsWith(k.id + ':') && cl.st.playing && 'on', k.available === false && 'dim')}
      aria-label=${k.name} onClick=${() => touch(k)}>
      <div class="dk-art">${vis ? html`<${Drawing} svg=${kitSvg(k, { compact: true })} align="xMidYMid" />` : ''}</div>
      <span class="dk-sub">${k.type === 'pads' ? html`<span class="ky-play">▶</span> ${(k.pads || []).filter(p => p.sample).length} pads`
        : html`${c && ready ? html`<span class="dk-demo ok">▶ Demo</span>` : html`<span class="dk-demo">Demo soon</span>`}
          <span class="dk-eng">${k.engine}${k.mics ? ' · ' + k.mics + ' mics' : ''}${k.imported ? ' · this golem only' : ''}</span>`}</span>
    </button>`; };
  const section = (title, list) => list.length ? html`<h6 class="dk-h">${title}</h6><div class="dk-grid">${list.map(card)}</div>` : '';
  const sets = shown.filter(k => k.type !== 'pads'), pads = shown.filter(k => k.type === 'pads');
  const n = t => all.filter(k => t === 'all' || (t === 'pads') === (k.type === 'pads')).length;
  return html`<div class="library tn-page">${sheets}
    <div class="tn-col ky-col">
      <div class="ky-styles">${[['all', 'All'], ['sets', 'Drum sets'], ['pads', 'Pads']].map(([k, lb]) =>
        html`<button class=${cls('ky-sty', fam === k && 'on')} onClick=${() => setFam(k)}>${lb} <em>${n(k)}</em></button>`)}</div>
      <div class="dk-scroll">
        ${section('Drum sets · ships with golem', sets.filter(k => k.factory))}
        ${section('Drum sets · yours', sets.filter(k => !k.factory))}
        ${section('Pads · ships with golem', pads.filter(k => k.factory))}
        ${section('Pads · yours', pads.filter(k => !k.factory))}
        ${!shown.length ? html`<div class="empty">No kit here. Tap <b>+ Import</b> to add a drum set or a pad kit.</div>` : ''}
      </div>
      <${ClipBar} cl=${cl} hint="Touch a kit to hear it: the same four phrases (rock, funk, jazz, metal) play through every drum set." />
    </div></div>`;
}

function KitDetail({ k, vis, cl, all, onClose, onChanged }) {
  const pads = k.type === 'pads';
  // Play it / Add to… (docs/library-play.md) : le kit joué des pads ou de la batterie électronique branchés
  const item = { kit: k.id };
  const pi = usePlayIt(item);
  const rock = clipOf(k, 'drums/rock');
  const { data: gd } = useAsync(() => pads ? Promise.resolve(null) : fetch('/api/grooves').then(r => r.json()), [k.id]);
  const [gq, setGq] = useState('');
  const [tempo, setTempo] = useState('patch');
  const [hearing, setHearing] = useState(null);       // {gid, phase, error}
  const [armDel, setArmDel] = useState(false);
  const del = async () => {
    if (!armDel) { setArmDel(true); setTimeout(() => setArmDel(false), 2500); return; }
    await fetch('/api/kit/' + encodeURIComponent(k.id), { method: 'DELETE' }).catch(() => null);
    onChanged();
  };
  // un groove sur ce kit : rendu au premier toucher (quelques secondes), joué ensuite
  const hear = async g => {
    setHearing({ gid: g.id, phase: 'render' });
    const r = await fetch('/api/groove/' + encodeURIComponent(g.id) + '/hear', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kit: k.id, tempo }) }).then(x => x.json()).catch(e => ({ error: String(e) }));
    const play = st => { setHearing({ gid: g.id, phase: st.phase, error: st.error });
      if (st.phase === 'ready') cl.play({ sound: 'gok:' + st.key, clip: st.clip, title: g.name + ' on ' + k.name, phrase: r.bpm ? r.bpm + ' BPM' : '' }); };
    if (r.error) return setHearing({ gid: g.id, phase: 'error', error: r.error });
    if (r.phase !== 'render') return play(r);
    const t = setInterval(async () => { const st = await fetch('/api/groove-hear').then(x => x.json()).catch(() => null);
      if (!st || st.key !== r.key || st.phase === 'render') return; clearInterval(t); play(st); }, 800);
  };
  const grooves = ((gd && gd.grooves) || []).filter(g => !gq || g.name.toLowerCase().includes(gq));
  const padSound = p => ({ sound: k.id + ':pad' + p.note, clip: '/api/sample?file=' + encodeURIComponent(p.sample), title: k.name + ' · pad ' + p.note,
    phrase: (p.sample || '').split('/').pop() });
  return html`<div class="tn-col ky-col">
    <div class="ky-detail">
      <div class="ky-left wide">
        <button class="tn-back" onClick=${onClose}>‹ Kits</button>
        <div class="ky-art big">${vis ? html`<${Drawing} svg=${kitSvg(k, {})} align="xMidYMid" />` : ''}</div>
        <div class="ky-title"><b>${esc(k.name)}</b><span>${k.engine}${k.mics ? ' · ' + k.mics + ' mics' : ''} · ${k.factory ? 'ships with golem' : k.imported ? 'imported · this golem only' : 'yours'}${k.hint ? ' · ' + esc(k.hint) : ''}</span></div>
        ${pads ? '' : html`<div class="ky-card"><h6 class="ky-h6">Demo · the same four phrases for every kit</h6>
          ${k.demo && Object.keys(k.demo.clips || {}).length
            ? html`<div class="dk-refs">${REF_NAMES.map(r => { const s = clipOf(k, 'drums/' + r);
                return s ? html`<button class=${cls('ky-row', cl.playing(s) && 'on')} onClick=${() => cl.play(s)}><${Mark} on=${cl.playing(s)} s=${{ status: 'ready' }} /><span class="nm">${r[0].toUpperCase() + r.slice(1)}</span><em>${dur(s)}</em></button>` : ''; })}</div>`
            : html`<div class="muted">${k.available === false ? esc(k.unavailable_why || 'Not on this machine.') : k.factory ? 'Its demo comes with the factory demos (Settings ▸ Content).' : 'Its demo renders when the rack is idle (10 minutes without anyone playing).'}</div>`}
        </div>`}
      </div>
      <div class="ky-right">
        ${pads ? html`<div class="ky-card dk-padcard"><h6 class="ky-h6">Pads · touch one to hear it</h6>
          <div class="dk-pads">${(k.pads || []).filter(p => p.sample).map(p => { const s = padSound(p);
            return html`<button class=${cls('dk-pad', cl.playing(s) && 'on')} onClick=${() => cl.play(s)} title=${s.phrase}>
              <b>${p.note}</b><span>${esc(s.phrase.replace(/\.[a-z0-9]+$/i, ''))}</span></button>`; })}</div></div>`
        : html`<div class="ky-card dk-gok">
          <div class="dk-gok-hd"><h6 class="ky-h6">A groove on this kit</h6>
            <div class="tn-seg">${[['file', 'File'], ['half', 'Half'], ['patch', 'Patch']].map(([v, lb]) =>
              html`<button class=${tempo === v ? 'on' : ''} onClick=${() => setTempo(v)} title=${v === 'file' ? "the groove's own tempo" : v === 'half' ? 'half its tempo' : "the tempo of the patch that plays"}>${lb}</button>`)}</div>
            <input class="search" type="search" placeholder="Search groove…" onInput=${e => setGq(e.target.value.trim().toLowerCase())} /></div>
          <div class="dk-glist">${grooves.map(g => { const h = hearing && hearing.gid === g.id ? hearing : null;
            return html`<button class=${cls('ky-row', h && h.phase === 'ready' && cl.st.playing && 'on')} onClick=${() => hear(g)}>
              ${h && h.phase === 'render' ? html`<span class="ky-dm wait">◌</span>` : html`<span class="ky-play">▶</span>`}
              <span class="nm">${esc(g.name)}${h && h.phase === 'render' ? html` <small class="wait">rendering…</small>` : h && h.phase === 'error' ? html` <small class="ko">${esc(h.error)}</small>` : ''}</span>
              <em>${g.meter} · ${g.bars} bar${g.bars > 1 ? 's' : ''} · ${g.factory ? 'golem' : 'yours'}</em></button>`; })}</div>
          <div class="muted dk-note">A groove is rendered on this kit the first time you touch it (a few seconds), then plays at once.</div>
        </div>`}
        <div class="dk-acts">
          ${k.factory ? '' : k.imported
            ? html`<button class=${cls('mini', armDel && 'arm')} onClick=${del}>${armDel ? 'Tap again: delete it and its samples' : 'Delete'}</button>`
            : html`<a class="mini" href=${'/api/kit/' + encodeURIComponent(k.id) + '/export'} onClick=${saveClick('/api/kit/' + encodeURIComponent(k.id) + '/export')}>Export</a>
              <button class=${cls('mini', armDel && 'arm')} onClick=${del}>${armDel ? 'Tap again to delete' : 'Delete'}</button>`}
        </div>
      </div>
    </div>
    <${PlayBanner} pi=${pi} />
    <${ActionBar} pi=${pi} item=${item} onListen=${rock ? () => { if (pi.st.on) pi.stop(); cl.play(rock); } : null} listening=${rock && cl.playing(rock)}
      extra=${pads ? '' : html`<button class="la-btn" disabled=${k.available === false} onClick=${() => openInDesigner(null, 'cfg', { kind: 'drums-kit', kit: k.id })}>Use in my drum machine</button>`} />
    <${ClipBar} cl=${cl} hint=${pads ? 'Touch a pad to hear its sample.' : 'Touch a phrase or a groove to hear it on this kit.'} />
  </div>`;
}
