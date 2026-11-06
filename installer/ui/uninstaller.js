// SPDX-License-Identifier: GPL-3.0-or-later
// golem — le DÉSINSTALLATEUR (docs/uninstall.md §4) : six écrans, Preact/htm sans build, même allure que l'installateur.
// Le serveur est installer/server.py en mode --uninstall (installer/uninstaller.py) ; chaque appel porte le jeton.
// L'écran n'invente rien : le plan vient de `provision/uninstall.py plan --json`, l'avancement de `run --json`.
import { html, render, useState, useEffect, useRef } from '/vendor/htm-preact-standalone.module.js';

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const api = (path, body) => fetch(path, body === undefined
  ? { headers: { 'X-Golem-Token': TOKEN } }
  : { method: 'POST', headers: { 'X-Golem-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  .then(r => r.json());
const cls = (...a) => a.filter(Boolean).join(' ');
const human = n => n == null ? '?' : n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n >= 1e6 ? Math.round(n / 1e6) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB';

const SCREENS = [['backup', 'Back up'], ['golem', 'golem'], ['third', 'Third-party software'], ['review', 'Review'],
  ['uninstall', 'Uninstall'], ['done', 'Done']];
const GROUP_LABEL = {
  golem: 'golem itself', 'reaper-links': 'Links inside REAPER', 'reaper-ini': 'REAPER settings golem changed',
  system: 'System settings', dedicated: 'Dedicated machine settings',
  plugins: 'Plugins', reaper: 'REAPER', programs: 'Programs', apt: 'System packages', toolchain: 'Build tools',
};
const GROUP_NOTE = {
  plugins: 'Plugins golem downloaded or built. Another audio program may use them.',
  reaper: 'golem drives REAPER; you may use it on your own. Removing its settings folder needs the backup: it keeps your license.',
  apt: 'Packages golem asked for. Audio plugin packages are ticked; general tools are not, because other software may need them.',
  programs: 'Programs golem installed with their own installers. Each one is removed by its own uninstaller, silently. Another audio program may use them.',
  toolchain: 'Installed for golem; other programs or scripts may use it.',
};
// les étapes du moteur, dans l'ordre du §5 (provision/uninstall.py run)
const STEPS = [['stop', 'Stop golem'], ['root', 'System settings'], ['apt', 'System packages'], ['reaper', 'REAPER links and settings'],
  ['user', 'Plugins, launchers and caches'], ['folder', 'The golem folder'], ['receipt', 'The install receipt']];
// Windows (docs/uninstall.md §9.3) : une passe élevée — réglages système, puis les programmes par leur désinstalleur
const WIN_STEPS = [['stop', 'Stop golem'], ['root', 'System settings'], ['programs', 'Programs'], ['reaper', 'REAPER files and settings'],
  ['user', 'Plugins, shortcuts and caches'], ['folder', 'The golem folder'], ['receipt', 'The install receipt']];
// le chip du privilège d'un groupe : le mot de passe (Linux) ou l'invite de Windows (UAC)
const ELEVATED = it => it.privilege === 'root' || it.privilege === 'admin';

const Origin = ({ it }) => it.origin === 'unknown' ? html`<span class="chip warnchip" title="nothing records that golem placed it">origin unknown</span>` : '';
const Paths = ({ it }) => it.paths && it.paths.length ? html`<code class="pth" title=${it.paths.join('\n')}>${it.paths[0]}${it.paths.length > 1 ? ` +${it.paths.length - 1}` : ''}</code>` : '';

// LE RAPPORT D'ÉCHEC (docs/diagnostics.md §7.1) : ENVOYÉ TOUT SEUL quand la désinstallation échoue (décision du 2026-10-27) ;
// l'écran dit qu'il est parti et ce qu'il contient
function UReport({ r }) {
  const [what, setWhat] = useState(false);
  if (!r || !r.state) return null;
  return html`<div class="card ureport"><p class="muted">${r.state === 'sending' ? '⏳ Sending a report of this failure to golem…'
      : r.state === 'sent' ? html`A report of this failure was sent to golem, so we can fix it. Its code: <b>${r.code}</b>.`
      : r.state === 'dry' ? html`(dry run) a report of this failure was built, not sent: <code>${r.path}</code>`
      : html`A report of this failure could not be sent (${r.error})${r.path ? html` — it is saved in <code>${r.path}</code>` : ''}.`}
</p>
    <div class="row"><button class="linkbtn" onClick=${() => setWhat(!what)}>${what ? 'Hide' : 'What is in it'}</button></div>
    ${what ? html`<p class="muted small">This computer (system, processor, memory), the golem version, which steps and items failed and
      the last error line, and the last part of the uninstall output. Your user name, computer name, folders, network
      addresses and password are erased first.</p>` : ''}</div>`;
}

function App() {
  const [st, setSt] = useState(null);
  const [gone, setGone] = useState(false);            // le serveur s'est arrêté (Close / Cancel)
  const [i, setI] = useState(0);
  const [plan, setPlan] = useState(null);
  const [third, setThird] = useState({});
  const [dest, setDest] = useState(null);
  const [destErr, setDestErr] = useState('');
  const [est, setEst] = useState(null);
  const [rev, setRev] = useState(null);
  const [pw, setPw] = useState('');
  const [pwErr, setPwErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [log, setLog] = useState([]);
  const logN = useRef(0); const logEl = useRef(null);
  const cur = SCREENS[i][0];
  const u = (st && st.uninstall) || null;

  const refresh = () => api('/api/state').then(d => { setSt(d); return d; }).catch(() => null);
  useEffect(() => {
    refresh();
    api('/api/uplan').then(p => { setPlan(p); if (p && p.third) setThird(p.third); }).catch(e => setPlan({ error: String(e) }));
    // le battement : il tient le serveur en vie (son chien de garde part après 15 min sans écran ouvert)
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, []);
  const running = u && (u.backup.state === 'running' || u.run.state === 'running');
  // état + journal en direct pendant la sauvegarde et la désinstallation
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const d = await api('/api/log?since=' + logN.current).catch(() => null);
      if (d && d.lines.length) { logN.current = d.n; setLog(l => [...l, ...d.lines].slice(-1500)); }
      refresh();
    }, 700);
    return () => clearInterval(t);
  }, [running]);
  useEffect(() => { if (logEl.current) logEl.current.scrollTop = logEl.current.scrollHeight; }, [log, cur]);
  const B = u && u.backup;
  const loadEst = () => api('/api/backup/estimate').then(setEst).catch(() => null);
  useEffect(() => { if (cur === 'backup' && u && u.venv) loadEst(); }, [cur, B && B.dest, B && B.secrets, !!u]);
  useEffect(() => { if (cur === 'review') { setRev(null); api('/api/review').then(setRev); } }, [cur, st && st.sudo_ok]);

  if (gone) return html`<div class="shell"><div class="top"><span class="lg">/golem_</span><span class="sub">uninstaller</span></div>
    <div class="content"><h1>The uninstaller has closed</h1><p class="muted">You can close this tab.</p></div></div>`;
  if (!st || !u) return html`<div class="shell"><div class="top"><span class="lg">/golem_</span><span class="sub">uninstaller</span></div>
    <div class="content"><p class="muted">connecting to the uninstaller…</p></div></div>`;

  const items = (plan && plan.items) || [];
  const R = u.run;
  const uac = u.privilege === 'uac';
  const steps = uac ? WIN_STEPS : STEPS;
  const started = R.attempt > 0;
  const backupCfg = async body => {
    const d = await api('/api/backup/config', body);
    setDestErr(d.error || ''); await refresh(); return d;
  };
  const backupNow = async () => {
    setErr('');
    if (dest != null && dest !== B.dest) { const d = await backupCfg({ dest }); if (d.error) return; }
    const r = await api('/api/backup/start', {});
    if (!r.ok) setErr(r.error || 'could not start the backup');
    logN.current = logN.current || 0; refresh();
  };
  const checkPw = async () => {
    setBusy(true); setPwErr(null);
    const d = await api('/api/sudo', { password: pw }); setBusy(false);
    if (d.ok) { setPw(''); await refresh(); } else setPwErr(d.error || 'wrong password');
  };
  const startRun = async retry => {
    setErr('');
    const r = await api(retry ? '/api/uninstall/retry' : '/api/uninstall', retry ? {} : { third });
    if (!r.ok) { setErr(r.error || 'could not start'); return false; }
    await refresh(); return true;
  };
  const quit = async () => {
    const r = await api('/api/quit', {}).catch(() => ({ ok: true }));
    if (r && r.ok === false) { setErr(r.error); return; }
    setGone(true);
  };
  const toggle = id => setThird({ ...third, [id]: !(id in third ? third[id] : (items.find(x => x.id === id) || {}).default) });
  const picked = it => it.id in third ? third[it.id] : it.default;
  // tout cocher / tout décocher un groupe (600 paquets ne se cochent pas un par un)
  const setGroup = (its, on) => setThird({ ...third, ...Object.fromEntries(its.map(x => [x.id, on])) });

  const canNext = {
    backup: !u.gate && (dest == null || dest === B.dest) && !running,
    golem: !!plan && !plan.error,
    third: !!plan && !plan.error,
    review: rev && !rev.error && !rev.gate && rev.ids.length && (!rev.needs_password || st.sudo_ok) && !started,
    uninstall: R.state === 'done',
    done: false,
  }[cur];
  const go = async n => {
    if (n > i) {
      if (cur === 'third') await api('/api/third', { third });
      if (cur === 'review') { if (!(await startRun(false))) return; }
    }
    setErr('');
    setI(Math.max(0, Math.min(SCREENS.length - 1, n)));
  };

  const groupBlock = (g, editable) => {
    const its = items.filter(x => x.group === g);
    if (!its.length) return '';
    const k = its.filter(picked).length;
    const deps = g === 'apt' && plan.apt_deps && plan.apt_deps.length
      ? ` The ${plan.apt_deps.length} dependencies they pulled in go with them, unless something installed before golem needs them.` : '';
    return html`<div class="grp"><div class="gh"><b>${GROUP_LABEL[g] || g}</b>
        ${its.some(ELEVATED) ? html`<span class="chip">${uac ? 'needs Windows permission' : 'needs your password'}</span>` : ''}
        ${editable ? html`<span class="chip grp-count">${k} of ${its.length} selected</span>
          <button class="btn mini ghost grp-all" onClick=${() => setGroup(its, k < its.length)}>${k < its.length ? 'Select all' : 'Select none'}</button>` : ''}
        <span class="muted">${editable ? (GROUP_NOTE[g] || '') + deps : ''}</span></div>
      <div class=${cls('its', g === 'apt' && 'cols')}>${its.map(it => editable
        ? html`<label class=${cls('it', 'pickable', picked(it) && 'on')}><input type="checkbox" checked=${picked(it)} onChange=${() => toggle(it.id)} />
            <span class="lb"><b>${it.label}</b> <${Origin} it=${it} /><span class="why">${it.reason}</span></span><${Paths} it=${it} /></label>`
        : html`<div class=${cls('it', !it.default && 'stays')}><i>${it.default ? '✓' : '—'}</i>
            <span class="lb"><b>${it.label}</b> <${Origin} it=${it} /><span class="why">${it.default ? it.reason : 'stays — ' + it.reason}</span></span><${Paths} it=${it} /></div>`)}</div></div>`;
  };
  const planState = !plan ? html`<p class="muted">reading what golem installed on this machine…</p>`
    : plan.error ? html`<div class="card"><b class="bad">✗ ${plan.error}</b><p class="muted">Nothing has been touched. Close the uninstaller and try again, or run <code>golem uninstall --dry-run</code> in a terminal to see why.</p></div>` : null;
  const logBox = html`<div class="log" ref=${logEl}>${log.length ? log.map(l => html`<span class=${cls('ln', l.line.startsWith('$') && 'cmd', l.line.startsWith('✗') && 'err', (l.line.startsWith('▶') || l.line.startsWith('✓ backup')) && 'hd')}>${l.line}</span>`) : html`<span class="ln muted">the output shows here, live</span>`}</div>`;

  const Screen = {
    backup: () => html`
      <h1>Back up first <small>your sounds, presets and songs leave with golem</small></h1>
      ${!u.venv ? html`<div class="card"><b class="warn">The backup cannot run on this machine</b>
          <p class="muted">golem's Python environment is missing (<code>${u.venv_path}</code>), and the backup runs with it. Your presets, songs and settings are still in <code>${u.root}</code> — copy that folder somewhere safe by hand if you need them, before going on.</p>
          <label class=${cls('pick', 'chk-pick', B.skip_confirmed && 'on')}><input type="checkbox" checked=${B.skip_confirmed} onChange=${e => backupCfg({ skip_confirmed: e.target.checked })} />
            <span><b>Continue without a backup</b><br/><span class="muted">I understand that my presets, songs, recordings and settings are deleted with golem.</span></span></label></div>`
      : html`
        <label class=${cls('pick', 'chk-pick', B.enabled && 'on')}><input type="checkbox" checked=${B.enabled} disabled=${running} onChange=${e => backupCfg({ enabled: e.target.checked })} />
          <span><b>Back up before uninstalling</b> — recommended<br/><span class="muted">Two zips you can import into a new golem (⇅ I/O ▸ Import), this rack's lifetime number, your REAPER license, and a README that says how to put each one back. Every file is read back and checked before anything is removed.</span></span></label>
        ${B.enabled ? html`<div class="card">
            <div class="field"><label>Save to</label><input type="text" spellcheck="false" value=${dest ?? B.dest} disabled=${running}
              onInput=${e => setDest(e.target.value)} onBlur=${() => dest != null && dest !== B.dest && backupCfg({ dest })}
              onKeyDown=${e => e.key === 'Enter' && dest != null && backupCfg({ dest })} /></div>
            <p class="muted">A folder outside golem's — a USB drive works. Not inside <code>${u.root}</code>: it is deleted.</p>
            ${destErr ? html`<p class="bad">✗ ${destErr}</p>` : ''}
            ${est ? html`<div class="row"><span>About <b>${human(est.need)}</b> needed${est.simulated ? ' (simulated)' : ''}</span><span class="grow"></span>
                <span class="muted">${human(est.free)} free there</span></div>
              ${est.need != null && est.free != null ? html`<div class=${cls('bar', !est.fits && 'over')}><i style=${'width:' + Math.min(100, est.need / Math.max(1, est.free) * 100) + '%'}></i></div>` : ''}
              ${est.fits === false ? html`<p class="bad">Not enough space there — pick another folder or a drive.</p>` : ''}
              ${est.error ? html`<p class="muted">size unknown: ${est.error}</p>` : ''}` : html`<p class="muted">measuring…</p>`}
            <label class=${cls('pick', 'chk-pick', B.secrets && 'on')}><input type="checkbox" checked=${B.secrets} disabled=${running} onChange=${e => backupCfg({ secrets: e.target.checked })} />
              <span><b>Include my keys</b><br/><span class="warn">Copies your API keys, the golem.fm pairing token, your paired tablets and phones and your Wi-Fi passwords, readable by anyone who gets this folder. Keep it private — or leave this off and pair again after reinstalling.</span></span></label>
          </div>
          <div class="row">
            ${B.state === 'running' ? html`<button class="btn primary" disabled>⏳ backing up and checking…</button><span class="muted">this can take a few minutes</span>`
            : B.state === 'ok' ? html`<b class="ok">✓ Backup verified</b><span class="muted">${(B.result.files || []).length} files in ${B.result.dest}</span>`
            : html`<button class="btn primary" disabled=${!!destErr || (est && est.fits === false)} onClick=${backupNow}>${B.state === 'fail' ? '↻ Back up again' : 'Back up now'}</button>`}
          </div>
          ${B.state === 'fail' ? html`<div class="card"><b class="bad">✗ The backup failed its verification</b><p class="muted">${B.error}</p><p class="muted">Nothing has been removed, and nothing will be until a backup is verified — or you untick it.</p></div>` : ''}
          ${B.state === 'running' || B.state === 'fail' ? logBox : ''}`
        : html`<div class="card"><b class="warn">No backup</b><p class="muted">Your presets, songs, recordings, captures and settings are deleted with golem. They cannot come back.</p></div>`}`}
      ${err ? html`<p class="bad">✗ ${err}</p>` : ''}`,
    golem: () => html`
      <h1>What goes <small>golem itself — this is what uninstalling golem means</small></h1>
      ${planState || html`
        <p class="muted">${plan.mode === 'receipt' ? html`Read from the install receipt and from this machine: only what is there now is listed.`
          : html`<b class="warn">No install receipt</b> — golem was installed before it kept one. Only what is golem's by its name goes; anything that may be shared is left alone.`}
          ${' '}Install folder: <code>${plan.root || 'not found'}</code>.</p>
        ${(plan.warnings || []).map(w => html`<p class="warn">⚠ ${w}</p>`)}
        ${plan.golem_groups.map(g => groupBlock(g, false))}
        ${!items.some(x => plan.golem_groups.includes(x.group)) ? html`<p class="muted">Nothing of golem's is left on this machine.</p>` : ''}`}`,
    third: () => html`
      <h1>Third-party software <small>golem installed it; other programs may use it — your choice</small></h1>
      ${planState || html`
        ${plan.third_groups.map(g => groupBlock(g, true))}
        ${!items.some(x => plan.third_groups.includes(x.group)) ? html`<p class="muted">Nothing here: golem installed no third-party software that is still on this machine.</p>` : ''}
        ${plan.mode !== 'receipt' ? (uac
          ? html`<p class="muted">Programs are listed but not ticked: without an install receipt nothing says golem installed them.</p>`
          : html`<p class="muted">System packages are not offered: without an install receipt nothing says which ones golem added, and guessing is how a machine loses its sound.</p>`) : ''}
        <p class="muted small">Never removed, whatever the receipt says (system base): ${(plan.never_apt || []).join(', ')}.</p>`}`,
    review: () => html`
      <h1>Review <small>exactly what is removed, nothing else</small></h1>
      ${!rev ? html`<p class="muted">preparing…</p>` : rev.error ? html`<p class="bad">✗ ${rev.error}</p>` : html`
        <div class="install-grid review">
          <div>
            <div class="card"><b>Backup</b>${B.state === 'ok' ? html`<span class="ok">✓ verified in ${B.result.dest}</span>` : html`<span class="warn">none — your data goes with golem</span>`}</div>
            ${rev.needs_password && !st.sudo_ok ? html`<div class="card"><p>Removing system settings and packages needs administrator rights. Your password is used for this uninstall only — it is <b>never written anywhere</b> and forgotten when this window closes.</p>
              <div class="field stack"><label>Your password</label><input type="password" value=${pw} onInput=${e => setPw(e.target.value)} onKeyDown=${e => e.key === 'Enter' && checkPw()} autofocus />
                <button class="btn primary" disabled=${!pw || busy} onClick=${checkPw}>${busy ? '⏳' : 'Check'}</button></div>
              ${pwErr ? html`<p class="bad">✗ ${pwErr}</p>` : ''}</div>`
            : rev.needs_password ? html`<div class="card"><b class="ok">✓ password checked</b><span class="muted">kept in memory until this window closes</span></div>` : ''}
            ${rev.needs_uac ? html`<div class="card uac-note"><b>Windows asks your permission once</b><p class="muted">When the uninstall starts, Windows shows its permission prompt (UAC) for the system settings and programs. Approve it. If you refuse, those items stay and you can retry.</p></div>` : ''}
            ${rev.gate ? html`<p class="bad">✗ ${rev.gate}</p>` : ''}
            <p class="muted">golem stops first. A step that fails is said, the others go on, and you can retry it.</p>
            ${rev.kept.length ? html`<div class="card"><b>Stays (${rev.kept.length})</b><p class="muted">${rev.kept.map(k => k.label).join(' · ')}</p></div>` : ''}
          </div>
          <div class="sel"><div class="gh"><b>Removed (${rev.items.length})</b></div>
            <div class="its">${rev.items.map(it => html`<div class="it"><i>✓</i><span class="lb"><b>${it.label}</b> <span class="chip">${GROUP_LABEL[it.group] || it.group}</span>${ELEVATED(it) ? html` <span class="chip">${uac ? 'Windows permission' : 'password'}</span>` : ''}<span class="why">${it.action}${it.paths && it.paths.length ? ' · ' + it.paths.join(', ') : ''}</span></span></div>`)}</div></div>
        </div>`}
      ${err ? html`<p class="bad">✗ ${err}</p>` : ''}`,
    uninstall: () => {
      const failed = R.failed || [];
      const byId = Object.fromEntries(items.map(x => [x.id, x]));
      return html`
      <h1>Uninstall <small>${u.root}</small></h1>
      <div class="install-grid"><div>
        <div class="steps">${steps.map(([sid, label]) => {
          const s = (R.steps || {})[sid];
          const state = R.state === 'running' && R.current === sid ? 'running' : !s ? 'pending' : s.fail ? 'fail' : 'ok';
          return html`<div class=${cls('step', state)}><i>${state === 'ok' ? '✓' : state === 'fail' ? '✗' : state === 'running' ? '⏳' : '·'}</i>${label}${s ? html`<small>${s.n - s.fail}/${s.n}</small>` : ''}</div>`;
        })}</div>
        ${R.state === 'running' ? html`<p class="muted">⏳ working — do not close this window.</p>` : ''}
        ${R.state === 'done' && R.ok ? html`<p class="ok">✓ everything chosen was removed — tap Next.</p>` : ''}
        ${R.error ? html`<p class="bad">✗ ${R.error}</p>` : ''}
        ${R.state === 'done' && failed.length ? html`<div class="card"><b class="bad">✗ ${failed.length} item${failed.length === 1 ? '' : 's'} could not be removed</b>
            <div class="its">${failed.map(id => html`<div class="it"><i class="bad">✗</i><span class="lb"><b>${(byId[id] || {}).label || id}</b><span class="why">${(R.items[id] || {}).msg || 'not done'}</span></span></div>`)}</div>
            <p class="muted">Everything else went on. Fix the cause, then retry — or go on: the receipt keeps what remains, so <code>golem uninstall</code> can finish later.</p>
            <div class="row"><button class="btn primary" onClick=${() => startRun(true)}>↻ Retry what failed</button></div></div>` : ''}
        ${R.state === 'done' && !R.ok ? html`<${UReport} r=${st.uninstall && st.uninstall.report} />` : ''}
        ${err ? html`<p class="bad">✗ ${err}</p>` : ''}
      </div><div>${logBox}</div></div>`;
    },
    done: () => {
      const failed = R.failed || [];
      const chosen = new Set(R.chosen || []);
      const kept = items.filter(x => !chosen.has(x.id));
      const relog = (R.items['system:audio-group'] || {}).ok;
      const keptPk = R.kept || [];
      return html`
      <h1>${R.ok ? 'golem is uninstalled' : 'golem is partly uninstalled'}</h1>
      <div class="done">
        <div class="card"><b>Your backup</b>${B.state === 'ok' ? html`
            <p><code>${B.result.dest}</code></p>
            <p class="muted">Open <b>README.txt</b> there: it says how to come back — install golem again, then ⇅ I/O ▸ Import each zip. The rack's number and your keys are copied back by hand, as it explains.</p>`
          : html`<p class="muted">No backup was made.</p>`}
          ${R.log_path && B.state === 'ok' && !(B.result || {}).dry ? html`<p class="muted">The log of this uninstall is next to it: <code>${R.log_path}</code></p>` : ''}
          ${R.after_log ? html`<p class="muted">Python is uninstalled a few seconds after you close this window. What happened is written to <code>${R.after_log}</code></p>` : ''}
          ${R.deps_removed ? html`<p class="muted">${R.deps_removed} ${R.deps_removed === 1 ? 'dependency' : 'dependencies'} of golem's packages removed with them.</p>` : ''}
          ${relog ? html`<p class="warn"><b>Log out and back in once</b> (or restart): leaving the audio group takes effect at your next session.</p>` : ''}
          <div class="row"><button class="btn primary" onClick=${quit}>Close the uninstaller</button></div></div>
        <div class="card"><b>What remains, and why</b>
          ${!failed.length && !kept.length && !keptPk.length ? html`<p class="muted">Nothing that golem recorded: everything it placed is gone.</p>` : ''}
          ${(plan.check_yourself || []).length ? html`<div class="check-yourself"><b>Check yourself</b>
            <p class="muted">golem may have set these, but nothing records them, so they cannot be told from yours. Nothing was deleted:</p>
            <ul>${plan.check_yourself.map(c => html`<li class="muted">${c}</li>`)}</ul></div>` : ''}
          <div class="its">
            ${keptPk.map(id => html`<div class="it stays"><i>—</i><span class="lb"><b>${((items.find(x => x.id === id)) || {}).label || id}</b><span class="why">${(R.items[id] || {}).msg || 'kept'}</span></span></div>`)}
            ${failed.map(id => html`<div class="it"><i class="bad">✗</i><span class="lb"><b>${((items.find(x => x.id === id)) || {}).label || id}</b><span class="why">failed: ${(R.items[id] || {}).msg || ''} — run <code>golem uninstall</code> again later (the receipt remembers it)</span></span></div>`)}
            ${kept.map(it => html`<div class="it stays"><i>—</i><span class="lb"><b>${it.label}</b> <${Origin} it=${it} /><span class="why">${plan.golem_groups.includes(it.group) ? it.reason : 'you kept it — ' + it.reason}</span></span></div>`)}
          </div></div>
      </div>`;
    },
  }[cur]();

  return html`<div class="shell">
    <div class="top"><span class="lg">/golem_</span><span class="sub">uninstaller</span>${st.dry ? html`<span class="dry">DRY RUN — nothing is removed</span>` : ''}</div>
    <div class="main">
      <div class="rail">${SCREENS.map(([id, label], k) => html`<div class=${cls('st', k === i && 'cur', k < i && 'ok')}><i>${k < i ? '✓' : k + 1}</i><b>${label}</b></div>`)}
        <div class="foot">${started ? 'golem stops first; the folder goes last.' : 'Nothing is removed before the Review screen.'}</div></div>
      <div class="body">
        <div class="content">${Screen}</div>
        <div class="foot">
          ${!started ? html`<button class="btn ghost" disabled=${running} onClick=${quit}>Cancel</button>` : ''}
          ${!started ? html`<button class="btn ghost" disabled=${i === 0 || running} onClick=${() => go(i - 1)}>← Back</button>` : ''}
          <span class="grow"></span>
          ${cur === 'review' ? html`<button class="btn primary danger" disabled=${!canNext} onClick=${() => go(i + 1)}>Uninstall golem</button>`
          : cur !== 'done' ? html`<button class="btn primary" disabled=${!canNext} onClick=${() => go(i + 1)}>Next →</button>` : ''}
        </div>
      </div>
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
