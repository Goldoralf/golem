// SPDX-License-Identifier: GPL-3.0-or-later
// Onglet Licenses (hub Settings) — 2026-07-24 : versions & licences au même endroit.
// Sous-onglets : Golem (version/update + licence open source) · Reaper (versioning | licence)
// · Libraries (tous les projets open source musicaux embarqués — cartes nom + lien).
// Les cartes GoleM/Reaper viennent de l'ancien sous-onglet System ▸ Update (supprimé).
import { html, useState, useEffect, useAsync, post, cls, esc, go } from './lib.js';

// ── carte GoleM : version + update git (releases uniquement) — ex-UpdatePanel ──
function GolemUpdateCard() {
  const { data: u, setData } = useAsync(() => fetch('/api/system/update').then(r => r.json()), []);
  const [checking, setChecking] = useState(false);
  const [updating, setUpdating] = useState('');           // '' | 'busy' | message d'erreur
  const check = async () => {
    setChecking(true);
    const d = await fetch('/api/system/update?fetch=1').then(r => r.json()).catch(() => null);
    if (d) setData(d);
    setChecking(false);
  };
  const apply = async () => {
    setUpdating('busy');
    const r = await post('/api/system/update', { tag: u.latest }).catch(e => ({ error: String(e) }));
    // le bridge redémarre — on recharge l'app ; sur un poste le lanceur ferme et rouvre la fenêtre lui-même
    if (r && r.ok) { if (!r.full_restart) setTimeout(() => location.reload(), 6000); }
    else setUpdating((r && r.error) || 'failed');
  };
  const STATUS = {
    'up-to-date': ['ok', '✓ up to date'],
    'update-available': ['warn', '⬆ update available'],
    'ahead': ['ok', '✓ ahead of latest release (dev)'],
    'no-release': ['idle', 'no release tags yet'],
    'no-git': ['idle', 'cannot update from here'],
  };
  const [stState, stLabel] = (u && STATUS[u.status]) || ['idle', '…'];
  return html`<section class="card-panel">
    <h3>golem</h3>
    <div class="upd-rows">
      <div class="upd-row"><label>Current version</label><b>${u ? (u.current || '—') : '…'}</b></div>
      <div class="upd-row"><label>Branch</label><b>${u ? u.branch : '…'}</b></div>
      <div class="upd-row"><label>Working tree</label>
        <b class=${u && !u.clean ? 'warnish' : ''} title=${u && !u.clean ? (u.changes || []).join('\n') : ''}>
          ${u ? (u.clean ? 'clean' : `${(u.changes || []).length || ''} local code change${(u.changes || []).length === 1 ? '' : 's'}`) : '…'}</b></div>
      <div class="upd-row"><label>Latest release</label><b>${u ? (u.latest || '—') : '…'}</b>
        <span class=${cls('upd-status', stState)}>${stLabel}</span></div>
    </div>
    ${u && u.fetch_error ? html`<p class="muted warn">✗ ${u.fetch_error}</p>` : ''}
    ${/* SANS GIT (une install Windows/macOS est une copie sans .git) : on le DIT, au lieu d'un faux nom de version */''}
    ${u && u.status === 'no-git' ? html`<p class="muted">This golem was installed without git, so it cannot update from
      this screen yet. To get the latest release, run the install line again — your presets, settings and takes are kept.</p>` : ''}
    ${/* LES NOTES DE LA RELEASE (message du tag annoté, en anglais) — plus les sujets de commit, en français */''}
    ${u && u.status === 'update-available' && u.notes ? html`
      <div class="upd-log"><b>What's new in ${u.latest}</b>
        ${u.notes.split('\n').map(l => html`<div class="upd-log-line">${l}</div>`)}</div>` : ''}
    <div class="upd-actions">
      <button class="chip" disabled=${checking} onClick=${check}>${checking ? '⏳ checking…' : '⟳ Check for releases'}</button>
      ${u && u.status === 'update-available' ? html`
        <button class="primary" disabled=${!u.clean || updating === 'busy'} onClick=${apply}
          title=${u.clean ? '' : 'working tree has local changes — commit or stash first'}>
          ${updating === 'busy' ? (u.full_restart ? '⏳ updating — golem restarting…' : '⏳ updating — bridge restarting…') : `⬆ Update to ${u.latest}`}</button>` : ''}
      ${updating && updating !== 'busy' ? html`<span class="perf-err">✗ ${updating}</span>` : ''}
    </div>
    <p class="muted" style="margin-top:12px">Updates are bound to <b>tagged releases</b> only (git).${' '}
      ${u && u.full_restart
        ? html`golem <b>restarts entirely</b> after switching — this window closes and reopens, audio stops ~30 s.`
        : 'The bridge restarts automatically after switching — the page reloads itself.'}</p>
  </section>`;
}

