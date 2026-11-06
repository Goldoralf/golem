// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Kits (hub Library ▸ Drums) — bibliothèque des kits (docs/drums-kit.md) : grille des kits
// (badge role/engine, pads garnis pour rs5k), + Add = import .golemkit (kits de PADS), suppression
// sûre. Les BATTERIES d'usine (avldrums / drumgizmo / sfz) arrivent AVEC le rack (graines versionnées,
// docs/drums-kit.md §2, 2026-09-15) : lecture seule — ni édition, ni suppression. Depuis le 2026-10-11
// (docs/drums-kit.md §8) une batterie peut aussi être IMPORTÉE par le rack — « + Add » en mode Drums
// ouvre la feuille de drums-import.js (dossier, clé USB, URL) ; celle-là porte « MINE · this golem only »
// et se supprime (son dossier part avec elle). Les SAMPLES ont leur onglet ; l'ÉDITION d'un kit rs5k vit
// dans le Designer.
import { useFactoryShow, keepFactory } from './factory-show.js';
import { html, useState, useRef, useAsync, cls, esc, setTopAction, setSubToolbar, useEffect, useRev, saveClick } from './lib.js';
import { WaveTrack } from './wavetrack.js';   // même mini-DAW que Recordings : voir ET écouter
import { DrumImportSheet, gb } from './drums-import.js';

