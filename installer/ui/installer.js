// SPDX-License-Identifier: GPL-3.0-or-later
// GoleM installer — neuf écrans (docs/installer.md §2), Preact/htm sans build comme l'app.
// L'état vient du serveur local (installer/server.py) ; chaque appel porte le jeton de l'URL.
import { html, render, useState, useEffect, useRef } from '/vendor/htm-preact-standalone.module.js';

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const api = (path, body) => fetch(path, body === undefined
  ? { headers: { 'X-Golem-Token': TOKEN } }
  : { method: 'POST', headers: { 'X-Golem-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  .then(r => r.json());
const cls = (...a) => a.filter(Boolean).join(' ');
// la puce de licence d'un moteur libre : son identifiant réel (« gpl-2.0-or-later » → « free · GPL-2.0-or-later »),
// « free » seul quand le descripteur n'en déclare pas — jamais une licence supposée
const freeLicense = l => l ? 'free · ' + l.replace(/-or-later$/i, '').toUpperCase() + (/-or-later$/i.test(l) ? '-or-later' : '') : 'free';
const mb = n => n >= 1024 ? (n / 1024).toFixed(1) + ' GB' : Math.round(n) + ' MB';

const SCREENS = [
  ['before', 'Before you start'], ['play', 'Instrument'], ['checks', 'Checks'], ['engine', 'Audio engine'], ['reaper', 'Reaper'], ['where', 'Folder'], ['size', 'Size'],
  ['install', 'Install'], ['connect', 'Connect'], ['done', 'Done'],
];
// UNE installation, DEUX usages (docs/installer.md §4, FIXÉ 2026-10-16) : on ne choisit plus rien ici.
// L'INSTRUMENT (2026-10-27, bridge/first_run.py) : l'entrée 1 de la carte (guitare, basse, voix), la banque d'usine au
// pied, et pour la guitare cette banque ouverte sur sa première entrée. Claviers et batterie arrivent en USB-MIDI : l'entrée 1
// reste guitare. Tout se change ensuite dans l'app.
const PLAY = [
  ['guitar', 'Guitar', 'Input 1 is your guitar. The Factory Guitar sounds are on the foot, and golem opens on the first one.'],
  ['bass', 'Bass', 'Input 1 is your bass. The Factory Bass sounds are on the foot.'],
  ['keys', 'Keys', 'The Factory Keys sounds are on the foot. Plug your keyboard in by USB.'],
  ['drums', 'Drums', 'The Factory Drums sounds are on the foot. Plug your drum kit in by USB.'],
  ['voice', 'Voice', 'Input 1 is your microphone. The Factory Voice sounds are on the foot.'],
];
// golem s'ouvre dans une fenêtre (golem) ou sans fenêtre (golem Server, une tablette est l'écran) — les deux sont
// posés. Démarrer avec l'ordinateur et verrouiller la machine sont des réglages de l'app (System ▸ Dashboard).

const FM_PITCH = 'Backing tracks, tabs, song sharing, your captures, and a vault that backs up your presets — from your golem.fm account.';
const T3K_PITCH = 'Amp, pedal and cab captures. The factory sounds come from here too, through your own TONE3000 account.';

// ── l'écran Connect sous LINUX (2026-10-15) : deux cartes à l'installateur, plus l'app dans un cadre ──────────────
// golem tourne (étape « start ») : on lit et on agit PAR LE SERVEUR DE L'INSTALLATEUR (/api/link…), qui relaie vers
// le bridge une courte liste de routes (server.py BRIDGE_ALLOW). La page n'appelle jamais :8770 elle-même.
// En --dry le serveur simule golem (installer/dry_bridge.py) : le vrai rack n'est jamais touché.
// ── l'écran Done : la carte « Continue on a tablet » (docs/installer.md §4) ─────────────────────────────────────────
function TabletCard({ tab }) {
  if (tab.phase === 'starting') return html`<div class="card tablet"><b>Starting golem Server…</b>
    <p class="muted">No window opens: a tablet or a phone on your Wi-Fi will be the screen. The first start can take a minute.</p></div>`;
  if (tab.phase === 'error') return html`<div class="card tablet"><b class="warn">golem is not answering yet</b>
    <p class="muted">${tab.error}</p></div>`;
  const i = tab.info || {};
  return html`<div class="card tablet"><div class="tablet-row">
      <img src=${'/api/tablet/qr?t=' + encodeURIComponent(TOKEN) + '&v=' + Date.now()} alt="QR: open golem on the tablet" />
      <div class="tablet-txt">
        <span class="muted">golem runs without a window. On the tablet, scan or open</span>
        <b class="tablet-url">${i.url}</b>
        ${!i.named ? html`<span class="muted small">on the same Wi-Fi as this computer</span>` : ''}
        ${i.code ? html`<span class="muted">First tablet: open <b>${i.pair_url}</b> and type (valid 10 min, once)</span>
          <b class="tablet-code">${i.code}</b>
          <span class="muted small">That tablet becomes the main device: it can show golem on this computer again, or stop it.</span>`
        : html`<span class="muted">Your main tablet opens golem directly.</span>`}
      </div></div>
    <div class="row"><span class="muted small">golem keeps running when the installer closes.</span></div></div>`;
}

function ConnectLive({ open }) {
  const [L, setL] = useState(null);                    // GET /api/link
  const [busy, setBusy] = useState('');
  const [pair, setPair] = useState(null);              // {code, approve_url, unreachable?} pendant l'appairage
  const [fmMsg, setFmMsg] = useState('');
  const [tokOpen, setTokOpen] = useState(false);
  const [tok, setTok] = useState('');
  const [key, setKey] = useState('');
  const [keyEdit, setKeyEdit] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);       // « No golem.fm? » : la clé à soi, repliée par défaut
  const [keyMsg, setKeyMsg] = useState('');
  const [signin, setSignin] = useState(null);          // {auth_url, redirect_uri} pendant la connexion TONE3000
  const [t3Msg, setT3Msg] = useState('');
  const [fac, setFac] = useState(null);                // GET /api/link/factory (frais pendant le téléchargement)
  const timers = useRef({});
  const stop = k => { clearInterval(timers.current[k]); delete timers.current[k]; };
  const every = (k, ms, fn) => { stop(k); timers.current[k] = setInterval(fn, ms); };
  useEffect(() => () => Object.keys(timers.current).forEach(stop), []);
  const watchDl = () => every('dl', 1500, async () => {
    const f = await api('/api/link/factory').catch(() => null); if (!f) return;
    setFac(f); if (!f.download || f.download.phase !== 'running') stop('dl');
  });
  const load = async () => {
    const d = await api('/api/link').catch(() => ({ up: false }));
    setL(d); if (d.factory) setFac(d.factory);
    if (d.factory && d.factory.download && d.factory.download.phase === 'running') watchDl();
    return d;
  };
  useEffect(() => { load(); }, []);

  const pairStart = async () => {
    setBusy('pair'); setFmMsg('');
    const r = await api('/api/link/pair', {}).catch(e => ({ ok: false, error: String(e) }));
    setBusy('');
    if (!r.ok) { setFmMsg('✗ ' + r.error); if (r.down) load(); return; }
    setPair(r);
    every('pair', 2000, async () => {
      const s = await api('/api/link/pair').catch(() => null); if (!s) return;
      if (s.approved) { stop('pair'); setPair(null); load(); }
      else if (!s.active) {
        stop('pair'); setPair(null);
        setFmMsg('✗ ' + (s.down ? s.error : s.error === 'already claimed' ? 'this code was already used — pair again' : 'the code expired — pair again'));
      } else setPair(p => p && { ...p, unreachable: !!s.unreachable });
    });
  };
  const pairCancel = () => { stop('pair'); setPair(null); };
  const saveToken = async () => {
    setBusy('token'); setFmMsg('');
    const r = await api('/api/link/token', { token: tok }).catch(e => ({ ok: false, error: String(e) }));
    setBusy('');
    if (!r.ok) { setFmMsg('✗ ' + r.error); return; }
    setTok(''); setTokOpen(false); load();
  };
  const saveKey = async () => {
    setBusy('key'); setKeyMsg('');
    const r = await api('/api/link/t3k-key', { key }).catch(e => ({ ok: false, error: String(e) }));
    setBusy('');
    if (!r.ok) { setKeyMsg('✗ ' + r.error); return; }
    setKey(''); setKeyEdit(false); setKeyMsg(''); load();
  };
  const signIn = async () => {
    setBusy('signin'); setT3Msg('');
    const r = await api('/api/link/t3k-signin', {}).catch(e => ({ ok: false, error: String(e) }));
    setBusy('');
    if (!r.ok) { setT3Msg('✗ ' + r.error); return; }
    setSignin(r); if (r.open_error) setT3Msg('✗ ' + r.open_error);
    every('t3k', 2500, async () => {
      const s = await api('/api/link/t3k').catch(() => null);
      if (s && s.authed) { stop('t3k'); setSignin(null); setT3Msg(''); load(); }
    });
  };
  const download = async () => {
    setBusy('dl'); setT3Msg('');
    const r = await api('/api/factory/download', {}).catch(e => ({ error: String(e) }));
    setBusy('');
    if (r && r.error) { setT3Msg('✗ ' + r.error); return; }
    watchDl();
    const f = await api('/api/link/factory').catch(() => null); if (f) setFac(f);
  };

  if (!L) return html`<p class="muted">asking golem…</p>`;
  if (!L.up) return html`<div class="card"><b class="warn">The rack is not answering yet</b>
    <p class="muted">Start it (the launcher, or <code>golem</code>) and tap ↻ — or skip and do it later in golem, Settings ▸ API.</p>
    <div class="row"><button class="btn mini" onClick=${() => { setL(null); load(); }}>↻ check again</button></div></div>`;
  if (L.error) return html`<div class="card"><b class="warn">golem answered with an error</b><p class="muted">${L.error}</p>
    <div class="row"><button class="btn mini" onClick=${() => { setL(null); load(); }}>↻ check again</button></div></div>`;

  const fm = L.golemfm, t3 = L.t3k, srv = fm.server || {};
  const fmChip = pair ? html`<span class="chip accentchip">waiting for approval</span>`
    : fm.authed ? html`<span class="chip okchip">✓ paired</span>`
    : fm.paired && fm.reachable ? html`<span class="chip warnchip">token refused</span>`
    : fm.configured && !fm.reachable ? html`<span class="chip warnchip">unreachable</span>`
    : html`<span class="chip">not paired</span>`;
  const f = fac || {}, dl = f.download || {};
  const running = dl.phase === 'running';
  const t3Chip = t3.authed ? html`<span class="chip okchip">✓ signed in</span>`
    : signin ? html`<span class="chip accentchip">signing in…</span>`
    : html`<span class="chip">not signed in</span>`;

  return html`<div class="link-grid">
    <section class="card link">
      <div class="link-hd"><b class="link-name">golem.fm</b>${fmChip}</div>
      <p class="muted">${FM_PITCH}</p>
      <div class="link-body">
        ${pair ? html`
          <span class="muted small">Your code</span>
          <div class="pair-code">${pair.code}</div>
          <div class="row"><button class="btn primary" onClick=${() => open(pair.approve_url || srv.url || 'https://' + srv.host)}>Open golem.fm ↗</button>
            <button class="btn ghost" onClick=${pairCancel}>Cancel</button></div>
          <p class="muted">Sign in or sign up there, check that the code matches, and approve.
            ${pair.approve_url ? '' : ' Type it in golem ▸ Access ▸ Pair a golem.'}</p>
          <p class=${cls('small', pair.unreachable ? 'warn' : 'muted')}>${pair.unreachable ? '⚠ golem.fm is not answering — still waiting' : '⏳ waiting for your approval — this card updates by itself'}</p>`
        : fm.authed ? html`
          <div class="paired"><span class="ok">✓ Paired</span><span>— ${fm.band ? fm.band : 'your golem.fm account'}</span></div>
          <p class="muted">This golem has its own device token. You can revoke it on golem.fm, golem ▸ Access ▸ Who can reach your golems.</p>`
        : html`
          <div class="row"><button class="btn primary" disabled=${busy === 'pair'} onClick=${pairStart}>${busy === 'pair' ? '⏳ asking golem.fm…' : fm.paired ? '↻ Pair this golem again' : 'Pair this golem'}</button></div>
          <p class="muted small">You sign in (or sign up) on golem.fm in your browser — golem never sees your password.</p>
          ${fm.paired && fm.reachable ? html`<p class="warn small">The saved token was refused (revoked?) — pair again.</p>` : ''}
          ${fm.configured && !fm.reachable ? html`<p class="warn small">golem.fm does not answer at ${srv.host} — check the Internet connection, then ↻.</p>` : ''}
          ${fm.error ? html`<p class="warn small">${fm.error}</p>` : ''}`}
        ${fmMsg ? html`<p class="bad small">${fmMsg}</p>` : ''}
      </div>
      ${!pair && !fm.authed ? html`<div class="link-more">
        <button class="linkbtn" onClick=${() => setTokOpen(!tokOpen)}>${tokOpen ? '▾' : '▸'} I have a device token</button>
        ${tokOpen ? html`<div class="field"><input type="password" autocomplete="off" spellcheck="false" placeholder="paste the token from golem.fm ▸ golem ▸ Access ▸ Manual token"
            value=${tok} onInput=${e => setTok(e.target.value)} onKeyDown=${e => e.key === 'Enter' && tok && saveToken()} />
          <button class="btn" disabled=${!tok || busy === 'token'} onClick=${saveToken}>Save</button></div>` : ''}
      </div>` : ''}
      <div class="link-ft"><span>Server: <b>${srv.host || 'not set'}</b>${srv.label && srv.label !== 'Production' ? ' · ' + srv.label : ''}</span>
        ${!pair ? html`<button class="linkbtn" onClick=${load}>↻</button>` : ''}</div>
    </section>

    <section class="card link">
      <div class="link-hd"><b class="link-name">TONE3000</b>${t3Chip}</div>
      <p class="muted">${T3K_PITCH}</p>
      <ol class="link-steps">
        ${/* LE RELAIS (2026-10-23) : appairé à golem.fm, golem se connecte à TONE3000 SANS clé — golem.fm passe la
              connexion (bridge/routes_t3k.py _relay_cfg). La clé à soi n'est plus que le repli d'un golem sans golem.fm. */''}
        <li class=${cls((fm.authed || (t3.key.set && !keyEdit)) && 'done')}><i>${fm.authed || (t3.key.set && !keyEdit) ? '✓' : '1'}</i><div>
          ${fm.authed ? html`<b>Through golem.fm</b><span class="muted small">No key needed: golem.fm passes the sign-in on to this golem.</span>`
          : t3.key.set && !keyEdit ? html`<div class="row"><b>Your own key</b><span class="muted">saved (${t3.key.hint})</span>
              <button class="linkbtn" onClick=${() => setKeyEdit(true)}>change</button></div>`
          : html`<b>Pair golem.fm first</b>
            <span class="muted small">golem.fm then passes the TONE3000 sign-in on to this golem: no key to paste.</span>
            <button class="linkbtn" onClick=${() => setKeyOpen(!keyOpen)}>${keyOpen || keyEdit ? '▾' : '▸'} No golem.fm? Use your own TONE3000 key</button>
            ${keyOpen || keyEdit ? html`<div class="field"><input type="password" autocomplete="off" spellcheck="false" placeholder="paste it from tone3000.com ▸ Settings ▸ API Keys"
                value=${key} onInput=${e => { setKey(e.target.value); setKeyMsg(''); }} onKeyDown=${e => e.key === 'Enter' && key && saveKey()} />
              <button class="btn" disabled=${!key || busy === 'key'} onClick=${saveKey}>Save</button>
              ${keyEdit ? html`<button class="btn ghost" onClick=${() => { setKeyEdit(false); setKey(''); setKeyMsg(''); }}>Cancel</button>` : ''}</div>
            <span class="muted small">A publishable key names golem to TONE3000 — it is not a secret. <button class="linkbtn" onClick=${() => open('https://www.tone3000.com')}>tone3000.com ↗</button></span>` : ''}
            ${keyMsg ? html`<span class="bad small">${keyMsg}</span>` : ''}`}
        </div></li>
        <li class=${cls(t3.authed && 'done', !(fm.authed || t3.key.set) && 'off')}><i>${t3.authed ? '✓' : '2'}</i><div>
          ${t3.authed ? html`<b>Signed in to TONE3000</b>`
          : signin ? html`<b>Finish the sign-in in your browser</b>
            <span class="muted small">⏳ this card updates by itself. <button class="linkbtn" onClick=${() => open(signin.auth_url)}>Open the sign-in page again ↗</button></span>
            ${signin.redirect_uri ? html`<span class="muted small">First time? TONE3000 must know golem's address: add${' '}<code>${signin.redirect_uri}</code>${' '}to your key's redirect URIs (tone3000.com ▸ Settings ▸ API Keys), then sign in again.</span>` : ''}`
          : html`<div class="row"><button class="btn primary" disabled=${!(fm.authed || t3.key.set) || busy === 'signin'} onClick=${signIn}>Sign in to TONE3000</button>
              ${!(fm.authed || t3.key.set) ? html`<span class="muted small">pair golem.fm first</span>` : ''}</div>
            ${t3.reason && !/not signed in|publishable key/i.test(t3.reason) ? html`<span class="warn small">${t3.reason}</span>` : ''}`}
        </div></li>
        <li class=${cls(f.up && !f.missing && 'done', !t3.authed && 'off')}><i>${f.up && !f.missing ? '✓' : '3'}</i><div>
          <div class="row"><b>Factory sounds</b>${f.up ? html`<span class="muted small">${f.present} of ${f.total} captures on this golem</span>` : ''}</div>
          ${f.up && !f.missing ? html`<span class="ok small">✓ all ${f.total} factory captures are on this golem</span>`
          : running ? html`<div class="bar"><i style=${'width:' + (dl.total ? Math.round(dl.done / dl.total * 100) : 0) + '%'}></i></div>
            <span class="muted small">⬇ downloading ${dl.done} of ${dl.total}${dl.current ? ' — ' + dl.current : ''}…</span>`
          : html`<span class="muted small">The factory patches use amps, pedals and cabs from TONE3000 (about 11 MB). golem does not ship them: it downloads them with your account.</span>
            <div class="row"><button class="btn" disabled=${!t3.authed || !f.up || busy === 'dl'} onClick=${download}>${dl.phase === 'done'
              ? `↻ Try the ${f.missing} missing capture${f.missing === 1 ? '' : 's'} again` : `⬇ Download the factory captures${f.missing ? ' (' + f.missing + ')' : ''}`}</button></div>`}
          ${(dl.failed || []).length && !running ? dl.failed.slice(0, 2).map(x => html`<span class="bad small">✗ ${x.title || 'tone ' + x.tone} — ${x.why}</span>`) : ''}
        </div></li>
      </ol>
      ${t3Msg ? html`<p class="bad small">${t3Msg}</p>` : ''}
    </section>
  </div>`;
}

// ── LA LICENCE REAPER (écran 3, 2026-10-16) : coller le texte OU choisir le fichier .rk (lu ICI, envoyé en texte).
// Le serveur l'écrit dans le dossier de ressources de REAPER de CE système — la même écriture que Settings ▸ Licenses
// (bridge/reaper_license.py). Il ne renvoie jamais la licence : seulement « présente ». Facultative.
const LIC_MAX = 64 * 1024;
function LicenseCard({ present, dry }) {
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);              // {name, size, text} — le fichier choisi, lu dans la page
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [saved, setSaved] = useState(false);
  const fileEl = useRef(null);
  const pick = e => {
    const f = e.target.files && e.target.files[0]; e.target.value = '';
    if (!f) return;
    setMsg('');
    if (f.size > LIC_MAX) { setFile(null); setMsg('✗ this file is larger than 64 KB — a REAPER license is a short text; check the file'); return; }
    const rd = new FileReader();
    rd.onload = () => { setFile({ name: f.name, size: f.size, text: String(rd.result || '') }); setText(''); };
    rd.onerror = () => setMsg('✗ could not read this file');
    rd.readAsText(f);
  };
  const value = file ? file.text : text;
  const save = async () => {
    setBusy(true); setMsg('');
    const d = await api('/api/reaper/license', { license: value }).catch(e => ({ ok: false, error: String(e) }));
    setBusy(false);
    if (!d.ok) { setMsg('✗ ' + (d.error || 'could not save the license')); return; }
    setText(''); setFile(null); setReplace(false); setSaved(true);
  };
  const form = !present || replace;
  return html`<div class="card lic">
    <div class="row"><b>Your REAPER license</b><span class="muted">— optional</span><span class="grow"></span>
      ${present && !form ? html`<span class="chip okchip">✓ on this computer</span>` : ''}</div>
    ${saved && !form ? html`<p class="ok">✓ license saved${dry ? ' (dry run — nothing written)' : ''} — REAPER reads it when it starts: no evaluation reminder.</p>`
    : present && !form ? html`<p><b class="ok">✓ a REAPER license is already on this computer</b> <span class="muted">— REAPER will use it.</span></p>` : ''}
    ${present && !form ? html`<div class="row"><button class="linkbtn" onClick=${() => { setReplace(true); setSaved(false); setMsg(''); }}>Replace it with another license…</button></div>`
    : html`<p class="muted small">Bought REAPER? Paste the text of your license, or pick the <code>.rk</code> file you received. golem puts it in REAPER's settings folder on this computer${present ? ', in place of the one there' : ''}. Without it REAPER runs fully, with a reminder. You can also add it later in Settings ▸ Licenses.</p>
      ${file ? html`<div class="lic-file"><span class="chip okchip">✓ ${file.name}</span><span class="muted small">${file.size < 1024 ? file.size + ' bytes' : (file.size / 1024).toFixed(1) + ' KB'} read — ready to save</span>
          <button class="linkbtn" onClick=${() => setFile(null)}>clear</button></div>`
      : html`<textarea class="lic-in" rows="3" spellcheck="false" autocomplete="off" placeholder="paste your REAPER license here…"
          value=${text} onInput=${e => { setText(e.target.value); setMsg(''); }}></textarea>`}
      <div class="row">
        <button class="btn mini" onClick=${() => fileEl.current && fileEl.current.click()}>Choose the .rk file…</button>
        <input ref=${fileEl} type="file" accept=".rk,text/plain" class="lic-pick" onChange=${pick} />
        ${present && replace ? html`<button class="btn mini ghost" onClick=${() => { setReplace(false); setText(''); setFile(null); setMsg(''); }}>Cancel</button>` : ''}
        <span class="grow"></span>
        ${msg ? html`<span class="bad small">${msg}</span>` : ''}
        <button class="btn mini primary" disabled=${busy || !value.trim()} onClick=${save}>${busy ? 'saving…' : 'Save license'}</button>
      </div>`}
  </div>`;
}

// ── LA PAGE « Before you start » et L'ÉCRAN D'INSTALLATION EN PHASES (2026-10-23, maquette validée) ─────────
// Avant : la trace brute du shell — les warnings de compilation font paniquer — et un bouton qu'on cliquait cinq fois.
// Maintenant : des phases nommées (installer/phases.py, marqueurs de provision/install.sh), chacune avec son temps,
// un décompte corrigé par la vitesse observée, et la trace repliée sous « Show details » (pour le support).
const clock = s => s == null ? '' : Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0');
const about = s => s < 45 ? 'less than a minute' : s < 90 ? 'about 1 min' : 'about ' + Math.round(s / 60) + ' min';
const short = s => s < 60 ? Math.max(5, Math.round(s / 5) * 5) + ' s' : Math.round(s / 60) + ' min';
const hhmm = t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
const gb = mbv => mbv >= 1024 ? (mbv / 1024).toFixed(1) + ' GB' : Math.round(mbv) + ' MB';
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const took = s => Math.floor(s / 60) + ' min ' + String(Math.round(s % 60)).padStart(2, '0');

function Before({ est, uac, U }) {
  const b = U.before || {};
  return html`<h1>Before you start</h1>
    <div class="two"><div class="card"><div class="big">${est ? 'About ' + Math.max(5, Math.round(est / 300) * 5) + ' minutes' : 'Plan for half an hour'}</div>
      <p class="muted">${b.measured || 'A slower computer or connection takes longer. The install downloads the plugins and the sounds you choose.'}</p></div>
    <div class="card p0"><b>During the install</b><ul class="muted">
      <li><b class="hi">Click each button once.</b> Some steps work for minutes without showing anything new — that is normal: the screen tells you what it is doing and how long is left.</li>
      <li><b class="hi">Keep this window open</b> — you can use the computer meanwhile.</li>
      <li><b class="hi">Stay connected</b> to the internet, and plug a laptop in.</li></ul></div></div>
    <div class="card p0"><b>What you will be asked</b><ul class="muted">
      ${uac ? html`<li><b class="hi">${U.os_label || 'the system'}'s permission, once</b> — for the parts that go in Program Files;</li>`
        : html`<li>your computer password, <b class="hi">once</b> — for the system packages and the real-time audio setup;</li>`}
      <li>where to put golem, and which sounds to download;</li>
      <li>at the end, optionally: link golem.fm and TONE3000 (you can do it later).</li></ul></div>
    <p class="muted">${b.not_before_gig || 'Not before a gig: the first start needs a check with your instrument.'}</p>`;
}

function PhaseRow({ p, done, retry, onRetryItem }) {
  const cl = { ok: 'ok', warn: 'warnp', fail: 'failp', running: 'run', pending: 'todo' }[p.state];
  const icon = { ok: '✓', warn: '⚠', fail: '✗', running: '●', pending: '○' }[p.state];
  const right = p.state === 'running' ? clock(p.elapsed) + (p.left != null ? ' · ~' + short(p.left) + ' left' : '')
    : p.state === 'pending' ? (p.est ? '~' + short(p.est) : '')
    : p.skipped ? 'nothing to do' : clock(p.secs);
  return html`<div class=${cls('ph', cl)}><i>${icon}</i><span>${p.label}</span><small>${right}</small>
    ${p.state === 'running' && (p.sub || p.progress) ? html`<span class="sub">${p.sub}${p.progress
      ? (p.sub ? ' · ' : '') + gb(p.progress.done) + ' of ' + gb(p.progress.total) : ''}</span>` : ''}
    ${(p.warns || []).map(w => {
      const [head, ...rest] = w.text.split(' — ');
      const mine = retry && retry.id === w.retry;
      return html`<span class="sub"><span class="w">${head}</span>${rest.length ? ' — ' + rest.join(' — ') : ''}
        ${w.retry && done ? (mine && retry.state === 'running' ? html` <b>⏳ trying again…</b>`
          : html` <button class="linkbtn" disabled=${retry && retry.state === 'running'} onClick=${() => onRetryItem(w.retry)}>↻ Try again</button>${mine && retry.state === 'fail' ? html` <span class="bad">failed again — see details</span>` : ''}`) : ''}</span>`;
    })}</div>`;
}

// LE RAPPORT D'ÉCHEC (docs/diagnostics.md §7.1, 2026-10-27) : rien ne part sans ce clic ; « What is in it » dit tout
function ReportCard({ r, onSend }) {
  const [what, setWhat] = useState(false);
  r = r || {};
  return html`<div class="report">
    ${r.state === 'sent' ? html`<p class="ok">✓ Report sent. Quote <b>${r.code}</b> if you write to us.</p>`
    : r.state === 'dry' ? html`<p class="muted">(dry run) the report was built, not sent: <code>${r.path}</code></p>`
    : html`<div class="row"><button class="btn" disabled=${r.state === 'sending'} onClick=${onSend}>${r.state === 'sending' ? '⏳ sending…' : r.state === 'fail' ? '↻ Send the report again' : '✉ Send this report to golem'}</button>
        <button class="linkbtn" onClick=${() => setWhat(!what)}>${what ? 'Hide' : 'What is in it'}</button></div>
      ${r.state === 'fail' ? html`<p class="bad">${r.error}${r.path ? html` — the report is saved in <code>${r.path}</code>: you can send it by hand.` : ''}</p>` : ''}`}
    ${what && r.state !== 'sent' ? html`<p class="muted small">This computer (system, processor, memory), the golem version, the steps and how long each took,
      which one failed and its last error line, the checks, your choices on these screens (packs, engine, instrument), and
      the last part of the install output. Your user name, computer name, folders, network addresses, password and the
      keys you typed are erased first. Nothing is sent until you tap the button.</p>` : ''}</div>`;
}

function InstallRun({ st, uac, U, starting, onStart, onRetryItem, onStop, onReport, details, setDetails, log, logEl }) {
  const I = st.install || {};
  const phs = I.phases || st.steps.map(s => ({ id: s.id, label: s.label, state: s.state, secs: s.secs }));
  const fresh = !st.running && !st.done && !st.error && st.steps.every(s => s.state === 'pending');
  const warns = phs.reduce((n, p) => n + (p.warns || []).length, 0);
  const failed = phs.find(p => p.state === 'fail');
  const prog = I.progress != null ? I.progress : st.steps.filter(s => s.state === 'ok').length / st.steps.length;
  const running = phs.find(p => p.state === 'running');
  return html`
    ${st.done ? html`<h1>Installed ${I.elapsed ? html`<small>in ${took(I.elapsed)}</small>` : ''}</h1>`
      : fresh ? html`<h1>Install <small>${st.dir}</small></h1>` : html`<h1>Installing <small>${st.dir}</small></h1>`}
    ${fresh && uac ? html`<div class="card">${U.permission
      ? html`<p>${U.permission[0]}</p><p class="muted">${U.permission[1]}</p>`
      : html`<p>Installing needs <b>Windows' permission, once</b>: a Windows prompt asks you to allow the setup to install the Visual C++ runtime, Reaper and the plugins golem plays (NAM, AVL Drumkits, Vitalium) in Program Files, and one firewall rule so Reaper accepts nothing from the network. Approve it when it appears — it may blink in the taskbar.</p>
        <p class="muted">That is the only part that runs as administrator. golem itself is copied to your folder and always runs as you; no password is asked or kept.</p>`}</div>` : ''}
    ${fresh ? html`<div class="eta"><b>${I.total_est ? cap(about(I.total_est)) : 'Ready'}</b>
        <span class="muted">${I.total_est ? 'for everything below · you can use the computer meanwhile' : 'each step below shows its time'}</span>
        <span class="grow"></span>
        <button class="btn primary" disabled=${starting} onClick=${onStart}>${starting ? '⏳ starting…' : '▶ Install now'}</button></div>`
    : st.running ? html`<div class="eta"><b>${I.left != null ? cap(about(I.left)) + ' left' : 'Installing…'}</b>
        <span class="muted">${I.elapsed >= 60 ? Math.floor(I.elapsed / 60) + ' min done · ' : ''}${I.started ? 'started at ' + hhmm(I.started) + ' · ' : ''}you can use the computer meanwhile</span></div>
      <div class="pbar"><i style=${'width:' + Math.round(Math.min(1, prog) * 100) + '%'}></i></div>
      ${/* LE SILENCE (2026-10-24, un testeur Windows : 16 min figé sur « golem itself ») : passé stall_secs sans une ligne,
            l'écran le dit et propose d'arrêter l'étape — Retry la reprend, ce qui est fait reste fait */''}
      ${st.quiet != null && st.stall_secs && st.quiet >= st.stall_secs ? html`<div class="card warncard">
        <b class="warn">Nothing new for ${Math.floor(st.quiet / 60)} min${running ? ' on « ' + running.label + ' »' : ''}</b>
        <p class="muted">${st.stoppable
          ? 'Some steps work quietly for a while. If it stays like this, stop the step, then tap Retry: what is done stays done.'
          : 'This step runs with Windows\' permission: look for a Windows prompt in the taskbar, or wait.'}</p>
        ${st.stoppable ? html`<div class="row"><button class="btn" onClick=${onStop}>■ Stop this step</button></div>` : ''}</div>` : ''}`
    : st.done && warns ? html`<div class="card warncard"><b class="warn">golem is installed — ${warns === 1 ? '1 thing' : warns + ' things'} will not play yet</b>
        <p class="muted">Everything else plays. Each line says what is missing and what to do; golem shows the same in Settings ▸ Health.</p></div>`
    : st.done ? html`<p class="ok">✓ everything is installed — tap Next.</p>`
    : st.error ? html`<div class="card failcard"><b class="bad">✗ ${failed ? failed.label : 'A step'} stopped the install</b>
        <p class="muted">What was done stays done: Retry starts again from this step. Show details tells why (${st.error}).</p>
        <div class="row"><button class="btn primary" disabled=${starting} onClick=${onStart}>${starting ? '⏳ starting…' : '↻ Retry from the failed step'}</button></div>
        <${ReportCard} r=${st.report} onSend=${onReport} /></div>` : ''}
    <div class="phs">${phs.map(p => html`<${PhaseRow} p=${p} done=${st.done} retry=${st.retry} onRetryItem=${onRetryItem} />`)}</div>
    ${fresh ? '' : html`<button class="details" onClick=${() => { setDetails(!details);
      setTimeout(() => logEl.current && logEl.current.scrollIntoView({ block: 'end' }), 0); }}>${details ? '▾ Hide details' : '▸ Show details (the full output, for support)'}</button>`}
    ${details && !fresh && st.log_file ? html`<p class="muted small">The full output is also saved in <code>${st.log_file}</code> — send it with a screenshot if something goes wrong.</p>` : ''}
    ${details && !fresh ? html`<div class="log short" ref=${logEl}>${log.length ? log.map(l => html`<span class=${cls('ln', l.line.startsWith('$') && 'cmd', l.line.startsWith('✗') && 'err', l.line.startsWith('▶') && 'hd')}>${l.line}</span>`) : html`<span class="ln muted">the output shows here</span>`}</div>` : ''}`;
}

function App() {
  const [st, setSt] = useState(null);
  const [i, setI] = useState(0);
  const [checks, setChecks] = useState(null);
  const [reaper, setReaper] = useState(null);
  // écran Engine (COQUILLE 2026-10-06, docs/audio-engine-choice.md §6) : les descripteurs de moteur, lus
  // par le serveur dans la source. Un seul est sélectionnable aujourd'hui (Reaper, coché par défaut) ;
  // l'écran « Reaper » qui suit reste celui qui l'installe — le jour d'un second moteur, il suivra le choix.
  const [engines, setEngines] = useState(null);
  const [size, setSize] = useState(null);
  const [dir, setDir] = useState(null);
  const [pw, setPw] = useState('');
  const [pwErr, setPwErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState([]);
  const logN = useRef(0); const logEl = useRef(null);
  // l'écran Connect en deux champs (Windows, U.connect === 'form') : l'état masqué et les saisies
  const [conn, setConn] = useState(null);
  const [keys, setKeys] = useState({ golem_token: '', t3k_key: '' });
  const [connMsg, setConnMsg] = useState('');
  const [connWhere, setConnWhere] = useState([]);       // la carte (ou les deux) dont la clé vient d'être enregistrée
  const [finishErr, setFinishErr] = useState('');
  const [vital, setVital] = useState(null);
  // LES CAPTURES D'USINE (docs/factory.md §6 ter) : connexion TONE3000 puis téléchargement, par golem lancé en serveur
  const [fac, setFac] = useState(null);
  const [facMsg, setFacMsg] = useState('');
  const [facSignin, setFacSignin0] = useState(null);
  const facSigninRef = useRef(null);                   // lu par la boucle de suivi (une fermeture ne voit pas l'état neuf)
  const setFacSignin = v => { facSigninRef.current = v; setFacSignin0(v); };
  const cur = SCREENS[i][0];
  // ce qui dépend du système (Linux / Windows) vient du serveur : installer/platform_*.py, ui()
  const P = (st && st.platform) || { os: 'linux', privilege: 'sudo', ui: {} };
  const U = P.ui || {};
  const uac = P.privilege === 'uac';

  const refresh = () => api('/api/state').then(setSt).catch(() => null);
  // une fenêtre ROUVERTE pendant ou après l'installation revient sur l'écran Install (VM 2026-10-23 : fermée par
  // erreur, elle repartait sur « Before you start » et il fallait recliquer tous les Next pour retrouver le décompte)
  useEffect(() => { api('/api/state').then(s => {
    setSt(s);
    if (s && s.mode !== 'uninstall' && (s.running || s.done || (s.steps || []).some(x => x.state !== 'pending')))
      setI(SCREENS.findIndex(([id]) => id === 'install'));
  }).catch(() => null); }, []);
  useEffect(() => {
    if (cur === 'checks') api('/api/checks').then(d => setChecks(d.checks));
    if (cur === 'engine') api('/api/engines').then(setEngines);
    if (cur === 'reaper') api('/api/reaper').then(setReaper);
    if (cur === 'size' && st) api('/api/size?dir=' + encodeURIComponent(dir ?? st.dir)).then(setSize);
    // Linux : l'écran Connect est un composant à part (ConnectLive), qui lit golem par le relais du serveur
    if (cur === 'connect' && U.connect === 'form') { api('/api/connect').then(setConn); facRefresh().then(d => { if (d && d.up && d.download && d.download.phase === 'running') facWatch(); }); }
  }, [cur]);
  // journal + état en direct pendant une étape (installation ou Reaper)
  useEffect(() => {
    if (!(cur === 'install' || cur === 'reaper')) return;
    const t = setInterval(async () => {
      const d = await api('/api/log?since=' + logN.current).catch(() => null);
      if (d && d.lines.length) { logN.current = d.n; setLog(l => [...l, ...d.lines].slice(-1500)); }
      const s = await api('/api/state').catch(() => null); if (s) setSt(s);
      if (cur === 'reaper') api('/api/reaper').then(setReaper);
    }, 1000);
    return () => clearInterval(t);
  }, [cur]);
  useEffect(() => { if (logEl.current) logEl.current.scrollTop = logEl.current.scrollHeight; }, [log]);
  // le Vital officiel s'installe à la main (compte vital.audio) : l'écran Done le re-vérifie pendant ce temps
  useEffect(() => {
    if (cur !== 'done' || !U.vital) return;
    const look = () => api('/api/vital').then(setVital).catch(() => null);
    look(); const t = setInterval(look, 3000);
    return () => clearInterval(t);
  }, [cur, U.vital]);

  if (!st) return html`<div class="shell"><div class="top"><span class="lg">/golem_</span><span class="sub">installer</span></div>
    <div class="content"><p class="muted">connecting to the installer…</p></div></div>`;

  const blocking = (checks || []).some(c => !c.ok && c.blocking);
  // déclaré AVANT canNext qui l'appelle (TDZ : l'écran Taille restait vide)
  const total = (sz, packs) => Object.values(sz.fixed).reduce((a, b) => a + b, 0) + (packs || []).reduce((a, p) => a + (sz.packs[p] || 0), 0);
  const canNext = {
    before: true,
    play: !!st.instrument,
    checks: checks && !blocking,
    engine: !!st.engine,
    reaper: reaper && (reaper.found || reaper.job === 'ok'),
    where: !!(dir ?? st.dir),
    size: size && size.free_mb != null && total(size, st.packs) <= size.free_mb,
    install: st.done,
    connect: true, done: false,
  }[cur];
  const go = async n => {
    if (n > i) {
      if (cur === 'play') { await api('/api/config', { instrument: st.instrument }); await refresh(); }
      if (cur === 'engine') { await api('/api/config', { engine: st.engine }); await refresh(); }
      if (cur === 'where') { await api('/api/config', { dir: dir ?? st.dir }); await refresh(); }
      if (cur === 'size') { await api('/api/config', { packs: st.packs }); await refresh(); }
      // une clé tapée puis « Finish » sans « Save » : on l'enregistre, on ne la perd pas en silence
      if (cur === 'connect' && U.connect === 'form' && !(await saveKeys())) return;
    }
    setI(Math.max(0, Math.min(SCREENS.length - 1, n)));
  };
  const togglePack = p => setSt({ ...st, packs: st.packs.includes(p) ? st.packs.filter(x => x !== p) : [...st.packs, p] });
  const checkPw = async () => { setBusy(true); setPwErr(null); const d = await api('/api/sudo', { password: pw }); setBusy(false);
    if (d.ok) { setPw(''); await refresh(); } else setPwErr(d.error || 'wrong password'); };
  // UN clic suffit (VM 2026-10-23 : le bouton restait actif jusqu'au poll suivant, on cliquait cinq fois) : grisé tout
  // de suite, jusqu'à ce que le serveur dise que ça tourne
  const [starting, setStarting] = useState(false);
  const [details, setDetails] = useState(false);
  const startInstall = async () => {
    setStarting(true);
    await api('/api/install', {}).catch(() => null); await refresh(); setStarting(false); };
  const retryItem = async id => { await api('/api/retry-item', { id }).catch(() => null); refresh(); };
  const stopStep = async () => { await api('/api/stop-step', {}).catch(() => null); refresh(); };
  const sendReport = async () => { await api('/api/report', {}).catch(() => null); refresh(); };
  // OÙ EST REAPER (2026-10-17) : un REAPER installé ailleurs que C: était invisible, et golem en posait un second.
  // L'écran propose donc « je l'ai déjà ailleurs » (on retient le dossier) et un dossier d'installation au choix.
  const [rDir, setRDir] = useState(null);              // dossier d'installation (null = celui proposé par le serveur)
  const [rHave, setRHave] = useState('');              // « J'ai déjà REAPER ici »
  const [rErr, setRErr] = useState('');
  const installReaper = async () => {
    await api('/api/reaper/install', { dir: rDir == null ? '' : rDir }); api('/api/reaper').then(setReaper); };
  const locateReaper = async () => {
    setRErr(''); const d = await api('/api/reaper/locate', { path: rHave }).catch(e => ({ ok: false, error: String(e) }));
    if (!d.ok) setRErr(d.error || 'no reaper.exe there'); api('/api/reaper').then(setReaper); };
  const open = url => api('/api/open', { url });
  const saveKeys = async () => {
    if (!keys.golem_token && !keys.t3k_key) return true;
    setConnWhere(['golem_token', 't3k_key'].filter(k => keys[k]));
    setConnMsg('saving…');
    const d = await api('/api/connect', keys).catch(e => ({ error: String(e) }));
    if (d.error) { setConnMsg('✗ ' + d.error); return false; }
    setConn(d); setKeys({ golem_token: '', t3k_key: '' }); setConnMsg('✓ saved'); return true;
  };
  // « Continue on a tablet » : golem Server démarre (s'il ne tourne pas), puis l'adresse, son QR et le code d'appairage
  // s'affichent ICI — par le serveur de l'installateur (/api/tablet), jamais :8770 depuis la page
  const [tab, setTab] = useState(null);
  const tabPoll = useRef(null);
  useEffect(() => () => clearInterval(tabPoll.current), []);
  const tabletStart = async () => {
    const r = await api('/api/tablet', {}).catch(e => ({ phase: 'error', error: String(e) }));
    setTab(r);
    clearInterval(tabPoll.current);
    if (r.phase === 'starting') tabPoll.current = setInterval(async () => {
      const d = await api('/api/tablet').catch(() => null); if (!d) return;
      setTab(d); if (d.phase !== 'starting') clearInterval(tabPoll.current);
    }, 1500);
  };
  const [starting2, setStarting2] = useState(false);   // « Open golem » : golem démarre, l'installateur attend
  const finish = async () => {
    setFinishErr(''); setStarting2(true);
    const d = await api('/api/finish', {}).catch(() => ({ ok: true }));   // le serveur s'en va quand golem répond
    if (d && d.ok === false) { setStarting2(false); setFinishErr(d.error || 'could not start golem'); }
  };
  // « Restart now » (Linux, 2026-11-03) : les droits temps réel ne valent qu'après un redémarrage ; le serveur arrête
  // d'abord le golem qu'il a lancé (platform_linux.restart), puis `systemctl reboot`
  const [restarting, setRestarting] = useState(false);
  const restartNow = async () => {
    setFinishErr(''); setRestarting(true);
    const d = await api('/api/restart', {}).catch(() => ({ ok: true }));
    if (d && d.ok === false) { setRestarting(false); setFinishErr(d.error || 'the computer did not restart'); }
  };
  // le téléchargement des captures d'usine : golem (en serveur, sans fenêtre) fait le travail ; on suit son état
  const facPoll = useRef(null);
  const facRefresh = async () => { const d = await api('/api/factory').catch(() => null); if (d) setFac(d); return d; };
  const facWatch = () => {
    clearInterval(facPoll.current);
    facPoll.current = setInterval(async () => {
      const d = await facRefresh(); if (!d || !d.up) return;
      const dl = d.download || {};
      // connecté pendant qu'on attendait le navigateur : le téléchargement part tout seul, une fois
      if (d.authed && d.missing && dl.phase !== 'running' && facSigninRef.current) { setFacSignin(null); await api('/api/factory/download', {}); return; }
      if (d.authed && (!d.missing || dl.phase === 'done') && !facSigninRef.current) clearInterval(facPoll.current);
    }, 2000);
  };
  useEffect(() => () => clearInterval(facPoll.current), []);
  const facStart = async () => {
    setFacMsg('starting golem — it runs without a window…');
    const r = await api('/api/factory/start', {}).catch(e => ({ ok: false, error: String(e) }));
    if (!r.ok) { setFacMsg('✗ ' + (r.error || 'could not start')); return; }
    if (r.dry) { setFacMsg('(dry run) golem would sign in to TONE3000 and download the factory captures'); return; }
    if (r.step === 'signin') { setFacSignin(r); setFacMsg('sign in to TONE3000 in your browser — the download starts by itself'); }
    else setFacMsg(r.step === 'done' ? '✓ all factory captures are already here' : 'downloading…');
    facWatch();
  };
  const keyField = (id, label, hint, help) => {
    const m = (conn && conn[id]) || { set: false, hint: '' };
    return html`<div class="field"><label>${label}</label>
      <input type="password" autocomplete="off" spellcheck="false" value=${keys[id]}
        placeholder=${m.set ? 'set (' + m.hint + ') — leave blank to keep it' : hint}
        onInput=${e => { setKeys({ ...keys, [id]: e.target.value }); setConnMsg(''); }}
        onKeyDown=${e => e.key === 'Enter' && saveKeys()} /></div>
      <p class="muted small">${help}</p>
      <div class="row"><button class="btn" disabled=${!keys[id]} onClick=${saveKeys}>Save</button>
        ${connWhere.includes(id) ? html`<span class=${cls('muted', connMsg.startsWith('✗') && 'bad', connMsg.startsWith('✓') && 'ok')}>${connMsg}</span>` : ''}</div>`;
  };
  const keyChip = id => (conn && conn[id] && conn[id].set) ? html`<span class="chip okchip">✓ set ${conn[id].hint}</span>` : html`<span class="chip">not set</span>`;

  const missing = ((st.install && st.install.phases) || []).flatMap(p => p.warns || []);
  const Screen = {
    before: () => html`<${Before} est=${st.install && st.install.total_est} uac=${uac} U=${U} />`,
    play: () => html`
      <h1>What do you play? <small>golem sets itself up for it — you can change everything later in golem</small></h1>
      ${PLAY.map(([id, name, what]) => html`<button class=${cls('pick', st.instrument === id && 'on')}
          onClick=${() => setSt({ ...st, instrument: id })}>
        <div class="row"><span class="radio"></span><b>${name}</b></div>
        <span class="muted">${what}</span>
      </button>`)}`,
    checks: () => html`
      <h1>Before anything <small>what this machine is</small></h1>
      <p class="muted">${U.checks_intro}</p>
      ${!checks ? html`<p class="muted">checking…</p>` : checks.map(c => html`<div class=${cls('chk', c.ok ? 'ok' : 'no', !c.ok && !c.blocking && 'soft')}>
        <i>${c.ok ? '✓' : c.blocking ? '⛔' : '⚠'}</i><b>${c.label}</b><span>${c.detail}</span></div>`)}`,
    engine: () => html`
      <h1>Audio engine <small>the engine golem drives — you can change it later in Settings ▸ System ▸ Audio Engine</small></h1>
      ${!engines ? html`<p class="muted">reading engines…</p>` : engines.engines.map(e => {
        const caps = e.capabilities || {};
        const missing = engines.features.filter(f => caps[f.id] === 'no').map(f => f.label);
        return html`<button class=${cls('pick', st.engine === e.id && 'on', !e.available && 'off')} disabled=${!e.available}
            onClick=${() => setSt({ ...st, engine: e.id })}>
          <div class="row"><span class="radio"></span><b>${e.name}</b>
            ${e.license !== 'commercial' && e.by ? html`<span class="muted">${e.by}</span>` : ''}
            ${!e.available ? html`<span class="chip">${e.reason}</span>` : ''}
            <span class="grow"></span><span class="chip">${e.license === 'commercial' ? 'commercial' : freeLicense(e.license)}</span></div>
          <span class="muted">${e.summary || ''}${missing.length ? ' Not available on it yet: ' + missing.join(', ') + '.' : ''}</span>
        </button>`;
      })}
      <p class="muted">One engine is installed. More engines will be offered here as they become available.</p>`,
    reaper: () => html`
      <h1>Reaper <small>the audio engine golem drives</small></h1>
      ${!reaper ? html`<p class="muted">looking for Reaper…</p>`
      : reaper.found ? html`<div class="card"><div class="row"><b class="ok">✓ Reaper ${reaper.version || ''} found</b><span class="muted">${reaper.path}</span></div>
          <p class="muted">golem <b>runs on Reaper</b>: it drives it as its audio engine. Never uninstall it — golem would fall silent. ${reaper.pinned && reaper.version && reaper.version !== reaper.pinned ? html`<span class="warn">golem is tested with ${reaper.pinned}; you have ${reaper.version} — it usually works${U.reaper_update_note ? ' — ' + U.reaper_update_note : '.'}</span>` : ''}</p>
          <p class="muted">Reaper is commercial: it runs fully in evaluation mode, a personal license is $60. <button class="btn mini ghost" onClick=${() => open(reaper.buy_url)}>reaper.fm/purchase ↗</button></p></div>`
      : html`<div class="card"><b class="warn">Reaper is not installed</b>
          <p class="muted">golem is tested with Reaper <b>${reaper.pinned || '7.x'}</b> for ${U.reaper_platform}. ${reaper.can_locate ? 'Three' : 'Two'} ways:</p>
          ${reaper.can_locate ? html`<div class="field"><label>I already have it</label>
            <input type="text" placeholder="the folder that holds reaper.exe — e.g. D:\\REAPER" value=${rHave}
              onInput=${e => setRHave(e.target.value)} />
            <button class="btn" disabled=${!rHave.trim()} onClick=${locateReaper}>Use this Reaper</button></div>
            ${rErr ? html`<p class="warn">${rErr}</p>` : ''}` : ''}
          ${reaper.can_locate ? html`<div class="field"><label>Install it in</label>
            <input type="text" value=${rDir == null ? (reaper.default_dir || '') : rDir} onInput=${e => setRDir(e.target.value)} /></div>` : ''}
          <div class="row"><button class="btn primary" disabled=${reaper.job === 'running'} onClick=${installReaper}>${reaper.job === 'running' ? '⏳ installing…' : reaper.job === 'fail' ? '↻ Retry: install Reaper for me' : '⬇ Install Reaper ' + (reaper.pinned || '') + ' for me'}</button>
            <span class="muted">${U.reaper_install_note}</span></div>
          <div class="row"><button class="btn" onClick=${() => open(reaper.download_url)}>Download it from reaper.fm ↗</button><span class="muted">then install it yourself and come back — this screen re-checks every second</span></div>
          <p class="muted">Reaper is commercial: full evaluation, a personal license is $60 — if you have one, add it below.</p></div>`}
      ${/* hors du ternaire : REAPER qui vient de s'installer ne remonte pas la carte (le texte collé reste) */''}
      ${reaper ? html`<${LicenseCard} present=${!!reaper.license_present} dry=${st.dry} />` : ''}
      ${reaper && !reaper.found && log.length ? html`<div class="log" ref=${logEl}>${log.map(l => html`<span class=${cls('ln', l.line.startsWith('$') && 'cmd', l.line.startsWith('✗') && 'err', l.line.startsWith('▶') && 'hd')}>${l.line}</span>`)}</div>` : ''}`,
    where: () => html`
      <h1>Where golem lives</h1>
      <div class="field"><label>Install folder</label><input type="text" value=${dir ?? st.dir} onInput=${e => setDir(e.target.value)} spellcheck="false" /></div>
      <p class="muted">golem lives in one folder: code, presets, your sounds. Keep it on a local disk, not a network share.</p>
      <div class="card"><b>Two ways to use it — both are installed</b>
        <div class="uses"><div><b>golem</b><span>opens in a window on this computer.</span></div>
          <div><b>golem Server</b><span>no window: a tablet or a phone on your Wi-Fi is the screen. Switch anytime, the sound does not stop.</span></div></div>
        <p class="muted small">A computer that is only golem? Once it runs, <b>System ▸ Dashboard</b> can start it with this computer.</p></div>`,
    size: () => html`
      <h1>What it takes on disk</h1>
      ${!size ? html`<p class="muted">measuring…</p>` : html`<div class="card"><div class="size">
        <div class="h">Required</div><div></div>
        ${(size.fixed_labels || []).map(([k, l]) => html`<span>${l}</span><span class="mb">${mb(size.fixed[k] || 0)}</span>`)}
        ${(size.required_packs || []).map(k => html`<span>${size.pack_labels[k] || k}</span><span class="mb">${mb(size.packs[k] || 0)}</span>`)}
        <div class="h">Optional sounds — you can fetch them later</div><div></div>
        ${Object.entries(size.packs).filter(([k]) => !(size.required_packs || []).includes(k)).map(([k, v]) => {
          const off = (size.packs_unavailable || {})[k];        // un pack que ce système ne joue pas : montré, pas proposé
          return html`<label class=${cls(off && 'off')} title=${off || ''}><input type="checkbox" disabled=${!!off} checked=${!off && st.packs.includes(k)} onChange=${() => togglePack(k)} /> ${size.pack_labels[k] || k}${off ? html` <small class="muted">— ${off}</small>` : ''}</label><span class="mb">${off ? '—' : mb(v)}</span>`;
        })}
        <span class="muted" style="grid-column:1/-1; font-size:11.5px">No amp capture ships with golem: a new rack knows every amp, pedal and cab by name, and gets its captures from golem.fm or Tone3000 once paired.</span>
        <span class="tot">Total</span><span class="mb tot">${mb(total(size, st.packs))}</span>
        <span class="muted">Free in ${dir ?? st.dir}</span><span class="mb">${size.free_mb == null ? '?' : mb(size.free_mb)}</span>
      </div>
      <div class=${cls('bar', size.free_mb && total(size, st.packs) > size.free_mb && 'over')}><i style=${'width:' + Math.min(100, size.free_mb ? total(size, st.packs) / size.free_mb * 100 : 100) + '%'}></i></div>
      ${size.free_mb && total(size, st.packs) > size.free_mb ? html`<p class="bad">Not enough space — untick a pack or pick another folder.</p>` : ''}</div>`}`,
    install: () => html`
      ${/* 2026-09-09 : « on efface le mot de passe, mais le boost CPU tourne en sudo » — l'écran
            devait dire ce que l'install ACCORDE pour plus tard, sinon les deux phrases se contredisent.
            Ce sont deux règles NOPASSWD étroites (provision/setup-perf-sudo.sh, setup-net-sudo.sh) sur
            des copies root-owned, limitées à des verbes ; le bridge appelle `sudo -n`, jamais de prompt. */''}
      ${/* l'autorisation du système (UAC sous Windows, la fenêtre d'administrateur de macOS) : ses phrases
            viennent du module de plateforme (U.permission), l'écran n'en invente aucune */''}
      ${!uac && !st.sudo_ok ? html`<h1>Install <small>${st.dir}</small></h1><div class="card"><p>Installing packages and the real-time audio setup needs administrator rights. Your password is used for this install only — it is <b>never written anywhere</b> and forgotten when this window closes.</p>
        <p class="muted">Afterwards golem never asks again, and never runs as root: the install writes two narrow rules that let it run <b>two root-owned scripts and nothing else</b> without a password — the CPU governor (the ⚡ boost on the dashboard) and Wi-Fi switching (the rescue access point on stage). Each is limited to a handful of verbs; you can read them in <code>/etc/sudoers.d/golem-perf</code> and <code>golem-net</code>.</p>
        <div class="field"><label>Your password</label><input type="password" value=${pw} onInput=${e => setPw(e.target.value)} onKeyDown=${e => e.key === 'Enter' && checkPw()} autofocus />
          <button class="btn primary" disabled=${!pw || busy} onClick=${checkPw}>${busy ? '⏳' : 'Check'}</button></div>
        ${pwErr ? html`<p class="bad">✗ ${pwErr}</p>` : ''}</div>`
      : html`<${InstallRun} st=${st} uac=${uac} U=${U} starting=${starting} onStart=${startInstall}
          onRetryItem=${retryItem} onStop=${stopStep} onReport=${sendReport} details=${details} setDetails=${setDetails} log=${log} logEl=${logEl} />`}`,
    // Windows / macOS : golem ne tourne pas encore — deux champs écrits sans lui (provision.desktop connect), dans
    // les mêmes deux cartes que Linux ; les captures d'usine démarrent golem en serveur (factory_start)
    connect: () => U.connect === 'form' ? html`
      <h1>Connect <small>golem.fm and TONE3000 — both optional</small></h1>
      <div class="link-grid">
        <section class="card link">
          <div class="link-hd"><b class="link-name">golem.fm</b>${keyChip('golem_token')}</div>
          <p class="muted">${FM_PITCH}</p>
          ${keyField('golem_token', 'Device token', 'paste your golem.fm device token',
            'golem.fm ▸ golem ▸ Access ▸ Manual token (shown once: copy it). No token yet? golem pairs with a code from Settings ▸ API, once it is open.')}
        </section>
        <section class="card link">
          <div class="link-hd"><b class="link-name">TONE3000</b>${keyChip('t3k_key')}</div>
          <p class="muted">${T3K_PITCH}</p>
          ${keyField('t3k_key', 'Publishable key', 'paste your TONE3000 publishable key',
            'tone3000.com ▸ Settings ▸ API Keys — it names golem to TONE3000, it is not a secret.')}
          ${conn && conn.t3k_key && conn.t3k_key.set ? html`<div class="link-sub">
            <b>Factory sounds</b>
            <p class="muted small">The factory patches and presets use amps, pedals and cabs from TONE3000 (about 11 MB). golem does not ship them:
              they come from <b>your</b> TONE3000 account — sign in once, golem downloads them.</p>
            ${fac && fac.up && fac.download && fac.download.phase === 'running'
              ? html`<p>⬇ downloading ${fac.download.done} of ${fac.download.total}${fac.download.current ? ' — ' + fac.download.current : ''}…</p>`
              : fac && fac.up && fac.authed && !fac.missing ? html`<p class="ok">✓ all ${fac.total} factory captures are on this golem</p>`
              : html`<div class="row"><button class="btn primary" onClick=${facStart}>${fac && fac.up && fac.authed && fac.download && fac.download.phase === 'done'
                  ? `↻ Try the ${fac.missing} missing capture${fac.missing === 1 ? '' : 's'} again` : 'Sign in to TONE3000 & download them'}</button></div>`}
            ${facSignin && facSignin.redirect_uri ? html`<p class="muted small">First time? TONE3000 must know golem's address: add${' '}<code>${facSignin.redirect_uri}</code>${' '}to your key's redirect URIs (tone3000.com ▸ Settings ▸ API Keys), then sign in again.</p>` : ''}
            ${fac && fac.download && (fac.download.failed || []).length ? html`${fac.download.failed.map(f => html`<p class="bad small">✗ ${f.title || 'tone ' + f.tone} — ${f.why}</p>`)}` : ''}
            ${facMsg ? html`<p class=${cls('muted', facMsg.startsWith('✗') && 'bad', facMsg.startsWith('✓') && 'ok')}>${facMsg}</p>` : ''}
          </div>` : ''}
        </section>
      </div>`
      : html`<h1>Connect <small>golem.fm and TONE3000 — both optional</small></h1><${ConnectLive} open=${open} />`,
    done: () => html`
      <h1>golem is installed 🎸</h1>
      ${/* DEUX SORTIES (docs/installer.md §4) : la fenêtre sur cet ordinateur, ou golem Server et une tablette */''}
      ${P.restart ? html`<div class="card warncard"><b class="warn">Restart your computer to finish</b>
        <p class="muted">golem needs real-time audio rights that only apply after a restart. Without it, the sound can crackle.</p></div>` : ''}
      <div class="row done-acts">
        ${P.restart ? html`<button class="btn primary" disabled=${restarting || starting2} onClick=${restartNow}>${restarting ? '⏳ Restarting…' : 'Restart now'}</button>
          <button class="btn" disabled=${restarting || starting2} onClick=${finish}>${starting2 ? '⏳ Starting golem…' : 'Open golem anyway'}</button>`
        : U.finish ? html`<button class="btn primary" disabled=${starting2} onClick=${finish}>${starting2 ? '⏳ Starting golem…' : 'Open golem →'}</button>`
          : html`<button class="btn primary" onClick=${() => open('http://localhost:8770/app/')}>Open golem ↗</button>`}
        <button class="btn" disabled=${tab && tab.phase === 'starting'} onClick=${tabletStart}>📱 Continue on a tablet</button>
        <span class="muted small">${P.restart ? 'After the restart, open golem from its icon in your applications menu.'
          : U.finish ? 'The first start takes about a minute: the installer closes when golem opens in its window.' : 'golem in its window, or golem Server: a tablet is the screen.'}</span>
        <span class="grow"></span>
        ${!U.finish || tab ? html`<button class="btn ghost" onClick=${() => api('/api/quit', {})}>Close the installer</button>` : ''}</div>
      ${finishErr ? html`<p class="bad">✗ ${finishErr}</p>` : ''}
      ${starting2 ? html`<p class="muted">golem is starting — the first start takes up to a minute. This window closes by itself when golem opens.</p>` : ''}
      ${tab ? html`<${TabletCard} tab=${tab} />` : ''}
      ${/* ce que l'installation a laissé en ⚠ : redit ici (2026-10-23 — l'écran Done ne le rappelait pas) */''}
      ${missing.length ? html`<div class="card warncard"><b class="warn">${missing.length === 1 ? '1 thing' : missing.length + ' things'} will not play yet</b>
        <ul class="next muted">${missing.map(w => { const [h, ...r] = w.text.split(' — ');
          return html`<li><b class="warn">${h}</b>${r.length ? ' — ' + r.join(' — ') : ''}</li>`; })}</ul></div>` : ''}
      <div class="done"><div class="card"><div class="kv">
          <span>Folder</span><b>${st.dir}</b>
          <span>Launchers</span><b>${U.launcher_done || ''}</b>
          <span>Starts</span><b>when you open golem or golem Server — System ▸ Dashboard can start it with this computer</b>
          <span>App</span><b>http://localhost:8770/app/</b></div>
          ${U.first_run ? html`<p class="muted">${U.first_run}</p>` : ''}</div>
        <div class="card"><b>Three things to do next</b><ol class="next muted">
          ${(U.next || []).map(([tone, b, rest]) => html`<li><b class=${tone}>${b}</b>${rest}</li>`)}</ol>
          <p class="muted">Reaper license: if you skipped it on the Reaper screen, add your <code>.rk</code> in Settings ▸ Licenses — REAPER then starts without the reminder.<br/>
            ${U.done_note}</p></div>
        ${U.vital && vital ? html`<div class="card vital"><div class="row"><b>Vital, the synth of the Keys block</b>
            ${vital.official ? html`<b class="ok">✓ official Vital found</b>` : vital.vitalium ? html`<b class="ok">✓ plays now with Vitalium</b>` : html`<b class="warn">not installed yet</b>`}</div>
          ${vital.official ? html`<p class="muted">golem uses the official Vital first. Restart golem once if it was running while you installed it, so Reaper sees the new plugin.</p>`
          : html`<p class="muted">${vital.vitalium ? 'Vitalium, the free build of Vital, was installed with golem: the Vital block plays now, with your presets from golem.fm. ' : ''}For the <b>official Vital</b> (same engine, plus its own preset store), create a free account on vital.audio, download the ${U.vital_installer || 'Windows installer'} and run it — golem tries it first, from its next start.</p>
            <div class="row"><button class="btn" onClick=${() => open(vital.download_url)}>Download Vital from vital.audio ↗</button><span class="muted">this card re-checks every few seconds</span></div>`}</div>` : ''}
        ${/* ce que GoleM ne peut pas poser lui-même sur CE système (macOS, 2026-10-04) : dit ici, avec le lien */''}
        ${(U.manual || []).length ? html`<div class="card manual"><b>To install yourself</b> <span class="muted">— optional: each one makes more blocks play; golem sees it at its next start</span><ul class="next muted">
          ${U.manual.map(([name, why, url]) => html`<li><b>${name}</b> — ${why}${url ? html` <button class="btn mini ghost" onClick=${() => open(url)}>${url.replace(/^https?:\/\//, '').split('/')[0]} ↗</button>` : ''}</li>`)}</ul></div>` : ''}</div>`,
  }[cur]();

  return html`<div class="shell">
    <div class="top"><span class="lg">/golem_</span><span class="sub">installer</span>${st.dry ? html`<span class="dry">DRY RUN — nothing is installed</span>` : ''}</div>
    <div class="main">
      <div class="rail">${SCREENS.map(([id, label], k) => html`<div class=${cls('st', k === i && 'cur', k < i && 'ok')}><i>${k < i ? '✓' : k + 1}</i><b>${label}</b></div>`)}
        <div class="foot">golem is free software (GPL-3). Reaper is not — it is yours to license.</div></div>
      <div class="body">
        <div class="content">${Screen}</div>
        <div class="foot">
          <button class="btn ghost" disabled=${i === 0 || st.running} onClick=${() => go(i - 1)}>← Back</button>
          <span class="grow"></span>
          ${cur === 'connect' ? html`<span class="note">both are optional — you can do it later in golem, Settings ▸ API</span>` : ''}
          ${cur === 'install' && st.running ? html`<span class="note">Installing… nothing to click until it is done</span>` : ''}
          ${cur !== 'done' ? html`<button class="btn primary" disabled=${!canNext} onClick=${() => go(i + 1)}>${cur === 'connect' ? 'Finish →' : cur === 'before' ? 'I am ready →' : 'Next →'}</button>` : ''}
        </div>
      </div>
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