// ── carte licence golem : le contrat open source du produit — texte de l'avocat (livrable L5 §2, 2026-10-20),
// resserré pour tenir à l'écran ; il dit exactement ce que déclarent LICENSE, LICENSE.MIT, TRADEMARK.md et
// docs/licence.md (une page qui affirme une licence que le dépôt ne déclare pas serait fausse) ──
function GolemLicenseCard() {
  const tab = (id, label) => html`<a href=${'#/system/about/' + id} onClick=${e => { e.preventDefault(); go('system/about/' + id); }}>${label}</a>`;
  return html`<section class="card-panel lic-card">
    <h3>Open-source license</h3>
    <div class="upd-rows">
      <div class="upd-row"><label>License</label><b>GNU GPL v3 or later</b></div>
      <div class="upd-row"><label>Copyright</label><b>© 2026 <span class="lic-who" title="github.com/Goldoralf">Raphaël Mucchielli</span>, <span class="lic-who" title="github.com/dunkean">Grégory Beurier</span> and contributors</b></div>
      <div class="upd-row"><label>MIT</label><span>exchange formats (.gsx, .golem, presets) · original JSFX</span></div>
      <div class="upd-row"><label>CC0 1.0</label><span>factory presets, patches and drum grooves</span></div>
    </div>
    <p class="muted lic-p">golem is <b>free software</b> under the GNU GPL, version 3 or any later version: a modified
      version you distribute stays under the same license. It comes with <b>ABSOLUTELY NO WARRANTY</b>.</p>
    <ul class="lic-points muted">
      <li>✓ run, read, modify, share and fork it — for any purpose</li>
      <li>⚠ a redistributed fork publishes its source under the GPL and takes its own name</li>
      <li>ℹ REAPER and the plugins keep their own licenses — ${tab('reaper', 'REAPER')} and ${tab('libs', 'Libraries')} tabs</li>
    </ul>
    <p class="muted lic-p"><b>Trademark notice:</b> “golem” and “golem.fm” are trademarks of Raphaël Mucchielli, not licensed
      under the GPL: a modified redistributed version must remove them. Amp, pedal and instrument names are trademarks
      of their owners, used only to describe a sound; golem is not affiliated with or endorsed by them.</p>
    <p class="muted lic-full">Full texts: <span class="liblic-url">gnu.org/licenses/gpl-3.0</span> · <span class="liblic-url">LICENSE.MIT</span> · <span class="liblic-url">TRADEMARK.md</span></p>
  </section>`;
}

