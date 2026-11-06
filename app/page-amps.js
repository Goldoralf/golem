// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Amps (hub Library) — parcours des amplis (centré ampli, jamais le contributeur).
// Grille PAGINÉE (no-scroll). Recherche + filtres sur UNE ligne (selects compacts).
// Photos : overlay library/catalog/images.json (tone id -> fichier sous /library/images/).
import { html, useState, useEffect, useRef, useAsync, cls, esc, safeHref, getCatalog, refreshCatalog, setTopAction, setSubToolbar, useRev } from './lib.js';
import { capText, archOf as archMatch } from './designer-model.js';
import { T3kModal } from './t3k-modal.js';

// 'bass' n'est PAS un style : c'est la famille (segmenté Guitar|Bass de la toolbar)
const STYLES = ['metal', 'rock', 'blues', 'jazz', 'funk'];
const GEAR_LABEL = { amp: 'Heads', 'amp-cab': 'Heads+Cab', cab: 'Cabs/IR', pedal: 'Pedals', outboard: 'Outboard' };
const ampName = t => t.amp || t.title || 'Tone';
// PRÊTS DU GROUPE (docs/library-loans.md) : un son prêté par un coéquipier se range comme les nôtres —
// il faut donc le DIRE sur sa carte, sinon rien ne distingue « à moi » de « prêté par alex ».
let _lent = null;
const lentMap = () => (_lent = _lent || fetch('/api/library/lent').then(r => r.json()).then(d => (d && d.by_catalog) || {}).catch(() => ({})));
const useLent = () => useAsync(lentMap, []).data || {};
export const lentLabel = row => {
  if (!row) return '';
  const w = (row.lent_by || [])[0] || {};
  const who = [w.owner, w.band].filter(Boolean).join(' · ');
  return row.state === 'no_longer_lent' ? `no longer lent${who ? ' (was ' + who + ')' : ''}` : `lent by ${who || 'a bandmate'}`;
};
// famille (section basse, QC-gap 1) : champ explicite (tones-index) sinon heuristique tag/style
// « Bass » en mot entier dans le nom compte aussi (« Behringer Bass V-Amp Pro » sortait sous Guitar, 15/09) —
// \bbass\b ne prend ni Bassman ni Bassbreaker. Miroir de bridge/tones_sync.family_of.
export const famOf = t => t.family || (((t.tags || []).includes('bass') || t.style === 'bass' || /\bbass\b/i.test(t.amp || t.title || '')) ? 'bass' : 'guitar');

// amplis NOMMÉS (archétypes effects.json amps[], champ brand) — la page les groupe PAR MARQUE
const ampIsBass = a => (a.roles || ['guitar']).includes('bass');

