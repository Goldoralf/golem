// SPDX-License-Identifier: GPL-3.0-or-later
// Connect ▸ golem.fm et Connect ▸ TONE3000 (ex-onglet API — mockups/settings-nav.html, écran 6) : clés Tone3000 +
// appairage golem.fm. Secrets masqués (champ vide = inchangé). (Les clés des services de séparation payants sont parties
// avec eux le 2026-10-31 : retirés de la v0.6, docs/private/launch-plan.md §3.)
// (l'assistant IA et ses clés ont quitté le rack le 2026-09-09 — il vit sur golem.fm)
import { html, useState, useEffect, useRef, useAsync, post, cls, esc, safeHref, LoadGuard, setTopAction } from './lib.js';
import { serviceBadges, withDemo } from './services-model.mjs';   // la pastille par sous-onglet (mockups/settings-badges.html)

const SUB_TABS = [['t3k', 'TONE3000'], ['mst', 'golem.fm']];

export function ApiPage({ rig, sub, bare }) {
  const badges = serviceBadges(withDemo((rig || {}).state));
  useEffect(() => { post('/api/services/check', {}).catch(() => {}); }, []);   // le verdict frais, pas celui du démarrage
  const [tab, setTab] = useState(sub === 'mst' ? 'mst' : 't3k');   // Connect ▸ golem.fm | Connect ▸ TONE3000
  useEffect(() => { setTab(sub === 'mst' ? 'mst' : 't3k'); }, [sub]);
  // « Ask golem » (docs/assistant.md §6) : le consentement se retire AUSSI d'ici, pas seulement depuis le tiroir de Health
  const [assist, setAssist] = useState(null);
  useEffect(() => { if (tab === 'mst') fetch('/api/health/assistant').then(r => r.json()).then(setAssist).catch(() => setAssist(null)); }, [tab]);
  const setAssistConsent = on => post('/api/health/assistant', { consent: on }).then(setAssist).catch(() => {});
  const { data, err, reload } = useAsync(() => fetch('/api/integrations').then(r => r.json()), []);
  const [t3k, setT3k] = useState({});        // valeurs saisies Tone3000 (vide = inchangé)
  const [saved, setSaved] = useState('');
  // 💾 Save CONTEXTUEL dans la topbar — l'effet est publié PLUS BAS (après la déclaration
  // de `mst`, qu'il lit pour l'état sale) mais toujours avant le early-return (règles des hooks).
  const saveRef = useRef(() => {});
  // ── OAuth : QR LAN sur le rack Linux (rack sans clavier) ; lien local sur Windows/macOS ──
  const [t3kAuthed, setT3kAuthed] = useState(null);
  const [t3kReason, setT3kReason] = useState('');     // pourquoi pas connecté (lignée morte, clé absente) — dit, pas deviné
  // golem appairé à golem.fm : la connexion passe par son RELAIS (rien à déclarer) — la clé à soi se range sous « Advanced »
  const [t3kPaired, setT3kPaired] = useState(false);
  const [t3kAdv, setT3kAdv] = useState(false);
  const [qr, setQr] = useState(null);                 // {qr, auth_url, redirect_uri} | null
  const pollRef = useRef(null);

  // ── golem.fm : appairage device-code (approbation SSO au téléphone/laptop). Le serveur vient de GOLEM_SERVER_URL
  // (.env, golem.fm par défaut) : plus de menu Advanced ni de jeton collé (2026-10-31) ──
  const [mstStatus, setMstStatus] = useState(null);   // {configured, paired, reachable, authed}
  const [pair, setPair] = useState(null);             // {code, approve_url, qr} pendant l'appairage
  const pairPollRef = useRef(null);
  const pingMst = () => { setMstStatus(null); fetch('/api/golemfm/status').then(r => r.json()).then(setMstStatus).catch(() => setMstStatus({ configured: false })); };
  // lot 8 (docs/diagnostics.md §5) : LA case — cochée par défaut, aucun bouton d'envoi nulle part.
  // Écrite tout de suite (pas via 💾) : c'est un consentement, pas une saisie.
  const [diagAuto, setDiagAuto] = useState(null);
  useEffect(() => { if (tab === 'mst') fetch('/api/diag').then(r => r.json()).then(d => setDiagAuto(!!d.auto)).catch(() => setDiagAuto(true)); }, [tab]);
  // docs/connect.md §5 : « Let golem.fm find this rack » — cochée par défaut, écrite tout de suite (consentement)
  const [presence, setPresenceState] = useState(null);
  const [where, setWhere] = useState(null);
  useEffect(() => {
    if (tab !== 'mst') return;
    fetch('/api/connect').then(r => r.json()).then(d => setPresenceState(!!d.presence)).catch(() => setPresenceState(true));
    fetch('/api/connect/where').then(r => r.json()).then(setWhere).catch(() => setWhere(null));
  }, [tab]);
  const setPresence = async (on) => { setPresenceState(on); const d = await post('/api/connect/settings', { presence: on }).catch(() => null); if (!d || !d.ok) { setPresenceState(!on); setSaved('✗ could not save'); } };
  const setDiag = async (on) => { setDiagAuto(on); const d = await post('/api/diag/settings', { auto: on }).catch(() => null); if (!d || !d.ok) { setDiagAuto(!on); setSaved('✗ could not save'); } };
  // état SALE = des saisies non sauvées existent (buffers t3k/keys/mst non vides, ou
  // ). Rend le 💾 IMPOSSIBLE à rater : bouton accent qui pulse +
  // mention « unsaved changes » (retour UX 2026-07-19 : le save invisible se faisait oublier).
  const dirty = Object.keys(t3k).length > 0;
  useEffect(() => {
    setTopAction(html`<div class="tb-action">
      ${dirty ? html`<span class="tb-dirty">● unsaved changes</span>` : saved ? html`<span class="tb-saved">${saved}</span>` : ''}
      <button class=${cls('save-btn', dirty && 'dirty')} title=${dirty ? 'save your changes' : 'save'}
        onClick=${() => saveRef.current()}>💾${dirty ? ' Save' : ''}</button></div>`);
    return () => setTopAction(null);
  }, [saved, dirty, tab]);
  useEffect(() => { if (tab === 'mst') pingMst(); return () => clearInterval(pairPollRef.current); }, [tab]);
  const startPair = async () => {
    const d = await post('/api/golemfm/pair', { device_name: 'golem rack' }).catch(e => ({ error: String(e) }));
    if (d.error || !d.ok) { setSaved('✗ ' + (d.error || 'pair failed')); return; }
    setPair(d);
    pairPollRef.current = setInterval(async () => {
      const st = await fetch('/api/golemfm/pair/status').then(r => r.json()).catch(() => null);
      if (st && st.approved) { clearInterval(pairPollRef.current); setPair(null); pingMst(); }
      else if (st && !st.active) { clearInterval(pairPollRef.current); setPair(null); setSaved('✗ pairing expired'); }
    }, 2000);
  };
  useEffect(() => {
    fetch('/api/t3k/auth/status').then(r => r.json()).then(d => { setT3kAuthed(!!d.authed); setT3kPaired(!!d.paired);
      setT3kReason(d.authed ? '' : ((d.relay || {}).error || d.reason || '')); }).catch(() => setT3kAuthed(false));
    return () => clearInterval(pollRef.current);
  }, []);
  const startQr = async (advanced) => {
    // le MOTIF du refus, pas « → 400 » : le bridge dit ce qui manque (le plus souvent la clé publique)
    const d = await post('/api/t3k/auth/start', advanced === true ? { advanced: true } : {}).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    // le refus s'affiche À CÔTÉ du bouton (la ligne d'état TONE3000), pas en vert dans la barre du haut
    // une réponse sans QR ni URL (bridge d'un autre âge, réponse interceptée par une sonde) ne doit pas casser la page
    if (d.error || !(d.qr || d.auth_url)) { setT3kAuthed(false); setT3kReason(d.error || 'unexpected answer from the bridge'); return; }
    setQr(d);
    pollRef.current = setInterval(async () => {
      const st = await fetch('/api/t3k/auth/status').then(r => r.json()).catch(() => null);
      if (st && st.authed) { clearInterval(pollRef.current); setQr(null); setT3kAuthed(true); setT3kReason(''); }
      // le relais s'est arrêté sans connexion (refusé, expiré) : on le DIT à côté du bouton, le QR s'en va
      else if (st && st.relay && !st.relay.running && st.relay.error && d.relay) { clearInterval(pollRef.current); setQr(null); setT3kReason(st.relay.error); }
    }, 2000);
  };
  if (!data) return html`<${LoadGuard} err=${err} reload=${reload} />`;
  // la coquille de la doc ne sert JAMAIS /api/integrations (des clés) : sans ces deux objets la page plantait
  // (« reading 'publishable_key' ») — elle se rend avec ses champs vides, comme un golem jamais configuré
  data.tone3000 = data.tone3000 || {};
  data.golemfm = data.golemfm || {};

  const save = async () => {
    await post('/api/integrations', { tone3000: t3k });
    setT3k({}); setSaved('✓ saved'); reload();
    if (tab === 'mst') pingMst();
  };
  saveRef.current = save;

  const secret = (label, mask, val, onIn) => html`<div class="set-row">
    <label>${label}</label>
    <input type="password" style="flex:1" autocomplete="off" spellcheck="false"
      placeholder=${mask.set ? (mask.hint + ' · set — blank keeps it') : 'not set'}
      value=${val || ''} onInput=${e => onIn(e.target.value)}
      onKeyDown=${e => e.key === 'Enter' && saveRef.current()} />
  </div>`;

  // NON APPAIRÉ, la clé d'abord et Connect ensuite (sans clé, Connect échoue) ; la raison sans son « où » — cette page
  // EST Settings ▸ Connect ▸ TONE3000 (audit 2026-10-31, #18)
  const t3kAuthRow = html`<div class="t3k-auth">
        <span class=${cls('t3k-dot', t3kAuthed && 'on')}></span>
        <span class="muted">${t3kAuthed == null ? 'checking…' : t3kAuthed ? 'Connected to TONE3000'
          : (t3kReason ? '✗ ' + t3kReason.replace(/ — (sign in|reconnect it|set it) .*$/, '') : 'Not connected') + (t3kPaired ? ' — sign in with your phone:' : ' — save your key, then sign in with your phone:')}</span>
        <button class="mini edit-only" onClick=${() => startQr(!t3kPaired)}>${t3kAuthed ? '↻ Sign in again' : '📱 Connect'}</button>
      </div>`;
  return html`<div class="api-page">
    ${bare ? '' : html`<div class="sys-tabs sub-tabs">
      ${SUB_TABS.map(([id, label]) => { const b = badges[id === 't3k' ? 't3k' : 'fm'];
        return html`<button class=${cls('sys-tab', tab === id && 'on')} title=${b ? b.text : ''}
        onClick=${() => setTab(id)}>${label}${b ? html`<i class=${'svc-dot ' + b.kind}></i>` : ''}</button>`; })}
    </div>`}

    ${tab === 't3k' ? html`<section class="card-panel" data-doc="connect.tone3000">
      <p class="muted">TONE3000 — the amps, pedals and cabinets your presets use. This golem signs in with your TONE3000 account and keeps its own session.</p>
      ${t3kPaired ? t3kAuthRow : ''}
      ${/* LA CLÉ À SOI (avant le relais, le seul chemin) : sans golem.fm elle est nécessaire, donc visible ; appairé, elle se
            range sous « Advanced » — un musicien n'a plus rien à coller ni à déclarer (2026-10-22) */''}
      ${t3kPaired ? html`<button class="linkish t3k-adv edit-only" onClick=${() => setT3kAdv(!t3kAdv)}>${t3kAdv ? '▾' : '▸'} Advanced — your own TONE3000 key</button>` : ''}
      ${!t3kPaired || t3kAdv ? html`<div class="t3k-own">
        <p class="muted">${t3kPaired ? 'Only if golem.fm cannot relay the sign-in. ' : 'Without golem.fm, this golem uses your own TONE3000 key. '}Create a key in
          tone3000.com ▸ Settings ▸ API Keys, paste it here and save 💾.</p>
        ${secret('Publishable key', data.tone3000.publishable_key, t3k.publishable_key, v => setT3k({ ...t3k, publishable_key: v }))}
        ${t3kPaired ? html`<button class="mini edit-only" onClick=${() => startQr(true)}>📱 Connect with my key</button>` : ''}
      </div>` : ''}
      ${t3kPaired ? '' : t3kAuthRow}
      ${qr ? html`<div class="qr-panel">
        ${!qr.desktop ? html`<svg class="qr" viewBox=${'0 0 ' + qr.qr.length + ' ' + qr.qr.length} shape-rendering="crispEdges">
          ${qr.qr.map((row, y) => row.map((c, x) => c ? html`<rect x=${x} y=${y} width="1" height="1" />` : ''))}
        </svg>` : ''}
        <div class="qr-help">
          ${qr.relay ? '' : html`<b>1.</b> Once: declare this return address in tone3000.com ▸ Settings ▸ API Keys:<br/>
          <code>${qr.redirect_uri}</code><br/>`}
          <b>${qr.relay ? '1' : '2'}.</b> ${qr.desktop ? html`<a href=${safeHref(qr.auth_url)} target="_blank" rel="noopener noreferrer">Open the TONE3000 sign-in on this computer</a>`
            : qr.relay ? 'Scan the QR with your phone and sign in to TONE3000.' : 'Scan the QR with your phone (on the same network as the golem) and sign in to TONE3000.'}<br/>
          <b>${qr.relay ? '2' : '3'}.</b> This panel turns green by itself.
          <div><button class="mini" onClick=${() => { clearInterval(pollRef.current); setQr(null); }}>cancel</button></div>
        </div>
      </div>` : ''}
      ${/* la carte « Factory sounds » ne vit plus qu'à un endroit : Content ▸ Factory (mockups/settings-nav.html) */''}
    </section>` : ''}

    ${/* DEUX COLONNES (mockups/settings-nav.html, écran 6) : l'appairage à gauche, les consentements à droite — en une
          colonne, la page débordait de 150 px à 1024×600 et poussait la barre de Connect hors de l'écran */''}
    ${tab === 'mst' ? html`<section class="card-panel mst-grid" data-doc="connect.golemfm"><div class="mst-l">
      <p class="muted">golem.fm — songs, backing tracks, tabs and the assistant. Pair once: this golem gets its own device token, revocable from golem.fm.</p>
      <div class="t3k-auth">
        <span class=${cls('t3k-dot', mstStatus && mstStatus.authed && 'on')}></span>
        <span class="muted">${mstStatus == null ? 'checking…'
          : !mstStatus.configured || !mstStatus.paired ? 'Not paired yet'
          : !mstStatus.reachable ? '✗ golem.fm is out of reach'
          : mstStatus.authed ? 'Paired with golem.fm' : '✗ golem.fm refused this golem (revoked?) — pair it again'}</span>
        <button class="mini" onClick=${pingMst}>↻ Test</button>
        <button class="mini edit-only" onClick=${startPair}>${mstStatus && mstStatus.authed ? '↻ Pair again' : '🔗 Pair'}</button>
      </div>
      ${/* LE SERVEUR SE DIT, IL NE SE CHOISIT PLUS (2026-10-31) : l'adresse de GOLEM_SERVER_URL en texte, pour qu'un
            développeur voie où il est appairé */''}
      ${data.golemfm.base_url ? html`<p class="muted small">Server: <code>${data.golemfm.base_url.replace(/^https?:\/\//, '')}</code></p>` : ''}
      ${/* une réponse sans matrice (`{ok: true}` seul : sans approve_url, ou écriture absorbée par la coquille ro)
            ne doit pas casser la page : pas de QR, le code et l'annulation restent */''}
      ${pair ? html`<div class="qr-panel">
        ${Array.isArray(pair.qr) ? html`<svg class="qr" viewBox=${'0 0 ' + pair.qr.length + ' ' + pair.qr.length} shape-rendering="crispEdges">
          ${pair.qr.map((row, y) => row.map((c, x) => c ? html`<rect x=${x} y=${y} width="1" height="1" />` : ''))}
        </svg>` : ''}
        <div class="qr-help">
          <b>Code: <code style="font-size:16px">${pair.code}</code></b><br/>
          Scan the QR (or type the code in golem.fm ▸ golem ▸ Access ▸ Pair a golem) on a device where you're logged in,
          check the code matches, and approve. This panel closes automatically.
          <div><button class="mini" onClick=${() => { clearInterval(pairPollRef.current); setPair(null); }}>cancel</button></div>
        </div>
      </div>` : ''}
      </div><div class="mst-r">
      ${/* golem.fm/connect NE SERT QU'UN GOLEM APPAIRÉ (audit 2026-10-31) : non appairé, l'adresse se dit en texte, au futur,
            et le QR du réseau local reste le chemin d'aujourd'hui */''}
      ${mstStatus && !mstStatus.paired ? html`<div class="diag-consent">
        <p class="muted">Once paired, band members open <b>golem.fm/connect</b> on their phone or tablet and land on this golem.
          Until then, a phone joins with the QR in Settings ▸ Connect ▸ Devices.
          ${where && where.urls && where.urls.length ? html` This golem: ${where.urls.map((u, i) => html`${i ? ' · ' : ''}<code>${u.replace('http://', '')}</code>`)}` : ''}</p>
      </div>` : html`<div class="diag-consent">
        <label class="diag-consent__row">
          <input type="checkbox" id="connect-presence" checked=${presence !== false} disabled=${presence == null} onChange=${e => setPresence(e.target.checked)} />
          <span><b>Let golem.fm find this rack</b></span>
        </label>
        <p class="muted">Band members open <b>golem.fm/connect</b> on their phone or tablet and land on this golem without typing an address.
          golem.fm learns this rack's local addresses and Wi-Fi name while it is on — never who is connected.
          ${/* à la suite, sans retour à la ligne : la place est comptée (2026-10-03) */''}
          ${where && where.urls && where.urls.length ? html` Reachable at ${where.urls.map((u, i) => html`${i ? ' · ' : ''}<code>${u.replace('http://', '')}</code>`)}.` : ''}</p>
      </div>`}
      <div class="diag-consent">
        <label class="diag-consent__row">
          <input type="checkbox" checked=${diagAuto !== false} disabled=${diagAuto == null} onChange=${e => setDiag(e.target.checked)} />
          <span><b>Allow this golem to send usage and bug reports to golem.fm</b></span>
        </label>
        <p class="muted">golem is open source — you can check exactly what it sends:${' '}
          <a href="https://github.com/Goldoralf/golem/blob/main/docs/diagnostics.md" target="_blank" rel="noopener">what is sent</a>.
          Reports go out automatically at startup, at shutdown and when a problem is detected.
          They never contain names, audio or credentials. golem.fm keeps them 90 days.</p>
      </div>
      ${assist && (assist.available || assist.consent) ? html`<div class="diag-consent">
        <label class="diag-consent__row">
          <input type="checkbox" checked=${!!assist.consent} onChange=${e => setAssistConsent(e.target.checked)} />
          <span><b>✦ Ask golem — send my questions from Health to golem.fm</b></span>
        </label>
        <p class="muted">A question and a summary of this golem's state, never a preset, song or person name, forwarded to the AI
          provider golem.fm uses. golem.fm keeps no text of it.</p>
      </div>` : ''}
    </div></section>` : ''}
  </div>`;
}