// ── Reaper : colonne gauche VERSIONING (ex-ReaperEngineCard, moitié update) ──
function ReaperVersioningCard() {
  const { data: r, setData } = useAsync(() => fetch('/api/system/reaper-update').then(x => x.json()), []);
  const [err, setErr] = useState('');
  const busy = !!(r && r.busy);
  // LA VERSION PUBLIÉE EN AMONT arrive en fond (le bridge la lit au plus une fois par jour) : si la
  // lecture est en cours à l'ouverture de la carte, on relit une fois — sinon la ligne resterait vide
  // jusqu'au prochain passage sur la page (2026-09-22 : « le golem ne détecte pas la 7.80 »).
  useEffect(() => {
    if (!r || !r.upstream_checking) return;
    const t = setTimeout(async () => {
      const d = await fetch('/api/system/reaper-update?check=0').then(x => x.json()).catch(() => null);
      if (d) setData(d);
    }, 2500);
    return () => clearTimeout(t);
  }, [r && r.upstream_checking]);
  const recheck = async () => {
    setData({ ...r, upstream_checking: true });
    const d = await fetch('/api/system/reaper-update?force=1').then(x => x.json()).catch(() => null);
    if (d) setData(d);
  };
  useEffect(() => {                                       // poll la progression pendant l'update
    if (!busy) return;
    const t = setInterval(async () => {
      const d = await fetch('/api/system/reaper-update').then(x => x.json()).catch(() => null);
      if (d) setData(d);
    }, 2000);
    return () => clearInterval(t);
  }, [busy]);
  const start = async (body, path) => {
    setErr('');
    const d = await post(path || '/api/system/reaper-update', body || {}).catch(e => ({ error: String(e) }));
    if (d && d.error) { setErr(d.error); return; }
    const s = await fetch('/api/system/reaper-update?check=0').then(x => x.json()).catch(() => null);
    if (s) setData(s);
  };
  // ── DEUX TAPS POUR CE QUI COUPE L'AUDIO (même idiome que la corbeille des setlists) ─────────
  // Le premier tap ARME et fait apparaître ce qu'on perd ; le second lance. Une install non validée
  // n'est pas un geste à faire en passant — mais elle appartient à l'utilisateur (2026-09-22 :
  // « il faut que l'utilisateur final puisse l'installer seul »).
  const [arm, setArm] = useState(null);
  const armed = k => arm === k;
  const confirm = (k, run) => { if (!armed(k)) { setArm(k); setTimeout(() => setArm(a => (a === k ? null : a)), 6000); return; }
    setArm(null); run(); };
  const STATUS = {
    'up-to-date': ['ok', '✓ matches this release'],
    'update-available': ['warn', '⬆ update available'],
    'ahead': ['warn', '⚠ not validated for this release'],
    'busy': ['warn', '⏳ updating…'],
    'not-installed': ['warn', 'engine not found'],
    'no-pin': ['idle', 'no pinned version'],
  };
  const [stState, stLabel] = (r && STATUS[r.status]) || ['idle', '…'];
  const last = r && r.last;
  return html`<section class="card-panel">
    <h3>Versioning</h3>
    <div class="upd-rows">
      <div class="upd-row"><label>Installed engine</label><b>${r ? (r.installed || '—') : '…'}</b></div>
      <div class="upd-row"><label>Validated for this release</label><b>${r ? (r.pinned || '—') : '…'}</b>
        <span class=${cls('upd-status', stState)}>${stLabel}</span></div>
      ${/* LA VERSION PUBLIÉE PAR COCKOS : une information, jamais une cible — aucun bouton sur cette
            ligne. Le rack n'installe que ce que la release golem a validé (le pin ci-dessus). */''}
      <div class="upd-row"><label>Latest published</label>
        <b>${r && r.upstream_checking ? '…' : (r && r.upstream) || '—'}</b>
        ${r && r.upstream_newer
          ? html`<span class="upd-status warn" title="published by Cockos — it reaches this rack when a golem release has validated it">newer than this release</span>`
          : r && r.upstream
            ? html`<span class="upd-status ok">✓ nothing newer</span>`
            : html`<span class="upd-status idle" title=${r && r.upstream_error ? 'reaper.fm unreachable: ' + r.upstream_error : 'read from reaper.fm, once a day'}>
                ${r && r.upstream_error ? 'not reachable' : 'not read yet'}</span>`}
        <button class="mini upd-recheck" title="read reaper.fm now" onClick=${recheck}>↻</button></div>
      ${/* CE QUI EST SUR LE RACK : la version précédente reste installée à côté, et un tap y revient —
            sans réseau. C'est le filet d'une install non validée, et il doit se VOIR avant le geste. */''}
      ${r && (r.versions || []).length > 1 ? html`<div class="upd-row"><label>On this rack</label>
        <span class="upd-vers">${r.versions.map(v => v.active
          ? html`<b class="upd-ver on">${v.version} · running</b>`
          : html`<button class=${cls('mini', armed('s:' + v.version) && 'danger')} disabled=${busy}
              title=${'switch the engine back to ' + v.version + ' — no download, audio stops ~1 min'}
              onClick=${() => confirm('s:' + v.version, () => start({ version: v.version }, '/api/system/reaper-switch'))}>
              ${armed('s:' + v.version) ? 'switch now?' : 'Use ' + v.version}</button>`)}</span></div>` : ''}
    </div>
    ${busy && r.log.length ? html`
      <div class="upd-log">${r.log.map(l => html`<div class="upd-log-line">${l}</div>`)}</div>` : ''}
    ${!busy && last ? html`
      <p class=${last.ok ? 'muted' : 'muted warn'} style="margin-top:10px">
        ${last.ok ? `✓ engine updated ${last.from} → ${last.to}`
    : `✗ ${last.error}${last.rolled_back ? '' : ' — engine unchanged'}`}</p>` : ''}
    ${/* L'INSTALL NON VALIDÉE, ce qu'elle coûte, DIT AVANT le geste — pas dans une infobulle. */''}
    ${armed('u') ? html`<div class="upd-warn">
      <b>Install REAPER ${r.upstream} without a golem release?</b>
      <ul>
        <li><b>Nobody has played it on this rig.</b> A golem release pins the version it was tested with; this one skips that.</li>
        <li><b>Nothing to check the download against</b> — Cockos publishes no checksum, so only HTTPS protects it. The rack records
          the sha256 it got, in the log below.</li>
        <li>Audio stops ~1 min. <b>${r.installed} stays on this rack</b>: if the new engine does not come back it is restored
          automatically, and « Use ${r.installed} » brings it back any time.</li>
      </ul></div>` : ''}
    ${/* macOS (2026-10-04) : ni mise à jour ni retour arrière depuis GoleM — l'écran le DIT au lieu
          d'offrir un bouton que le bridge refuserait (docs/platforms.md, M3b). */''}
    ${r && r.can_update === false ? html`<p class="muted" style="margin-top:10px">${r.update_unavailable_why}</p>` : html`
    <div class="upd-actions">
      ${r && r.status === 'update-available' ? html`
        <button class="primary" disabled=${busy} onClick=${() => start()}>⬆ Update engine to ${r.pinned}</button>` : ''}
      ${r && r.upstream_newer && r.upstream !== r.installed ? html`
        <button class=${cls('mini', 'upd-unval', armed('u') && 'danger')} disabled=${busy}
          title="install the version published by Cockos, which this golem release has not validated"
          onClick=${() => confirm('u', () => start({ version: r.upstream }))}>
          ${armed('u') ? `install ${r.upstream} now?` : `⬆ Install ${r.upstream}`}</button>` : ''}
      ${err ? html`<span class="perf-err">✗ ${err}</span>` : ''}
    </div>`}
    ${r && r.can_update === false ? '' : html`<p class="muted" style="margin-top:12px">Engine updates are bound to the version <b>validated with the
      installed golem release</b> — that one is verified against a checksum and has been played on a rig.
      A newer version published by Cockos can be installed from here too, <b>with neither guarantee</b>,
      and the previous engine stays one tap away. Updating <b>interrupts audio
      (~1 min)</b>; if the new engine fails to come back, the previous one is <b>restored automatically</b>.
      Play something afterwards to confirm the rig sounds right.</p>`}
    ${/* WINDOWS : chaque geste passe par une invite UAC — sur l'écran du PC, pas sur le téléphone. */''}
    ${r && r.needs_permission ? html`<p class="muted">On Windows, <b>Windows asks for permission on the PC
      screen</b> before the engine changes — approve it there (not from a phone). Refused: nothing changes.</p>` : ''}
  </section>`;
}

