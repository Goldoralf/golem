// SPDX-License-Identifier: GPL-3.0-or-later
// Modal ⇅ I/O — LES SAUVEGARDES (refonte, 2026-10-09 — maquette mockups/io-modal.html, contrat docs/backups.md).
// Trois vues :
//   Export — on COCHE des catégories, UN bouton fabrique UN fichier et le TÉLÉCHARGE ; chaque catégorie dit ce
//            qu'elle porte, sa taille et depuis quand elle n'a pas été sauvegardée ; ce qui n'est pas sauvegardé est dit.
//   Import — d'où vient le fichier (déposé, choisi, ou une sauvegarde déjà sur le rack ou au vault), puis le PLAN par
//            catégorie (nouveau · différent · identique) AVANT toute écriture ; les conflits se tranchent en mots.
//   Vault  — UNE liste par date, où que soit la sauvegarde (ce rack, golem.fm, les deux) ; l'envoi automatique en
//            toutes lettres ; une alerte quand la dernière sauvegarde complète est ancienne.
// Ouvert par ⇅ I/O (Library, Songs) ; la catégorie de l'onglet ouvert arrive cochée.
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, saveFile, savedToast } from './lib.js';

const mb = n => !n ? '—' : n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' kB'
  : n < 1073741824 ? (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB' : (n / 1073741824).toFixed(1) + ' GB';
const days = t => t ? Math.max(0, Math.floor((Date.now() / 1000 - t) / 86400)) : null;
const ageTxt = d => d == null ? 'never' : d === 0 ? 'today' : d === 1 ? '1 day' : d + ' days';
const ageCls = d => d == null || d > 30 ? 'r' : d > 7 ? 'a' : '';
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const dstr = t => { const d = new Date(t * 1000); return d.getDate() + ' ' + MONTHS[d.getMonth()].slice(0, 3); };

// les catégories, groupées comme la maquette ; `d` = ce qu'elle porte, lu dans l'inventaire du rack
const GROUPS = [
  ['Your sounds', [
    ['presets', 'Presets & scenes', c => plural(c.n, 'preset') + (c.templates ? ' · ' + plural(c.templates, 'template') : '')],
    ['patches', 'Patches', c => plural(c.n, 'patch').replace('patchs', 'patches') + ' — a musician’s sound'],
    ['banks', 'Setlists & banks', c => plural(c.n, 'setlist') + ' · pedalboard map'],
    ['settings', 'Settings', () => 'soundcard, inputs, pedalboard, click, modes — no keys or passwords'],
    ['blockpresets', 'Block presets', c => (c.n ? plural(c.n, 'block preset') + ' you saved' : 'the block presets you save — factory ones come with golem')]]],
  ['Gear — your captures', [
    ['amps', 'Amps', c => plural(c.tones || 0, 'amp') + ' · ' + plural(c.n, 'file')],
    ['cabs', 'Cabs / IRs', c => plural(c.tones || 0, 'cab') + ' · ' + plural(c.n, 'file')],
    ['pedals', 'Pedals · Outboard', c => plural(c.tones || 0, 'pedal') + (c.outboard ? ' · ' + c.outboard + ' preamps / compressors' : '')]]],
  ['Instruments', [
    ['kits', 'Kits & samples', c => plural(c.n, 'kit') + (c.sounds ? ' · ' + plural(c.sounds, 'sample') : '') + ' · reference DIs'],
    ['synths', 'Synth presets', c => c.n + ' Vital presets you added'],
    ['grooves', 'Grooves', c => c.n ? plural(c.n, 'imported groove') : 'your imported drum grooves']]],
  ['Songs', [
    ['songs', 'Songs', c => plural(c.n, 'song') + ' (.golem)', true],
    ['recordings', 'Recordings', c => plural(c.audio || 0, 'take') + ' from the Rec block'],
    ['standards', 'Standards', c => plural(c.n, 'chart') + ' · your key and form edits']]],
];
const ALL_UI = GROUPS.flatMap(g => g[1].map(x => x[0]));
// la sélection → le type de sauvegarde : tout sauf les reprises = « all » (peut partir au vault)
const kindOf = sel => {
  const noSongs = ALL_UI.filter(k => k !== 'songs');
  if (sel.length === noSongs.length && noSongs.every(k => sel.includes(k))) return 'all';
  return sel.length === 1 ? sel[0] : 'custom';
};
// sur l'écran de la machine : copiée dans ses Téléchargements par le bridge (pas de bulle de Chrome hors de golem) ;
// sur un appareil distant : téléchargée chez lui (lib.saveFile)
const download = file => saveFile(file, { backup: file });
const KIND_LABEL = { all: 'everything', custom: 'selection', setlist: 'setlist' };
const NAME_OF = { ...Object.fromEntries(GROUPS.flatMap(g => g[1].map(x => [x[0], x[1]]))), setlist: 'Setlist', originals: 'Originals' };

export function IoModal({ family, onClose }) {
  const [tab, setTab] = useState('export');
  const [tick, setTick] = useState(0);
  const refresh = () => setTick(t => t + 1);
  const { data: ov } = useAsync(() => fetch('/api/backups/overview').then(r => r.json()).catch(() => null), [tick]);
  const [restore, setRestore] = useState(null);          // une sauvegarde à restaurer, choisie dans Vault -> Import
  const lastFull = ov && ov.last_full ? days(ov.last_full.t) : null;
  const go = (t, r) => { if (r) setRestore(r); setTab(t); };
  return html`<div class="sheet-scrim iox-scrim" onClick=${e => e.target.classList.contains('sheet-scrim') && onClose()}>
    <div class="gf-sheet iox" data-doc="backups">
      <div class="iox-h"><b class="iox-t">Backups</b>
        <div class="tb-seg iox-tabs">${[['export', 'Export'], ['import', 'Import'], ['vault', 'Vault']].map(([id, lb]) =>
          html`<button class=${cls(tab === id && 'on')} data-doc=${'backups.' + id} onClick=${() => setTab(id)}>${lb}</button>`)}</div>
        <span class="grow"></span>
        ${ov ? html`<span class=${cls('iox-state', lastFull != null && lastFull <= 7 && 'ok')}>● Last full backup: ${lastFull == null ? 'never' : ageTxt(lastFull) + (lastFull ? ' ago' : '')}</span>` : ''}
        <button class="mini" onClick=${onClose}>✕</button></div>
      ${tab === 'export' ? html`<${ExportView} ov=${ov} family=${family} onMade=${refresh} />`
        : tab === 'import' ? html`<${ImportView} restore=${restore} onRestored=${refresh} onClear=${() => setRestore(null)} />`
        : html`<${VaultView} ov=${ov} tick=${tick} onChanged=${refresh} onRestore=${r => go('import', r)} />`}
    </div></div>`;
}

// ── ① EXPORT ───────────────────────────────────────────────────────────────────────────────────
function ExportView({ ov, family, onMade }) {
  const [sel, setSel] = useState(() => family && ALL_UI.includes(family) ? [family] : []);
  const [vault, setVault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState(null);
  const c = (ov && ov.counts) || {};
  const last = (ov && ov.last) || {};
  const kind = kindOf(sel);
  const vaultOk = ov && ov.vault && ov.vault.online && (ov.vault_kinds || []).includes(kind);
  const size = sel.reduce((t, k) => t + ((c[k] || {}).bytes || 0), 0);
  const toggle = k => setSel(s => s.includes(k) ? s.filter(x => x !== k) : [...s, k]);
  const make = async () => {
    setBusy(true); setSaid({ busy: true, msg: 'making the backup…' });
    const body = kind === 'all' ? { kind: 'all' } : { kinds: sel };
    const r = await post('/api/backup', { ...body, vault: vault && vaultOk }).catch(e => (e.body || { error: String(e) }));
    setBusy(false);
    if (!r || r.error) { setSaid({ ok: false, msg: (r && r.error) || 'backup failed' }); return; }
    const where = (await download(r.file)).where;
    const v = r.vault;
    setSaid({ ok: true, msg: (where ? `Saved to ${where}` : `Downloading ${r.file}`) + ` · ${mb(r.size)}` + (v ? (v.ok ? ' · a copy is going to golem.fm' : ' · ' + v.why) : '') });
    onMade && onMade();
  };
  if (!ov) return html`<p class="muted">reading what this rack holds…</p>`;
  return html`
    <div class="iox-groups">${[0, 1].map(col => html`<div class="iox-col">${GROUPS.filter((_, i) => i % 2 === col).map(([title, cats]) => html`
      <div class="iox-gh">${title}</div>
      ${cats.map(([k, name, d, lock]) => { const ci = c[k] || { n: 0 }; const a = days((last[k] || {}).t);
        return html`<button class=${cls('iox-cat', sel.includes(k) && 'sel')} onClick=${() => toggle(k)}>
          <span class="iox-ck"></span>
          <span class="iox-txt"><b>${name}</b><small>${d(ci)}${lock ? html` · <span class="iox-lock">🔒 stays on this rack</span>` : ''}</small></span>
          <span class="iox-sz">${mb(ci.bytes)}</span>
          <span class="iox-age"><i class=${'iox-dot ' + ageCls(a)}></i>${ageTxt(a)}</span>
        </button>`; })}`)}
      ${col === 1 && (ov.not_backed || []).length ? html`<div class="iox-out"><b>Not in backups</b> — reinstalled by the installer:
        ${ov.not_backed.map(x => x.label + ' ' + mb(x.bytes)).join(' · ')}</div>` : ''}
    </div>`)}</div>
    <div class="iox-foot">
      <button class="mini" onClick=${() => setSel(sel.length === ALL_UI.length ? [] : ALL_UI)}>${sel.length === ALL_UI.length ? 'Select none' : 'Select all'}</button>
      <span class="iox-out"><b>${sel.length} selected</b>${sel.length ? ' · ≈ ' + mb(size) : ''}</span>
      ${said ? html`<span class=${cls('iox-said', said.ok === true && 'ok', said.ok === false && 'bad')}>${esc(said.msg)}</span>` : ''}
      <span class="grow"></span>
      <label class=${cls('iox-tog', !vaultOk && 'dis')} title=${vaultOk ? 'golem.fm keeps a copy, visible only to you'
          : sel.includes('songs') ? 'a backup with songs stays on this rack — golem.fm never keeps a cover’s audio'
          : ov.vault && !ov.vault.online ? 'pair with golem.fm (Settings ▸ Connect ▸ golem.fm) to keep copies there'
          : 'golem.fm keeps full backups, and presets, banks, amps, cabs or pedals alone — not this selection yet'}>
        <input type="checkbox" checked=${vault && vaultOk} disabled=${!vaultOk} onChange=${e => setVault(e.target.checked)} />
        Also keep a copy on golem.fm</label>
      <button class="primary iox-go" disabled=${!sel.length || busy} onClick=${make}>${busy ? 'zipping…' : '⬇ Download backup'}</button>
    </div>`;
}

// ── ② IMPORT ───────────────────────────────────────────────────────────────────────────────────
const CAT_LABEL = { presets: 'Presets', setlists: 'Setlists & banks', patches: 'Patches', settings: 'Settings', gear: 'Gear',
  kits: 'Kits & samples', synths: 'Synth presets', grooves: 'Grooves', recordings: 'Recordings', songs: 'Songs', standards: 'Standards', other: 'Other' };

function ImportView({ restore, onRestored, onClear }) {
  const { data: bk } = useAsync(() => fetch('/api/backups').then(r => r.json()).catch(() => null), []);
  const { data: rem } = useAsync(() => fetch('/api/backup/remote').then(r => r.json()).catch(() => null), []);
  const [plan, setPlan] = useState(null);
  const [src, setSrc] = useState(null);                  // ce qui est en cours d'analyse : {label, size}
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [strategy, setStrategy] = useState('skip');
  const [done, setDone] = useState(null);
  const [over, setOver] = useState(false);
  const pick = useRef(null);
  const reset = () => { setPlan(null); setErr(''); setDone(null); setSrc(null); };
  const inspectFile = async f => {
    reset(); setSrc({ label: f.name, size: f.size }); setBusy('checking the file…');
    const r = await fetch('/api/import/inspect', { method: 'POST', body: f }).then(x => x.json()).catch(e => ({ error: String(e) }));
    setBusy(''); r && r.ok ? setPlan(r) : setErr((r && r.error) || 'this file can’t be read');
  };
  const inspectLocal = async (file, label) => {
    reset(); setSrc({ label: label || file }); setBusy('checking the backup…');
    const r = await post('/api/import/inspect-local', { file }).catch(e => (e.body || { error: String(e) }));
    setBusy(''); r && r.ok ? setPlan(r) : setErr((r && r.error) || 'this backup can’t be read');
  };
  const pullThen = async rr => {
    reset(); setSrc({ label: rr.filename, size: rr.size }); setBusy('downloading from golem.fm…');
    const r = await post('/api/backup/pull', { id: rr.id }).catch(e => (e.body || { error: String(e) }));
    if (!r || !r.ok) { setBusy(''); setErr((r && r.error) || 'golem.fm did not send it'); return; }
    inspectLocal(r.file, rr.filename);
  };
  // arrivé depuis Vault : la sauvegarde choisie s'analyse d'elle-même
  useEffect(() => { if (!restore) return; restore.file ? inspectLocal(restore.file) : pullThen(restore.remote); onClear(); }, [restore]);
  const apply = async () => {
    setBusy('restoring… (a safety copy first)');
    const r = await post('/api/import/apply', { token: plan.token, strategy }).catch(e => (e.body || { error: String(e) }));
    setBusy('');
    if (!r || r.ok === false || r.error) { setErr((r && r.error) || 'the restore failed'); return; }
    setDone(r); onRestored && onRestored();
  };
  const local = ((bk || {}).backups || []).filter(b => !b.safety).slice(0, 3);
  const remote = ((rem || {}).backups || []).slice(0, 3);
  const cats = plan ? Object.entries(plan.cats || {}) : [];
  const nNew = cats.reduce((t, [, v]) => t + v.new, 0);
  const nDiff = plan ? plan.diff_total || 0 : 0;
  return html`<div class="iox-imp">
    <div class="iox-left">
      <div class=${cls('iox-zone', over && 'over')} onDragOver=${e => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)}
        onDrop=${e => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) inspectFile(f); }}>
        <b>Drop a backup here</b><small>a golem backup (.zip) — from this rack or another</small>
        <input ref=${pick} type="file" accept=".zip" style="display:none" onChange=${e => e.target.files[0] && inspectFile(e.target.files[0])} />
        <button class="mini" onClick=${() => pick.current && pick.current.click()}>Choose a file…</button></div>
      ${local.length || remote.length ? html`<div class="iox-src"><span class="iox-gh">Or restore a backup you already have</span>
        ${local.map(b => html`<button class="iox-sr" onClick=${() => inspectLocal(b.file)}><span class=${cls('iox-k', b.kind === 'all' && 'all')}>${KIND_LABEL[b.kind] || b.kind}</span>
          <span class="n">${dstr(b.mtime)} · ${mb(b.size)}</span><small>this rack</small></button>`)}
        ${remote.filter(r => !local.some(b => b.file === r.filename)).map(r => html`<button class="iox-sr" onClick=${() => pullThen(r)}>
          <span class=${cls('iox-k', r.kind === 'all' && 'all')}>${KIND_LABEL[r.kind] || r.kind}</span>
          <span class="n">${dstr(Date.parse(r.backup_created_at + 'Z') / 1000)} · ${mb(r.size)}</span><small>☁ golem.fm</small></button>`)}
      </div>` : ''}
    </div>
    <div class="iox-plan">
      ${busy ? html`<p class="muted">${busy}</p>`
        : err ? html`<div class="iox-err"><b>This backup can’t be restored</b><small>${esc(err)}</small>
            <button class="mini" onClick=${reset}>Try another file</button></div>`
        : done ? html`<div class="iox-done"><b class="ok">✓ Restored</b>
            <small>${[done.presets && plural(done.presets, 'preset'), done.banks && plural(done.banks, 'setlist'), done.assets && plural(done.assets, 'gear file'),
              done.config && plural(done.config, 'library file'), done.settings && plural(done.settings, 'setting'), done.recordings && plural(done.recordings, 'recording file'),
              done.songs && plural(done.songs, 'song')].filter(Boolean).join(' · ') || 'nothing new to add'}${done.kept ? ' · ' + done.kept + ' kept as they were' : ''}</small>
            <small>🛟 Safety copy: <code>${esc(String(done.preimport || ''))}</code> — it’s in Vault, under “before import”.</small>
            <button class="mini" onClick=${reset}>Restore another</button></div>`
        : plan ? html`
          <div class="iox-ph"><b>${esc(src ? src.label : plan.kind)}</b><span class="m">${KIND_LABEL[plan.kind] || plan.kind}${src && src.size ? ' · ' + mb(src.size) : ''}</span>
            <span class="grow"></span><span class="iox-okl">✓ ${plan.files} files checked</span></div>
          <div class="iox-rows"><span class="h">What</span><span class="h">New</span><span class="h">Different here</span><span class="h">Already identical</span>
            ${cats.map(([k, v]) => html`<span><b>${CAT_LABEL[k] || k}</b></span><span class=${v.new ? 'n' : 's'}>${v.new ? '+' + v.new : '—'}</span>
              <span class=${v.diff ? 'c' : 's'}>${v.diff || '—'}</span><span class="s">${v.same || '—'}</span>`)}</div>
          ${nDiff ? html`<div class="iox-strat"><b>${nDiff} differ from what’s here</b>
            <div class="tb-seg">${[['skip', 'Keep mine'], ['overwrite', 'Use the backup'], ['rename', 'Keep both']].map(([v, l]) =>
              html`<button class=${cls(strategy === v && 'on')} onClick=${() => setStrategy(v)}>${l}</button>`)}</div>
            ${strategy === 'rename' ? html`<small class="m">presets and templates come in as copies; other files keep yours</small>` : ''}</div>` : ''}
          <div class="iox-note">🛟 Before anything is written, golem keeps a safety copy of what would change — it shows in Vault as “before import”. Recordings already here are never replaced.</div>
          <div class="iox-pf"><span class="m">${nNew} new item${nNew === 1 ? '' : 's'}${nDiff ? ' · ' + nDiff + (strategy === 'overwrite' ? ' replaced' : ' kept as they are') : ''}</span>
            <span class="grow"></span><button class="mini" onClick=${reset}>Cancel</button>
            <button class="primary" disabled=${!nNew && !(nDiff && strategy !== 'skip')} onClick=${apply}>Restore</button></div>`
        : html`<div class="iox-empty"><b>Pick a backup</b><small>golem checks every file first, then shows what would be added or changed — nothing is written before you confirm.</small></div>`}
    </div>
  </div>`;
}

// ── ③ VAULT ────────────────────────────────────────────────────────────────────────────────────
function VaultView({ ov, tick, onChanged, onRestore }) {
  const [t2, setT2] = useState(0);
  const { data: bk } = useAsync(() => fetch('/api/backups').then(r => r.json()).catch(() => null), [tick, t2]);
  const { data: rem } = useAsync(() => fetch('/api/backup/remote').then(r => r.json()).catch(() => null), [tick, t2]);
  const { data: integ, reload: reloadInteg } = useAsync(() => fetch('/api/integrations').then(r => r.json()).catch(() => null), []);
  const [armed, setArmed] = useState(null);
  const [busy, setBusy] = useState(null);
  const [said, setSaid] = useState('');
  const [showSafety, setShowSafety] = useState(false);
  const [page, setPage] = useState(0);                  // les sauvegardes plus anciennes, par pages (jamais de défilement)
  const poll = useRef(null);
  useEffect(() => () => clearInterval(poll.current), []);
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(null), 3000); return () => clearTimeout(t); }, [armed]);
  const online = !!(rem && rem.online);
  const auto = !!(integ && integ.golemfm && integ.golemfm.auto_push);
  const vk = (ov && ov.vault_kinds) || [];
  // UNE liste : le rack et le vault, réunis par nom de fichier
  const rows = {};
  ((bk || {}).backups || []).forEach(b => { rows[b.file] = { file: b.file, kind: b.kind, kinds: b.kinds, t: b.mtime, size: b.size, rack: true, safety: b.safety }; });
  ((rem || {}).backups || []).forEach(r => { const x = rows[r.filename] || (rows[r.filename] = { file: r.filename, kind: r.kind, t: Date.parse(r.backup_created_at + 'Z') / 1000, size: r.size });
    x.remote = r; });
  const all = Object.values(rows).sort((a, b) => b.t - a.t);
  const main = all.filter(r => !r.safety), safety = all.filter(r => r.safety);
  const lastFull = ov && ov.last_full ? days(ov.last_full.t) : null;
  const never = ov ? ALL_UI.filter(k => ((ov.counts || {})[k] || {}).n && !(ov.last || {})[k]) : [];
  const flash = m => { setSaid(m); setTimeout(() => setSaid(''), 6000); };
  const send = file => {
    setBusy(file);
    fetch('/api/backup/push/' + encodeURIComponent(file), { method: 'POST' }).then(r => r.json()).then(r => {
      if (r && r.ok === false) { setBusy(null); flash('✗ ' + r.error); return; }
      poll.current = setInterval(async () => {
        const st = await fetch('/api/backup/push/status').then(x => x.json()).catch(() => null);
        if (st && st.state !== 'busy') { clearInterval(poll.current); setBusy(null); setT2(x => x + 1); onChanged();
          if (st.state === 'error') flash('✗ golem.fm: ' + st.error); }
      }, 1200);
    });
  };
  const remove = async r => {
    if (armed !== r.file) { setArmed(r.file); return; }
    setArmed(null);
    if (r.rack) await fetch('/api/backup/' + encodeURIComponent(r.file), { method: 'DELETE' }).catch(() => null);
    else if (r.remote) await fetch('/api/backup/remote/' + r.remote.id, { method: 'DELETE' }).catch(() => null);
    setT2(x => x + 1); onChanged();
  };
  const fullNow = async () => {
    setBusy('full');
    const r = await post('/api/backup', { kind: 'all', vault: online }).catch(e => (e.body || { error: String(e) }));
    setBusy(null);
    if (!r || r.error) { flash('✗ ' + ((r && r.error) || 'backup failed')); return; }
    const where = (await download(r.file)).where;
    if (where) flash('✓ saved to ' + where);
    setT2(x => x + 1); onChanged();
  };
  const toggleAuto = async () => { await post('/api/integrations', { golemfm: { auto_push: !auto } }); reloadInteg(); };
  const canSend = r => r.rack && !r.remote && online && vk.includes(r.kind) && !(r.kinds || []).includes('songs');
  const row = r => html`<div class="iox-lr">
    <span class="iox-kd">${r.kind === 'custom' && (r.kinds || []).length
      ? r.kinds.slice(0, 3).map(k => html`<span class="iox-k">${k}</span>`) : html`<span class=${cls('iox-k', r.kind === 'all' && 'all')}>${KIND_LABEL[r.kind] || r.kind}</span>`}</span>
    <span class="iox-when"><b>${r.kind === 'all' ? 'Full backup' : r.kind === 'custom' ? plural((r.kinds || []).length, 'category').replace('categorys', 'categories') : NAME_OF[(r.kinds && r.kinds[0]) || r.kind] || r.kind}</b>
      <small>${dstr(r.t)} · ${ageTxt(days(r.t))}${days(r.t) ? ' ago' : ''}</small></span>
    <span class="iox-sz">${mb(r.size)}</span>
    <span class="iox-wh"><span class=${cls(r.rack && 'y')}>▣ ${r.rack ? 'this rack' : '—'}</span>
      ${(r.kinds || []).includes('songs') || r.kind === 'songs' ? html`<span class="iox-lock">🔒 stays here</span>`
        : html`<span class=${cls(r.remote && 'y c')}>☁ ${r.remote ? 'golem.fm' : '—'}</span>`}</span>
    <span class="iox-acts">
      <button class="mini" onClick=${() => onRestore(r.rack ? { file: r.file } : { remote: r.remote })}>Restore</button>
      ${r.rack ? html`<a class="mini dl" href=${'/api/backup/' + encodeURIComponent(r.file)} title="download"
        onClick=${e => { e.preventDefault(); download(r.file).then(x => x.where && savedToast('✓ Saved to ' + x.where)); }}>⬇</a>` : ''}
      ${canSend(r) ? html`<button class="mini" disabled=${!!busy} onClick=${() => send(r.file)}>${busy === r.file ? '…' : '☁ Send'}</button>` : ''}
      <button class=${cls('mini', 'del', armed === r.file && 'armed')} title=${r.rack ? 'delete it from this rack' : 'delete it from golem.fm'}
        onClick=${() => remove(r)}>${armed === r.file ? 'sure?' : '🗑'}</button></span>
  </div>`;
  let lastMonth = null;
  const v = (ov && ov.vault) || {};
  const warn = lastFull == null || lastFull > 30;
  const shown = warn ? 4 : 6;                     // 1024×600 sans défilement : ce qui tient sous l'alerte
  const pages = Math.max(1, Math.ceil(main.length / shown)), pg = Math.min(page, pages - 1);
  return html`
    <div class="iox-vh"><b>☁ golem.fm vault</b>
      ${online ? html`<span class="m">${plural(((rem || {}).backups || []).length, 'backup')} · ${mb(rem.bytes || 0)}${v.max_bytes ? ' of ' + mb(v.max_bytes) : ''}</span>
        ${v.max_bytes ? html`<span class="iox-meter"><i style=${'width:' + Math.min(100, Math.round(100 * (rem.bytes || 0) / v.max_bytes)) + '%'}></i></span>` : ''}`
        : html`<span class="m">not reachable — pair with golem.fm in Settings ▸ Connect ▸ golem.fm</span>`}
      <span class="grow"></span>
      ${online ? html`<label class="iox-tog"><input type="checkbox" checked=${auto} onChange=${toggleAuto} />Send every new backup automatically</label>` : ''}</div>
    ${warn ? html`<div class="iox-warn"><span>⚠</span><span><b>${lastFull == null ? 'No full backup yet.' : 'Your last full backup is ' + lastFull + ' days old.'}</b>
      ${never.length ? html` <span class="m">Never backed up: ${never.map(k => GROUPS.flatMap(g => g[1]).find(x => x[0] === k)[1]).join(', ')}.</span>` : ''}</span>
      <span class="grow"></span><button class="primary iox-go" disabled=${!!busy} onClick=${fullNow}>${busy === 'full' ? 'zipping…' : '⬇ Back up everything now'}</button></div>` : ''}
    ${said ? html`<div class="iox-said bad">${esc(said)}</div>` : ''}
    <div class="iox-list">
      ${!bk ? html`<p class="muted">loading…</p>` : !main.length ? html`<p class="muted">No backups yet — make one in Export.</p>` : ''}
      ${main.slice(pg * shown, (pg + 1) * shown).map(r => { const m = MONTHS[new Date(r.t * 1000).getMonth()]; const hd = m !== lastMonth; lastMonth = m;
        return html`${hd ? html`<div class="iox-mon">${m}</div>` : ''}${row(r)}`; })}
      ${/* « + N older backups » était un simple texte : au-delà de six, les sauvegardes étaient INACCESSIBLES (2026-10-22) */''}
      ${pages > 1 ? html`<div class="iox-pager">
        <button class="iox-fold" disabled=${pg === 0} onClick=${() => setPage(pg - 1)}>‹ newer</button>
        <span class="m">${pg * shown + 1}–${Math.min(main.length, (pg + 1) * shown)} of ${main.length}</span>
        <button class="iox-fold" disabled=${pg >= pages - 1} onClick=${() => setPage(pg + 1)}>older ›</button></div>` : ''}
      ${safety.length ? html`<button class="iox-fold" onClick=${() => setShowSafety(s => !s)}>${showSafety ? '▾' : '▸'} ${plural(safety.length, 'safety copy').replace('copys', 'copies')} taken before imports</button>
        ${showSafety ? safety.slice(0, 3).map(row) : ''}` : ''}
    </div>`;
}