export function AmpsPage({ role, gears } = {}) {
  const [catTick, setCatTick] = useState(0);
  const libRev = useRev('library_rev');   // golem.fm a posé quelque chose : on recharge (bridge/arrivals.py)
  const { data } = useAsync(getCatalog, [catTick, libRev]);
  const { data: fxData } = useAsync(() => fetch('/api/effects').then(r => r.json()), []);
  const ampArch = (fxData && fxData.amps) || [];         // amplis nommés (archétypes)
  const [selArch, setSelArch] = useState(null);
  const lent = useLent();
  const { data: imgs } = useAsync(() => fetch('/library/catalog/images.json').then(r => r.ok ? r.json() : {}), []);
  const tones = (data && data.tones) || [];
  const imgOf = t => ((imgs && imgs.tones) || {})[String(t.id)];
  const [style, setStyle] = useState('all');
  const [chr, setChr] = useState('all');        // caractère de gain : clean / crunch / high-gain
  const [rig, setRig] = useState('all');        // nature de capture : amp (tête seule) / amp-cab (cab inclus)
  const [q, setQ] = useState('');
  const [sel, setSel] = useState(null);
  const [t3k, setT3k] = useState(false);        // modal + Add (TONE3000)
  // IMPORT FILES (docs/tone-import.md, 2026-10-24) : .nam, .gcap, IR .wav ou paquet .zip, un fichier par appel ; le
  // compte rendu dit ce qui est entré ET ce qui est resté dehors, avec sa raison — jamais un import muet
  const [imp, setImp] = useState(null);
  const importFiles = async event => {
    const files = [...(event.target.files || [])]; event.target.value = '';
    if (!files.length) return;
    let acc = { busy: true, done: 0, total: files.length, current: files[0].name, installed: [], skipped: [], warnings: [], ignored: 0 };
    setImp(acc);
    for (const file of files) {
      acc = { ...acc, current: file.name }; setImp(acc);
      let r;
      try {
        const response = await fetch('/api/tones/import?name=' + encodeURIComponent(file.name), { method: 'POST', body: file });
        r = await response.json();
        if (!response.ok) r = { skipped: [{ file: file.name, reason: r.error || 'refused' }] };
      } catch (e) { r = { skipped: [{ file: file.name, reason: 'could not reach golem' }] }; }
      // même id importé deux fois (le module dans son paquet ET seul) = une seule ligne, la dernière
      const fresh = r.installed || [];
      acc = { ...acc, done: acc.done + 1, installed: [...acc.installed.filter(i => !fresh.some(f => f.id === i.id)), ...fresh],
        skipped: [...acc.skipped, ...(r.skipped || [])], warnings: [...acc.warnings, ...(r.warnings || [])], ignored: acc.ignored + (r.ignored || 0) };
      setImp(acc);
    }
    setImp({ ...acc, busy: false });
    refreshCatalog(); setCatTick(v => v + 1);
  };
  const KIND = { tone: 'capture', module: 'module with live knobs', ir: 'cab IR' };
  const short = (list, n, row) => html`${list.slice(0, n).map(row)}${list.length > n ? html`<li class="muted">+ ${list.length - n} more</li>` : ''}`;
  const ImportSheet = () => html`<div class="sheet-scrim" onClick=${e => !imp.busy && e.target.classList.contains('sheet-scrim') && setImp(null)}>
    <div class="gf-sheet imp-sheet">
      <div class="gf-hd"><b>${imp.busy ? 'Importing…' : 'Import done'}</b>
        <span class="muted">${imp.busy ? `${imp.done + 1} / ${imp.total} · ${imp.current}` : `${imp.installed.length} added · ${imp.skipped.length} left out`}</span>
        <span class="grow"></span>${imp.busy ? '' : html`<button class="mini" onClick=${() => setImp(null)}>✕</button>`}</div>
      ${imp.installed.length ? html`<div class="imp-sec"><small class="muted">Added — find them in Tones and in the block pickers</small><ul>
        ${short(imp.installed, 7, i => html`<li>✓ <b>${esc(i.title || i.id)}</b> <span class="muted">${KIND[i.kind] || i.kind}${i.models > 1 ? ' · ' + i.models + ' models' : ''}</span></li>`)}</ul></div>` : ''}
      ${imp.warnings.length ? html`<div class="imp-sec"><ul>${short(imp.warnings, 3, w => html`<li class="warn">⚠ ${esc(w)}</li>`)}</ul></div>` : ''}
      ${imp.skipped.length ? html`<div class="imp-sec"><small class="muted">Left out</small><ul>
        ${short(imp.skipped, 6, s => html`<li><span class="imp-file">${esc(s.file.split('/').pop())}</span> <span class="muted">— ${esc(s.reason)}</span></li>`)}</ul></div>` : ''}
      ${!imp.busy && !imp.installed.length && !imp.skipped.length ? html`<p class="muted">Nothing to import in these files.</p>` : ''}
      ${imp.ignored ? html`<div class="gf-ft"><span>${imp.ignored} other file${imp.ignored > 1 ? 's' : ''} in the archives (notes, recordings) — not sounds, ignored</span></div>` : ''}
    </div></div>`;
  // « + Add » CONTEXTUEL dans la topbar : deux sources d'un ampli, UN bouton (2026-10-24). « Import module » était un
  // second bouton de la barre — il poussait l'onglet Tracks sous ⇅ I/O sous 1024 px, et disait la même chose que + Add
  // par une autre voie. TONE3000 d'abord (le geste courant), puis la capture golem (.gcap, golem-capture-1).
  const [addMenu, setAddMenu] = useState(false);
  const gcapIn = useRef(null);
  useEffect(() => {
    setTopAction(html`<div class="tb-action save-wrap">
      <button class=${cls('primary tb-new', addMenu && 'sel')} onClick=${() => setAddMenu(m => !m)} title="add an amp">+ Add ▾</button>
      ${addMenu ? html`<div class="picker-scrim" onClick=${() => setAddMenu(false)}></div>
        <div class="save-pop" onClick=${e => e.stopPropagation()}>
          <button class="row-btn sm" onClick=${() => { setAddMenu(false); setT3k(true); }}>From TONE3000
            <small>search the amps, pedals and cabs captured on tone3000.com</small></button>
          <button class="row-btn sm" onClick=${() => { setAddMenu(false); gcapIn.current && gcapIn.current.click(); }}>Import files
            <small>.nam captures (A1 or A2), golem modules (.gcap), cab IRs (.wav), or a .zip of them</small></button>
        </div>` : ''}
      <input ref=${gcapIn} type="file" accept=".nam,.gcap,.wav,.zip" multiple style="display:none" onChange=${importFiles} /></div>`);
    return () => setTopAction(null);
  }, [addMenu]);

  // la famille suit le RÔLE du segment Tones (Guitar · Bass · Voice, page-library) — plus de
  // sélecteur propre à cette page ; `gears` = ce que le rôle peut charger (role_categories)
  const fam = role === 'bass' ? 'bass' : role === 'guitar' ? 'guitar' : 'all';
  const roleCanLoad = !gears || gears.has('amp') || gears.has('amp-cab');
  // ICI, que des AMPLIS : les captures de pédales vivent dans Pedals, les IR dans Cabs, l'OUTBOARD
  // (préamplis, compresseurs capturés) dans Outboard — il passait ici pour un ampli (audit 15/09)
  const isAmp = t => t.gear !== 'pedal' && t.gear !== 'cab' && t.gear !== 'outboard' && t.format !== 'ir';
  const match = t => isAmp(t)
    && (rig === 'all' || t.gear === rig)
    && (style === 'all' || t.style === style)
    && (fam === 'all' || famOf(t) === fam)
    && (!q || (ampName(t) + ' ' + (t.brand || '') + ' ' + (t.tags || []).join(' ')).toLowerCase().includes(q));
  const list = tones.filter(match).sort((a, b) => (b.downloads || 0) - (a.downloads || 0));

  // ── rattachement capture -> MODÈLE nommé : règle unique partagée (designer-model.archOf) ──
  const archOf = t => archMatch(ampArch, t);
  const GENERIC = /^(other|divers|unknown|amp|amps|\-|)$/i;
  const brandOf = t => { const b = (t.brand || '').trim(); if (b && !GENERIC.test(b)) return b;
    const m = (t.makes || []).find(x => x && !GENERIC.test(x)); return m || 'Other'; };

  // caractère de gain : les MODÈLES le portent (family effects.json) ; une capture rattachée hérite
  // de son modèle (le modèle caché cache ses captures) ; une capture hors-modèle = heuristique
  // mots-clés puis style. Les basses sont hors-axe (le segmenté Family s'en charge).
  const guessChar = t => { if (famOf(t) === 'bass') return 'bass';
    const txt = capText(t);
    if (/high.?gain|hi.?gain|djent|modern metal|lead|distort|fuzz|muff/.test(txt)) return 'high-gain';
    if (/clean/.test(txt)) return 'clean';
    if (/crunch|drive|dirty|screamer/.test(txt)) return 'crunch';
    return t.style === 'metal' ? 'high-gain'
      : (t.style === 'blues' || t.style === 'jazz' || t.style === 'funk') ? 'clean' : 'crunch'; };

  // FUSION par MARQUE : tous les modèles du marché (même sans capture) + les captures rattachées ;
  // les captures qui ne matchent aucun modèle restent visibles, à la suite, dans leur marque.
  const models = ampArch.filter(a => (fam === 'all' || (fam === 'bass') === ampIsBass(a))
    && (chr === 'all' || (!ampIsBass(a) && (a.family || 'crunch') === chr))
    && (!q || (a.name + ' ' + (a.short || '') + ' ' + (a.match || '')).toLowerCase().includes(q)));
  const capsByArch = {}, unmatched = [];
  for (const t of list) {
    const a = (t.gear === 'amp' || t.gear === 'amp-cab') ? archOf(t) : null;
    if (a) (capsByArch[a.id] = capsByArch[a.id] || []).push(t); else unmatched.push(t);
  }
  // filtre Heads|+Cab actif -> les modèles SANS capture du type demandé sont masqués
  // (on cherche des captures ; les « no capture yet » ne sont que du bruit ici)
  const shownModels = rig === 'all' ? models : models.filter(a => (capsByArch[a.id] || []).length);
  const shownUm = unmatched.filter(t => chr === 'all' || guessChar(t) === chr);
  const brandOfArch = a => a.brand || a.name.split(' ')[0];
  const brands = [...new Set([...shownModels.map(brandOfArch), ...shownUm.map(brandOf)])]
    .sort((a, b) => a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b));

  // card MODÈLE : le nom court + ses captures (3 max inline, le reste au tap -> ArchDetail)
  const ModelCard = a => { const caps = capsByArch[a.id] || [];
    return html`
    <div class=${cls('card cpt', !caps.length && 'empty-cap')} data-doc=${'tones.amp:' + a.id} onClick=${() => setSelArch(a)} style=${'--sc:#ff5a3c'}>
      <h3>${a.glyph || '▦'} ${esc(a.short || a.name)}</h3>
      ${caps.length ? html`<div class="amp-caps">
          ${caps.slice(0, 3).map(t => html`<div class="amp-cap-line">${esc(ampName(t))}</div>`)}
          ${caps.length > 3 ? html`<div class="amp-cap-line muted">+ ${caps.length - 3} more…</div>` : ''}
        </div>` : html`<div class="gear muted">no capture yet</div>`}
    </div>`; };
  // card CAPTURE hors modèle (reste cliquable -> Detail, avec photo dans le modal)
  const CapCard = t => html`
    <div class=${'card cpt style-' + t.style} onClick=${() => setSel(t)}>
      <h3>${esc(ampName(t))}${t.pack ? html` <span class="pk">PACK</span>` : ''}</h3>
      ${lent[String(t.id)] ? html`<div class="gear lent-tag">${esc(lentLabel(lent[String(t.id)]))}</div>` : ''}
      <div class="gear">${GEAR_LABEL[t.gear] || t.gear} · ${t.models.length} mdl${t.models.some(m => String(m.arch) === '2') ? html` · <span class="a2-chip">A2</span>` : ''}</div>
    </div>`;

  // recherche + filtres sur UNE ligne : selects (gain de place vs rangées de chips)
  const Filter = (val, set, opts, label) => html`
    <select class="flt-sel" value=${val} onChange=${e => set(e.target.value)} title=${label}>
      <option value="all">${label} · all</option>
      ${opts.map(([v, l]) => html`<option value=${v} selected=${v === val}>${l}</option>`)}
    </select>`;
  // toolbar compacte (search + filtres) dans la barre de sous-onglets (remplace .lib-head).
  // La famille (Guitar|Bass) n'est plus ici : c'est le segment de RÔLE du groupe Tones (15/09).
  useEffect(() => {
    setSubToolbar(html`
      <input class="search" type="search" placeholder="Search…" onInput=${e => setQ(e.target.value.trim().toLowerCase())} />
      <div class="tb-seg" data-doc="tones.type" title="Capture type — head only (add a cab after) vs full rig (cab included)">
        <button class=${cls(rig !== 'amp-cab' && 'on')} onClick=${() => setRig(rig === 'all' ? 'amp-cab' : 'all')}>Heads</button>
        <button class=${cls(rig !== 'amp' && 'on')} onClick=${() => setRig(rig === 'all' ? 'amp' : 'all')}>+Cab</button>
      </div>
      ${Filter(chr, setChr, [['clean', 'Clean'], ['crunch', 'Crunch'], ['high-gain', 'High-gain']], 'Gain')}
      ${Filter(style, setStyle, STYLES.filter(s => tones.some(t => t.style === s)).map(s => [s, s]), 'Style')}`);
    return () => setSubToolbar(null);
  }, [fam, rig, chr, style, tones.length]);

  if (!roleCanLoad) return html`<div class="library"><div class="empty">A <b>${esc(role)}</b> lane can't load an amp — see <b>Outboard</b> for captured preamps and compressors.</div></div>`;

  return html`
    <div class="library">
      ${imp ? ImportSheet() : ''}
      <div class="lib-grid">
        ${brands.length ? html`<div class="syn-pack" data-doc="tones.amps">
          ${brands.map(b => { const ms = shownModels.filter(a => brandOfArch(a) === b);
            const um = shownUm.filter(t => brandOf(t) === b).sort((x, y) => ampName(x).localeCompare(ampName(y)));
            const n = ms.reduce((s, a) => s + (capsByArch[a.id] || []).length, 0) + um.length;
            return html`<div class="np-fam">
              <div class="np-fam-hd muted">${esc(b)} <span>${n ? n + ' capture' + (n > 1 ? 's' : '') : '—'}</span></div>
              <div class="grid gcpt">${ms.map(ModelCard)}${um.map(CapCard)}</div>
            </div>`; })}
        </div>` : html`<div class="empty">No amps for these filters.</div>`}
      </div>

      ${sel && html`<${Detail} t=${sel} img=${imgOf(sel)} onClose=${() => setSel(null)}
        onDeleted=${() => { setSel(null); refreshCatalog(); setCatTick(x => x + 1); }} />`}
      ${selArch && html`<${ArchDetail} a=${selArch}
        caps=${capsByArch[selArch.id] || []}
        onCap=${t => { setSelArch(null); setSel(t); }}
        onClose=${() => setSelArch(null)} onT3k=${() => { setSelArch(null); setT3k(true); }} />`}
      ${t3k && html`<${T3kModal} initGear="amp-cab" onClose=${() => setT3k(false)} onInstalled=${() => setCatTick(x => x + 1)} />`}
    </div>`;
}