// ── Reaper : colonne droite LICENCE (ex-ReaperEngineCard, moitié lic-sec) ──
function ReaperLicenseCard() {
  const { data: lic, setData: setLic } = useAsync(() => fetch('/api/system/reaper-license').then(x => x.json()), []);
  const [licVal, setLicVal] = useState('');
  const [licSaving, setLicSaving] = useState('');
  const [licSaved, setLicSaved] = useState(false);          // save réussi -> propose le restart pour appliquer
  const [licRestart, setLicRestart] = useState('');          // '' | 'busy'
  const [licEdit, setLicEdit] = useState(false);             // licence installée : rouvrir le champ
  const licPresent = !!(lic && lic.present);
  const licForm = !licPresent || licEdit;                    // rien à saisir tant qu'elle est là
  const saveLic = async () => {
    if (!licVal.trim()) return;
    setLicSaving('busy');
    const rr = await post('/api/system/reaper-license', { license: licVal }).catch(e => ({ error: String(e) }));
    if (rr && rr.ok) { setLic({ present: true }); setLicVal(''); setLicSaving(''); setLicSaved(true); setLicEdit(false); }
    else setLicSaving((rr && rr.error) || 'failed');
  };
  const restartEngine = async () => {                        // applique la licence (Reaper la lit au boot)
    setLicRestart('busy');
    await post('/api/system/reaper-restart').catch(() => {});
    setTimeout(() => { setLicRestart(''); setLicSaved(false); }, 12000);   // Reaper revient (~10 s)
  };
  return html`<section class="card-panel">
    <h3>License</h3>
    <p class="muted">REAPER is <b>commercial software</b> (not open source) — golem drives it as its
      audio engine. It runs fully in evaluation mode, but a personal license is <b>$60</b> and worth
      every cent: <span class="liblic-url">reaper.fm/purchase</span>.</p>
    <div class="lic-sec" style="margin-top:8px; border-top:none; padding-top:0">
      <div class="upd-row"><label>License</label>
        ${/* `state` = ce que REAPER AFFICHE (Windows) : un fichier présent peut être refusé par la version qui tourne */''}
        <b class=${licPresent && lic.state !== 'evaluation' ? '' : 'warnish'}
          title=${lic && lic.state === 'evaluation' && licPresent ? 'the license file is there, but the running REAPER version does not accept it' : ''}>
          ${!licPresent ? 'eval — no license' : lic.state === 'evaluation' ? '⚠ not accepted by this REAPER — evaluation' : '✓ installed'}</b>
        ${licPresent && !licEdit ? html`<button class="mini lic-replace" title="paste another license — the one on this rack is replaced"
          onClick=${() => setLicEdit(true)}>Replace…</button>` : ''}</div>
      ${licForm ? html`<textarea class="lic-in" rows="4" spellcheck="false" placeholder="paste license here…"
        value=${licVal} onInput=${e => setLicVal(e.target.value)}></textarea>` : ''}
      <div class="upd-actions">
        ${licForm ? html`<button class="primary" disabled=${!licVal.trim() || licSaving === 'busy'} onClick=${saveLic}>
          ${licSaving === 'busy' ? '⏳ saving…' : '💾 Save license'}</button>` : ''}
        ${licPresent && licEdit ? html`<button class="chip" onClick=${() => { setLicEdit(false); setLicVal(''); setLicSaving(''); }}>Cancel</button>` : ''}
        ${licSaving && licSaving !== 'busy' ? html`<span class="perf-err">✗ ${licSaving}</span>` : ''}
        ${licSaved ? html`<button class="chip" disabled=${licRestart === 'busy'} onClick=${restartEngine}
          title="the license takes effect when the engine restarts (~10 s, audio interrupted)">
          ${licRestart === 'busy' ? '⏳ restarting…' : '↻ Restart engine to apply'}</button>` : ''}
      </div>
      ${licSaved && licRestart !== 'busy' ? html`<p class="muted">✓ saved — restart the engine to apply (or later, from the Dashboard).</p>` : ''}
    </div>
  </section>`;
}