export function KitsPage({ mode = 'kits' } = {}) {
  const facShow = useFactoryShow();          // l'usine masquée par sorte (Settings ▸ Content ▸ Factory)
  const drums = mode === 'drums';                      // Drums = batteries d'usine, lecture seule ; Kits = pads
  const [tick, setTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(() => fetch('/api/kits').then(r => r.json()), [tick, libRev]);
  const [busy, setBusy] = useState(null);
  const [armDel, setArmDel] = useState(null);        // 2-tap de suppression (kit ou sample)
  // ACCORDÉON (2026-10-13 : « ça prendra moins de place ») : une carte = sa ligne de titre ; un tap l'ouvre.
  // Le corps fermé n'est PAS rendu (pas de `hidden` : une autre feuille peut le réafficher, CLAUDE.md).
  const [open, setOpen] = useState({});
  const [q, setQ] = useState('');
  const [playing, setPlaying] = useState(null);       // un seul pad à la fois
  const kitFileRef = useRef(null);
  const [addSheet, setAddSheet] = useState(() => /[?&]drumadd=1/.test(location.search));   // ?drumadd=1 : la feuille ouverte (dev)
  useEffect(() => {
    setTopAction(drums
      ? html`<div class="tb-action"><button class="primary tb-new" title="add a drum kit from a folder, a USB key or a URL — this golem only" onClick=${() => setAddSheet(true)}>+ Add</button></div>`
      : html`<div class="tb-action"><button class="primary tb-new" title="import a .golemkit pad kit" onClick=${() => kitFileRef.current && kitFileRef.current.click()}>+ Add</button></div>`);
    return () => setTopAction(null);
  }, [drums]);

  // usine masquée : les kits de PADS d'usine ne sont pas rendus ; les batteries du rack (moteurs) restent
  const kits = ((data && data.kits) || []).filter(k => !(k.factory && k.role !== 'drum' && (k.engine || 'rs5k') === 'rs5k' && facShow.kits === false));
  const reload = () => setTick(t => t + 1);
  // Drums = les BATTERIES (d'usine ou importées : un moteur batterie) ; Kits = les kits de pads (rs5k)
  // le RÔLE du kit, pas son origine : depuis le 2026-10-13 l'usine livre aussi des kits de PADS (House, Lo-fi, Trap)
  const isDrum = k => k.role === 'drum' || ['sfz', 'avldrums', 'drumgizmo'].includes(k.engine);
  const shownKits = kits.filter(k => isDrum(k) === drums
    && (!q || (k.name || '').toLowerCase().includes(q)));
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder=${drums ? 'Search drums…' : 'Search kit…'}
        onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      ${busy ? html`<span class="syn-busy">${esc(busy)}</span>` : ''}`);
    return () => setSubToolbar(null);
  }, [busy]);

  const importKit = async f => {
    setBusy('importing…');
    const r = await fetch('/api/kit/import', { method: 'POST', body: f }).then(x => x.json()).catch(e => ({ error: String(e) }));
    setBusy(r.ok ? null : (r.error || 'import failed'));
    if (r.ok) reload();
  };
  const delKit = async id => {
    if (armDel !== 'k:' + id) { setArmDel('k:' + id); setTimeout(() => setArmDel(a => a === 'k:' + id ? null : a), 2500); return; }
    setArmDel(null);
    await fetch('/api/kit/' + encodeURIComponent(id), { method: 'DELETE' }).catch(() => null);
    reload();
  };
  // Grammaire de /songs/recordings : carte PLEINE LARGEUR, contenu toujours visible,
  // une ligne par pad avec sa forme d'onde et son bouton play. Un kit rs5k s'écoute pad par pad ;
  // un kit avldrums/sfz n'a AUCUN fichier à montrer (le son vient du moteur) — on le DIT au lieu
  // d'afficher une carte vide qui laisserait croire à un kit cassé.
  const aud = f => '/api/sample?file=' + encodeURIComponent(f);
  const pks = f => '/api/peaks?file=' + encodeURIComponent(f);
  const KitCard = k => {
    const eng = k.engine || 'rs5k', role = k.role || 'pad';
    const filled = (k.pads || []).filter(p => p.sample);
    const total = (data.default_notes || []).length || 8;
    const imp = k.imported && typeof k.imported === 'object' ? k.imported : null;
    const impLine = imp ? 'Imported ' + new Date((imp.at || 0) * 1000).toISOString().slice(0, 10) + (imp.from ? ' from ' + imp.from : '') + (imp.bytes ? ' · ' + gb(imp.bytes) : '') + ' — ' : '';
    const meta = eng === 'avldrums' ? 'avldrums · ' + (k.bank || '—')
      : eng === 'sfz' ? 'sfz · ' + ((k.sfz || '').split('/').pop() || '—')
      : eng === 'drumgizmo' ? 'drumgizmo · ' + ((k.drumkit || '').split('/').pop() || '—') + ' · ' + (k.mix || []).length + ' mics'
      : `${filled.length}/${total} pads`;
    const isOpen = !!open[k.id];
    return html`<div class=${cls('rec-card', 'kit-acc', isOpen && 'open', filled.length > 1 && 'multi')}>
      <div class="rec-head kit-acc-head" onClick=${e => { if (e.target.closest('button, a')) return;
          setOpen(o => ({ ...o, [k.id]: !o[k.id] })); }} title=${isOpen ? 'fold' : 'show the pads'}>
        <span class="kit-acc-chev">${isOpen ? '▾' : '▸'}</span>
        <span class="rec-glyph">${role === 'drum' ? '🥁' : '⋮⋮'}</span>
        <span class="rec-title">
          <span class="rec-name" title=${esc(k.name)}>${esc(k.name)}</span>
          <span class=${cls('kit-badge', 'e-' + eng)}>${eng}</span>
          <span class="rec-ctx">${esc(meta)}</span>
        </span>
        ${k.available === false ? html`<span class="kit-badge kit-unavail" title=${esc(k.unavailable_why || '')}>not on this machine</span>` : ''}
        ${k.factory
          ? html`<span class="slv-own" title="ships with golem — not deletable">◆ factory</span>`
          : imp
          ? html`<span class="kit-badge kit-mine" title="imported by this rack — its samples stay here; only a card goes to golem.fm">mine</span>
            <span class="kit-factory kit-local" title="the samples never leave this golem — golem.fm only has the card">this golem only</span>
            <button class=${cls('rec-del', armDel === 'k:' + k.id && 'arm')}
              title=${armDel === 'k:' + k.id ? 'tap again to delete (its samples too)' : 'delete this kit and its samples'}
              onClick=${() => delKit(k.id)}>${armDel === 'k:' + k.id ? 'sure?' : '🗑'}</button>`
          : html`<a class="wv-dl edit-only" href=${'/api/kit/' + encodeURIComponent(k.id) + '/export'} onClick=${saveClick('/api/kit/' + encodeURIComponent(k.id) + '/export')} title="export as .golemkit">⬇</a>
            <button class=${cls('rec-del', armDel === 'k:' + k.id && 'arm')}
              title=${armDel === 'k:' + k.id ? 'tap again to delete' : 'delete kit'}
              onClick=${() => delKit(k.id)}>${armDel === 'k:' + k.id ? 'sure?' : '🗑'}</button>`}
      </div>
      ${isOpen ? html`<div class="rec-body">
        ${eng === 'rs5k' ? (filled.length ? filled.map((pd, i) => { const key = k.id + ':' + pd.note;
          return html`<${WaveTrack} key=${key} audio=${aud(pd.sample)} peaks=${pks(pd.sample)}
            name=${'Pad ' + pd.note} label=${pd.sample.split('/').pop()} num=${i + 1}
            tag=${pd.mode || 'gate'} on=${playing === key}
            onToggle=${go => setPlaying(go ? key : null)} />`; })
          : html`<div class="rec-meta muted">No sample on any pad yet — assign them in the Designer.</div>`)
        : html`<div class="rec-meta muted">${impLine}${eng === 'avldrums'
            ? 'Acoustic engine — the sound is synthesised from the « ' + esc(k.bank || '—') + ' » bank' + (k.hint ? ' (' + esc(k.hint) + ')' : '') + ', there is no sample file to preview here. Play it from a Drums block.'
            : eng === 'drumgizmo'
            ? 'Multi-mic drum kit (DrumGizmo)' + (k.hint && !imp ? ' — ' + esc(k.hint) : '') + ' — one channel per mic, mixed in the Drums block; no per-pad sample to preview here.'
            : 'SFZ kit (sfizz) — the sound comes from the loaded soundfont' + (imp ? ', pieces read in the .sfz keys' : '') + '; no per-pad sample to preview here.'}${imp ? ' Card shared with golem.fm; samples stay here.' : ''}</div>`}
      </div>` : ''}
    </div>`;
  };

  return html`<div class="library">
    ${addSheet ? html`<${DrumImportSheet} onClose=${() => setAddSheet(false)} onInstalled=${() => reload()} />` : ''}
    <input ref=${kitFileRef} type="file" accept=".golemkit,.zip" style="display:none"
      onChange=${e => { if (e.target.files[0]) importKit(e.target.files[0]); e.target.value = ''; }} />
    <div class="lib-grid">
      ${shownKits.length ? html`<div class="rec-day"><div class="rec-grid">${shownKits.map(KitCard)}</div></div>`
        : html`<div class="empty">${drums ? html`No rack drums — they come back at the next start. Tap <b>+ Add</b> to import a DrumGizmo or SFZ kit.` : html`No pad kits yet — build one on golem.fm, or tap <b>+ Add</b> to import a <code>.golemkit</code>.`}</div>`}
    </div>

  </div>`;
}