// détail d'un AMPLI NOMMÉ (archétype) : ce que c'est + comment l'ajouter (tiroir Designer, picker
// de capture TONE3000 pré-filtré). Pas un fichier installé -> pas de suppression ici.
function ArchDetail({ a, caps, onCap, onClose, onT3k }) {
  const lent = useLent();
  const bass = (a.roles || ['guitar']).includes('bass');
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class="detail-card" data-doc="tones.amp-detail" style="--sc:#ff5a3c">
      <button class="close" onClick=${onClose}>×</button>
      <span class="badge" style="background:#ff5a3c">${esc(a.family)}${bass ? ' · bass' : ''}</span>
      <h2>${a.glyph || '▦'} ${esc(a.name)}</h2>
      <div class="sub">Named amp · ${bass ? 'bass' : 'guitar'} · ${(caps || []).length} capture(s) on the rack</div>
      ${(caps || []).length ? html`<div class="models" style="margin-top:12px"><strong>Your captures:</strong>
        ${caps.map(t => html`<div class="arch-cap" onClick=${() => onCap(t)} title="open this capture">
          <span>${esc(t.amp || t.title)}${t.gear === 'amp-cab' ? html` <span class="tag">+CAB</span>` : ''}${lent[String(t.id)] ? html` <span class="tag lent-tag" title=${lentLabel(lent[String(t.id)])}>LENT</span>` : ''}</span>
          <span class="muted">${esc(t.brand || t.creator || '')}${(t.models || []).some(m => String(m.arch) === '2') ? ' · A2' : ''} · ⬇ ${t.downloads || 0}</span>
        </div>`)}
      </div>` : html`<p class="muted" style="margin-top:12px">No capture on the rack yet.</p>`}
      <p class="muted" style="margin-top:12px">Add it from the <b>Designer ▸ +</b> drawer (${bass ? 'a Bass' : 'the'} input's
        Amp section) — the picker opens pre-filtered on <b>${esc(a.match || a.name)}</b> captures. Or download more below.</p>
      <p style="margin-top:12px"><button class="chip" onClick=${onT3k}>⬇ Browse TONE3000 captures</button></p>
    </div></div>`;
}

// Exporté : Pedals (page-fxblocks) rouvre le MÊME modal pour ses captures installées.
export function Detail({ t, img, onClose, onDeleted }) {
  const lent = useLent();
  const [del_, setDel] = useState(false);
  // famille (guitar/bass) : override explicite écrit dans tones-index (l'heuristique tag reste le défaut)
  const [famv, setFamv] = useState(famOf(t));
  const setFamily = async f => {
    setFamv(f);
    await fetch('/api/amp/' + t.id + '/family', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ family: f }),
    }).catch(() => {});
    refreshCatalog();
  };
  return html`<div class="detail" onClick=${e => e.target.classList.contains('detail') && onClose()}>
    <div class=${'detail-card' + (img ? ' with-photo' : '')}>
      <button class="close" onClick=${onClose}>×</button>
      <button class="mini danger amp-del" title="delete this amp (trash)" onClick=${() => setDel(true)}>🗑</button>
      ${del_ ? html`<${DeleteFlow} t=${t} onDone=${() => { setDel(false); onDeleted(); }} onCancel=${() => setDel(false)} />` : ''}
      ${img ? html`<div class="detail-photo" style=${`background-image:url('/library/${img.file}')`} title=${esc(img.credit || '')}></div>` : ''}
      <span class=${'badge style-' + t.style}>${t.style}</span>
      <h2>${esc(ampName(t))}${t.pack ? html` <span class="pk">PACK — ${(t.makes || []).length} gears</span>` : ''}</h2>
      <div class="sub">${esc(t.brand)} · ${t.gear} · ${t.models.length} model(s) · ♥ ${t.favorites || 0} · ⬇ ${t.downloads || 0}</div>
      ${lent[String(t.id)] ? html`<div class="sub lent-tag">${esc(lentLabel(lent[String(t.id)]))}</div>` : ''}
      <div class="kv"><strong>Family:</strong>
        ${['guitar', 'bass'].map(f => html`<button class=${cls('chip', famv === f && 'on')}
          onClick=${() => setFamily(f)}>${f === 'bass' ? '🎸 Bass' : '🎸 Guitar'}</button>`)}
      </div>
      ${(t.makes || []).length ? html`<div class="kv"><strong>Gear:</strong> ${(t.makes || []).map(m => html`<span class="tag">${esc(m)}</span>`)}</div>` : ''}
      <div class="kv"><strong>Tags:</strong> ${(t.tags || []).map(m => html`<span class="tag">${esc(m)}</span>`)}</div>
      <div class="models"><strong>Models:</strong>${t.models.map(m => html`<div><span>${esc(m.name || 'model')}</span><span>${esc(m.size || '')} ${m.arch ? 'A' + m.arch : ''}</span></div>`)}</div>
      <p style="margin-top:16px"><a href=${safeHref(t.url)} target="_blank" rel="noopener">Source ↗</a>${img && img.credit ? html`<span class="muted" style="margin-left:12px;font-size:11px">📷 ${esc(img.credit)}</span>` : ''}</p>
    </div></div>`;
}


// ── suppression d'un ampli : dépendances PAR PRESET (remplacer/vider), corbeille côté bridge ──
// Exporté : l'onglet IR (page-ir.js) réutilise le MÊME flux (les IR sont des tones du catalogue).
export function DeleteFlow({ t, onDone, onCancel }) {
  const { data: usage } = useAsync(() => fetch('/api/amp/' + t.id + '/usage').then(r => r.json()), []);
  const { data: cat } = useAsync(getCatalog, []);
  const [acts, setActs] = useState({});          // preset_id -> {mode, ref}
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  if (!usage) return html`<div class="delflow"><span class="muted">Checking dependencies…</span></div>`;

  const others = ((cat && cat.tones) || []).filter(x => String(x.id) !== String(t.id) && x.gear === t.gear);
  const deps = usage.presets || [];
  const act = id => acts[id] || { mode: 'clear' };
  const setAct = (id, a) => setActs({ ...acts, [id]: a });

  const doDelete = async () => {
    setBusy(true); setErr('');
    try {
      const r = await fetch('/api/amp/' + t.id, { method: 'DELETE',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actions: acts }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || r.status);
      onDone();
    } catch (e) { setErr(String(e.message || e)); setBusy(false); }
  };

  return html`<div class="delflow">
    <h3>Delete « ${esc(ampName(t))} » ?</h3>
    ${deps.length ? html`
      <p class="muted">Used by ${deps.length} preset(s) — choose what happens to each:</p>
      ${deps.map(d => html`<div class="del-dep">
        <b>${esc(d.name)}</b><span class="muted"> · ${d.blocks.join(', ')}</span>
        <select value=${act(d.id).mode} onChange=${e => setAct(d.id, e.target.value === 'clear' ? { mode: 'clear' } : { mode: 'replace', ref: others[0] && String(others[0].id) })}>
          <option value="clear" selected=${act(d.id).mode === 'clear'}>empty the block (choose a model later)</option>
          <option value="replace" selected=${act(d.id).mode === 'replace'} disabled=${!others.length}>replace with…</option>
        </select>
        ${act(d.id).mode === 'replace' ? html`<select value=${act(d.id).ref}
            onChange=${e => setAct(d.id, { mode: 'replace', ref: e.target.value })}>
          ${others.map(o => html`<option value=${String(o.id)} selected=${String(o.id) === act(d.id).ref}>${esc(o.amp || o.title)}</option>`)}
        </select>` : ''}
      </div>`)}` : html`<p class="muted">Not used by any preset.</p>`}
    ${usage.templates && usage.templates.length ? html`<p class="muted">Also in template(s) ${usage.templates.join(', ')} — blocks will be emptied.</p>` : ''}
    <div class="del-foot">
      <span class="flash-ko">${err}</span><span class="grow"></span>
      <button class="mini" onClick=${onCancel} disabled=${busy}>Cancel</button>
      <button class="primary" onClick=${doDelete} disabled=${busy}>${busy ? '…' : '🗑 Delete (to trash)'}</button>
    </div>
  </div>`;
}