// ── Libraries : tous les projets libres embarqués — LE MANIFESTE (provision/components.json), confronté
// à la machine par le bridge (dpkg, venv, fichiers). Une obligation de la GPL avant d'être une page :
// dire ce qu'on embarque, sous quelle licence, d'où ça vient — et s'il est vraiment là (2026-09-09). ──
const KIND_LBL = { engine: 'Audio engine', plugin: 'Plugins', asset: 'Sounds & kits', separation: 'Separation engines', python: 'Bridge (Python)', system: 'System', js: 'App' };
const KIND_ORDER = ['engine', 'plugin', 'asset', 'separation', 'python', 'system', 'js'];
function LibrariesPanel() {
  const { data, err, reload } = useAsync(() => fetch('/api/system/libraries').then(r => r.json()), []);
  const [lic, setLic] = useState(null);           // filtre par FAMILLE de licence (null = toutes)
  const [onlyMissing, setOnlyMissing] = useState(false);
  if (!data) return html`<div class="pg-body"><p class="muted">${err ? '✗ ' + err : 'reading the manifest…'}</p></div>`;
  const fam = l => /GPL/.test(l) ? 'gpl' : /CC/.test(l) ? 'cc' : /Commercial|EULA/.test(l) ? 'com' : 'perm';
  const FAMS = [['gpl', 'GPL / LGPL', 'copyleft — sources and changes stay open'], ['perm', 'Permissive', 'MIT, BSD, Apache, ISC…'], ['cc', 'Creative Commons', 'sounds and kits — attribution'], ['com', 'Commercial', 'Reaper']];
  const comps = (data.components || []).filter(c => (!lic || fam(c.license || '') === lic) && (!onlyMissing || c.installed === false));
  const byKind = KIND_ORDER.map(k => [k, comps.filter(c => (c.kind || 'plugin') === k)]).filter(([, l]) => l.length);
  return html`<div class="pg-body liblic-page">
    <div class="liblic-head">
      <p class="muted">Golem stands on these open-source projects — each keeps its own license. <b>${data.installed}</b> of ${data.checked} checked components are installed on this machine. 🙏</p>
      <div class="liblic-filters">
        <button class=${cls('chip', !lic && !onlyMissing && 'on')} onClick=${() => { setLic(null); setOnlyMissing(false); }}>all</button>
        ${FAMS.map(([id, label, title]) => html`<button class=${cls('chip', 'lic-' + id, lic === id && 'on')} title=${title} onClick=${() => setLic(lic === id ? null : id)}>${label} <small>${(data.components || []).filter(c => fam(c.license || '') === id).length}</small></button>`)}
        <button class=${cls('chip', onlyMissing && 'on warn')} onClick=${() => setOnlyMissing(!onlyMissing)} title="components the manifest expects and this machine does not have">missing only</button>
        <button class="mini" onClick=${reload} title="re-check the machine">↻</button>
      </div>
    </div>
    ${byKind.map(([k, list]) => html`<div class="liblic-kind">${KIND_LBL[k] || k}</div>
      <div class="liblic-grid">
        ${list.map(l => html`<div class=${cls('liblic-card', l.installed === false && 'missing', l.manual && 'manual', l.only && 'elsewhere')}>
          <b>${esc(l.name)}${l.version ? html` <small class="muted">${esc(String(l.version))}</small>` : ''}</b>
          <span class="liblic-by">${esc(l.by || '')}</span>
          <span class="liblic-what muted">${esc(l.what || '')}</span>
          <span class="liblic-foot"><span class=${'liblic-lic lic-' + fam(l.license || '')}>${esc(l.license || '?')}</span>
            ${l.only ? html`<span class="liblic-state" title="golem uses it on its Linux rack only — nothing to install on this machine">Linux only</span>`
              : html`<span class=${cls('liblic-state', l.installed === true && 'ok', l.installed === false && 'no')} title=${l.installed == null ? 'not checked' : l.installed ? 'installed on this machine' : (l.manual ? 'install it yourself — see the note' : 'expected by golem, not found on this machine')}>${l.installed == null ? '' : l.installed ? '✓ installed' : (l.manual ? '⚠ install yourself' : '✗ missing')}</span>`}</span>
          <span class="liblic-url">${esc(String(l.url || '').replace(/^https:\/\//, ''))}</span>
        </div>`)}
      </div>`)}
  </div>`;
}