// ── LES CAPTURES D'USINE (docs/factory.md §0.1, 2026-10-13) : les patches d'usine NOMMENT leurs amplis, pédales et
// baffles TONE3000 ; le golem ne les livre pas, il les télécharge avec le compte de l'utilisateur, en un geste. Le
// compte est lu (/api/factory/captures `connected`) : sans lui le bouton dit quoi faire au lieu d'échouer.
export function FactoryCaptures({ authed }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = () => fetch('/api/factory/captures').then(r => r.json()).then(setD).catch(() => {});
  useEffect(() => { load(); }, [authed]);
  const running = d && d.download && d.download.phase === 'running';
  useEffect(() => { if (!running) return; const t = setInterval(load, 1500); return () => clearInterval(t); }, [running]);
  if (!d) return '';
  const miss = (d.missing || []).length, dl = d.download || {};
  const go = async () => { setErr(''); const r = await post('/api/factory/captures/download').catch(e => (e.body || { error: String(e) }));
    if (r && r.error) setErr(r.error); load(); };
  return html`<div class="fac-cap">
    <div class="fac-cap-hd"><b>Factory sounds</b>
      <span class=${cls('muted', !miss && 'ok')}>${miss ? `${d.present} of ${d.total} captures on this rack` : `all ${d.total} captures on this rack ✓`}</span></div>
    <p class="muted">The factory patches and presets use amps, pedals and cabs from TONE3000. golem does not ship them: they come from your TONE3000 account.</p>
    ${miss ? html`<div class="row">
        <button class="primary edit-only" disabled=${!d.connected || running} title=${d.connected ? '' : 'connect to TONE3000 first (Settings ▸ Connect ▸ TONE3000)'}
          onClick=${go}>${running ? `⬇ Downloading ${dl.done} of ${dl.total}…` : `⬇ Download the factory captures (${miss})`}</button>
        ${/* Settings ▸ Content ▸ Factory n'a RIEN au-dessus (« — above » renvoyait au vide) : le lien mène au compte */''}
        ${!d.connected ? html`<span class="muted">connect to TONE3000 first — <a href="#/system/connect/tone3000">Settings ▸ Connect ▸ TONE3000</a></span>` : ''}
        ${running && dl.current ? html`<span class="muted">${esc(dl.current)}</span>` : ''}</div>` : ''}
    ${dl.phase === 'done' && (dl.installed || []).length ? html`<p class="ok">✓ ${dl.installed.length} capture${dl.installed.length === 1 ? '' : 's'} downloaded.</p>` : ''}
    ${(dl.failed || []).length ? html`<div class="fac-cap-fail">${dl.failed.map(f => html`<div class="bad">✗ ${esc(f.title || 'tone ' + f.tone)} — ${esc(f.why)}</div>`)}</div>` : ''}
    ${err ? html`<p class="bad">✗ ${esc(err)}</p>` : ''}
  </div>`;
}