const SUB_TABS = [['golem', 'golem'], ['reaper', 'REAPER'], ['libs', 'Libraries']];

// ABOUT (mockups/settings-nav.html, écran 7 — ex-« Licenses ») : la version ET les mises à jour, puis les licences
export function LicensesPage({ rig, sub }) {
  const valid = id => SUB_TABS.some(([tid]) => tid === id);
  const [tab, setTabRaw] = useState(sub && valid(sub) ? sub : 'golem');
  useEffect(() => { if (sub && valid(sub)) setTabRaw(sub); }, [sub]);
  const setTab = id => { setTabRaw(id); go('system/about/' + id); };
  return html`
    <div class="system pg-fit">
      <div class="sys-tabs sub-tabs">
        ${SUB_TABS.map(([id, label]) => html`<button class=${cls('sys-tab', tab === id && 'on')}
          onClick=${() => setTab(id)}>${label}</button>`)}
      </div>
      ${tab === 'golem' ? html`<div class="pg-body"><div class="upd-grid"><${GolemUpdateCard} /><${GolemLicenseCard} /></div></div>`
      : tab === 'reaper' ? html`<div class="pg-body"><div class="upd-grid"><${ReaperVersioningCard} /><${ReaperLicenseCard} /></div></div>`
      : html`<${LibrariesPanel} />`}
    </div>`;
}
