// SPDX-License-Identifier: GPL-3.0-or-later
// SETTINGS ▸ HEALTH (docs/health.md §1, maquette mockups/health.html validée le 2026-10-20) : UN écran, trois couches.
// « Now » : des faits que le bridge a MESURÉS (bridge/health.py), chacun avec sa source et, en orange ou rouge, le
// geste qui répare. « Check now » : les contrôles à la demande, chacun avec son coût annoncé. « Incidents » : les
// pannes de cette machine et COMMENT elles ont fini (bridge/incidents.py).
// HEALTH ▸ FIX (docs/assistant.md §3, maquette mockups/health-fix.html validée le 2026-10-20) : quand le registre
// d'actions (bridge/fixes.py) sait répondre à un fait, la ligne porte « Fix… » ; la FEUILLE dit avant → après, ce que
// ça coûte, comment golem vérifiera et comment revenir — rien ne part sans le tap. La garde (une prise, une chanson,
// un mode verrouillé) est celle du bridge : l'écran affiche sa raison, il ne la juge pas.
// La page ne juge rien : elle affiche le verdict du bridge et ses dates.
import { html, useState, useEffect, api, post, go, cls } from './lib.js';
import { ago, countsLine, incidentChip, incidentLine, hintCandidate, undoCandidate, lastFixUndo } from './health-model.mjs';

const POLL_MS = 5000;
const FIX = '/api/health/fix';
const INC = '/api/health/incidents';
const ASK = '/api/health/assistant';

export function HealthPage({ focus }) {
  const [doc, setDoc] = useState(null);
  const [err, setErr] = useState(null);
  const [fix, setFix] = useState({});                     // {current, last} — la réparation en cours
  const [incs, setIncs] = useState([]);
  const [sheet, setSheet] = useState(null);               // {action, params, incident} — la feuille ouverte
  // la ligne qu'une puce de /live désigne : soulignée quelques secondes, jamais une action d'office
  const [lit, setLit] = useState(focus || null);
  useEffect(() => { setLit(focus || null); if (!focus) return; const t = setTimeout(() => setLit(null), 6000); return () => clearTimeout(t); }, [focus]);
  const running = !!(fix.current && ['running', 'verifying'].includes(fix.current.phase));
  // « ASK GOLEM » (docs/assistant.md §5, maquette écran 4) : présent seulement si le rack est appairé et que le mode le
  // permet ; la conversation vit dans la page (rien n'est gardé : ni ici, ni chez golem.fm)
  const [assist, setAssist] = useState(null);
  const [askOpen, setAskOpen] = useState(false);
  const [convo, setConvo] = useState([]);
  useEffect(() => { api(ASK).then(setAssist).catch(() => setAssist(null)); }, []);
  useEffect(() => {
    let alive = true;
    const load = () => {
      api('/api/health/facts').then(d => { if (alive) { setDoc(d); setErr(null); } }).catch(e => alive && setErr(e));
      api(INC).then(d => alive && setIncs(d.items || [])).catch(() => {});
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);
  // la vérification d'une réparation se suit à la seconde ; sinon un coup d'œil toutes les 5 s suffit
  useEffect(() => {
    let alive = true;
    const load = () => api(FIX).then(d => alive && setFix(d || {})).catch(() => {});
    load();
    const t = setInterval(load, running ? 1000 : POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [running]);
  useEffect(() => { if (!running) api(INC).then(d => setIncs(d.items || [])).catch(() => {}); }, [running]);
  if (!doc) return html`<div class="hl-page pg-body"><div class="hl-measuring">${err ? 'The bridge did not answer — retrying…' : 'Measuring…'}</div></div>`;
  const facts = doc.facts || [];
  const guard = doc.guard || {};
  const cur = running ? fix.current : null;
  // pendant une vérification, le bandeau dit ce que golem regarde — le verdict du bridge revient ensuite
  const v = cur ? { level: 'on', title: 'Checking the fix.', text: cur.label + ' · ' + (cur.text || '') } : (doc.verdict || {});
  const age = ago(Math.max(0, (Date.now() / 1000) - doc.at));   // ≈ l'âge du cache (≤ 5 s) ; le bridge date, l'écran arrondit
  const now = doc.at;
  // la question facultative attend une prise ou une chanson, pas « quelqu'un a touché l'écran il y a 30 s » : c'est
  // justement la personne devant l'écran qui répond
  const ask = hintCandidate(incs, now, guard.free === false && !/^in use/.test(guard.why || '') ? guard.why : null);
  const undo = undoCandidate(incs);
  const lastUndo = running ? null : lastFixUndo(fix.last, now);
  const sendHint = h => post(INC + '/' + ask.id + '/hint', { hint: h }).then(() => api(INC).then(d => setIncs(d.items || []))).catch(() => {});
  const fixCell = f => {
    const r = f.repair;
    if (cur && r && (cur.incident ? cur.incident === f.incident : cur.action === r.action))
      return html`<span class="hl-fix hl-on">checking…</span>`;
    if (r && (f.level === 'warn' || f.level === 'bad'))
      return r.blocked || running ? html`<span class="hl-src hl-why">${r.blocked || 'another fix is running'}</span>`
        : html`<button class=${'hl-fix hl-go edit-only hl-' + f.level} onClick=${() => setSheet({ action: r.action, params: r.params, incident: f.incident })}>${r.label}</button>`;
    if (f.fix && (f.level === 'warn' || f.level === 'bad'))
      return html`<button class=${'hl-fix hl-' + f.level} onClick=${() => go(f.fix.go)}>${f.fix.label}</button>`;
    return html`<span class="hl-src">${f.source}</span>`;
  };
  return html`
    <div class="hl-page pg-body">
      <div class=${cls('hl-verdict', 'hl-' + (v.level || 'wait'))} data-doc="health.verdict">
        <span class="hl-big"></span>
        <div class="hl-vtxt"><b>${v.title || ''}</b><span class="hl-m">${v.text || ''}</span></div>
        <span class="hl-counts">checked ${age} · ${((doc.verdict || {}).counts || {}).total || facts.length} facts
          ${countsLine((doc.verdict || {}).counts).map(c => html` · <b class=${'hl-c hl-' + c.level}>${c.n}</b>${c.word ? ' ' + c.word : ''}`)}</span>
        ${assist && assist.available ? html`<button class="hl-ask" data-doc="health.ask" onClick=${() => setAskOpen(true)}><b>✦ Ask golem</b><span>your words, e.g. « it crackles »</span></button>` : ''}
      </div>
      <div class="hl-cols">
        <div class="hl-card hl-now" data-doc="health.now">
          <div class="hl-ch"><b>Now</b><span class="hl-m">read every 5 s · nothing touched</span></div>
          <div class="hl-rows">
            ${facts.map(f => html`<div class=${cls('hl-row', lit === f.id && 'hl-lit')} key=${f.id} data-doc=${'health.fact:' + f.id} title=${f.text}>
              <span class=${'hl-d hl-' + (cur && f.repair && cur.action === f.repair.action ? 'on' : f.level)}></span>
              <span class="hl-n">${f.name}<small>${cur && f.repair && cur.action === f.repair.action ? cur.text : f.text}</small></span>
              ${fixCell(f)}
            </div>`)}
          </div>
          <div class="hl-guard" data-doc="health.guard"><i class=${cls('hl-gi', guard.free === true && 'ok', guard.free === false && 'busy')}></i>
            <span>${guard.free === true ? 'Rack free for a check' + (guard.idle_s != null ? ' · nobody touched it for ' + ago(guard.idle_s).replace(' ago', '') : '')
              : guard.free === false ? 'Rack not free for a check — ' + (guard.why || 'in use')
              : 'Rack availability unknown'}</span>
          </div>
        </div>
        <div class="hl-side">
          <div class="hl-card" data-doc="health.checks">
            <div class="hl-ch"><b>Check now</b><span class="hl-m">each one says what it costs</span></div>
            <${SilenceHunt} />
            <div class="hl-chk"><span class="hl-cn"><b>Inputs, output, pedalboard</b><small>the first-start check, again: play, listen, press a switch</small></span>
              <span class="hl-cost"><span class="hl-tag">~2 min</span><span class="hl-tag snd">click</span><span class="hl-tag you">you</span>
                <button class="hl-run edit-only" onClick=${async () => { await post('/api/health/first-check', { action: 'reset' }).catch(() => {}); go('live'); }}>Run</button></span></div>
            ${doc.first_check && doc.first_check.done_at ? html`<div class="hl-m">last run ${ago(doc.at - doc.first_check.done_at)} · ${doc.first_check.verdict === 'ok' ? 'all three gestures green' : 'one gesture missing'}</div>` : ''}
          </div>
          <div class="hl-card hl-grow hl-incs" data-doc="health.incidents">
            <div class="hl-ch"><b>Incidents</b><span class="hl-m">this golem · 30 days · sent with the reports</span></div>
            ${lastUndo ? html`<div class="hl-inc">
                <span class=${'hl-d ' + (lastUndo.phase === 'done' ? 'hl-ok' : 'hl-bad')}></span>
                <span class="hl-cn"><b>${lastUndo.label}</b><small>${lastUndo.text || ''}</small></span>
                <button class="hl-link hl-undo edit-only" onClick=${() => setSheet({ ...lastUndo.undo, by: 'undo' })}>undo</button>
                <span class=${'hl-by ' + (lastUndo.phase === 'done' ? 'act' : 'open')}>${lastUndo.phase === 'done' ? 'done' : 'failed'}</span>
              </div>` : ''}
            ${incs.length ? incs.slice(0, ask ? 4 : 5).map(i => {
              const c = incidentChip(i);
              return html`<div class="hl-inc" key=${i.id} title=${i.detail || ''}>
                <span class=${'hl-d ' + (i.state === 'open' ? 'hl-bad' : i.state === 'verifying' ? 'hl-on' : '')}></span>
                <span class="hl-cn"><b>${i.title}</b><small>${incidentLine(i, now)}</small></span>
                ${undo && undo.id === i.id && !running ? html`<button class="hl-link hl-undo edit-only" onClick=${() => setSheet({ ...undo.undo, by: 'undo' })}>undo</button>` : ''}
                <span class=${'hl-by ' + c.cls}>${c.text}</span>
              </div>`;
            }) : html`<div class="hl-empty">No incident in the last 30 days. When something fails, it shows here with how it ended — fixed by golem, by a restart, or by you.</div>`}
            ${incs.length > (ask ? 4 : 5) ? html`<div class="hl-m">+ ${incs.length - (ask ? 4 : 5)} earlier</div>` : ''}
            ${ask ? html`<div class="hl-hint"><b>« ${ask.title} » came back by itself. What fixed it?</b>
                ${['cable', 'gain', 'power', 'other'].map(h => html`<button key=${h} onClick=${() => sendHint(h)}>${h[0].toUpperCase() + h.slice(1)}</button>`)}
                <span class="hl-m">optional</span></div>` : ''}
          </div>
        </div>
      </div>
      ${askOpen && assist ? html`<${AskDrawer} assist=${assist} setAssist=${setAssist} convo=${convo} setConvo=${setConvo}
          onClose=${() => setAskOpen(false)}
          onReview=${pr => { const f = facts.find(x => x.repair && x.repair.action === pr.action);
            setAskOpen(false); setSheet({ action: pr.action, params: pr.params, incident: f && f.incident, by: 'assistant' }); }} />` : ''}
      ${sheet ? html`<${FixSheet} req=${sheet} onClose=${() => setSheet(null)} onStarted=${f => { setSheet(null); setFix({ current: f }); }} />` : ''}
    </div>`;
}

// LE TIROIR « Ask golem » (mockups/health-fix.html, écran 4) : golem.fm répond en mots simples, cite l'aide, et propose
// au plus une action — que le BRIDGE a déjà revalidée (registre, schéma, garde). « Review… » ouvre la feuille « Fix » :
// c'est toujours la machine qui montre, applique et vérifie. Le consentement est demandé à la première question.
const helpName = id => { const p = String(id).split('/')[1] || id; return p.replace(/-/g, ' ').replace(/^./, c => c.toUpperCase()); };
function AskDrawer({ assist, setAssist, convo, setConvo, onClose, onReview }) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true); setQ('');
    const history = convo.filter(t => t.a).map(t => ({ q: t.q, a: t.a }));
    setConvo(c => [...c, { q: question, pending: true }]);
    const r = await post(ASK, { question, history }).catch(e => ({ ok: false, message: (e.body && e.body.error) || 'golem did not answer' }));
    setConvo(c => c.map((t, i) => i === c.length - 1 ? { q: question, ...(r.ok ? { a: r.answer, cites: r.cites, propose: r.propose, dropped: r.dropped } : { err: r }) } : t));
    setBusy(false);
  };
  const allow = on => post(ASK, { consent: on }).then(setAssist).catch(() => {});
  return html`<div class="hl-drawer" role="dialog" aria-label="Ask golem">
    <div class="hl-dh"><b>✦ Ask golem</b><span class="hl-m">answered by golem.fm · your question and a summary of this golem's state are sent</span>
      <button class="hl-x" onClick=${onClose} aria-label="close">×</button></div>
    ${!assist.consent ? html`<div class="hl-msgs"><div class="hl-a">
        <b>Before your first question</b>
        <span>Your question and a summary of this golem's state — the Health facts, open incidents, the types of blocks
          played, never a preset, song or person name — are sent to golem.fm and forwarded to the AI provider it uses, to
          answer it. golem.fm keeps no text of it.</span>
        <div class="hl-acts"><button onClick=${onClose}>Not now</button><button class="g" onClick=${() => allow(true)}>Allow and ask</button></div>
      </div></div>` : html`
      <div class="hl-msgs">
        ${!convo.length ? html`<div class="hl-m hl-empty2">Describe what you hear or what you want to do, in your words. golem.fm answers from this golem's
          facts; a fix it proposes is checked here, shown to you, and runs only on your tap — never while you play.</div>` : ''}
        ${convo.map((t, i) => html`<div class="hl-turn" key=${i}>
          <div class="hl-q">${t.q}</div>
          ${t.pending ? html`<div class="hl-a hl-m">golem.fm is thinking…</div>` : ''}
          ${t.err ? html`<div class="hl-a hl-aerr"><span>${t.err.message}</span>
              ${t.err.error === 'repair' ? html`<button class="hl-link" onClick=${() => { onClose(); go('system/connect/golemfm'); }}>Settings ▸ Connect ▸ golem.fm →</button>` : ''}</div>` : ''}
          ${t.a ? html`<div class="hl-a"><span>${t.a}</span>
              ${(t.cites || []).length ? html`<span class="hl-cite">${'Help: ' + t.cites.map(helpName).join(' · ')}</span>` : ''}
              ${t.propose ? html`<div class="hl-prop"><span class="hl-cn"><b>${t.propose.label}</b><small>${t.propose.why || ''}</small></span>
                  ${t.propose.blocked ? html`<span class="hl-why">${t.propose.blocked}</span>`
                    : html`<button class="hl-run" onClick=${() => onReview(t.propose)}>Review…</button>`}</div>` : ''}
              ${t.dropped ? html`<span class="hl-m">${t.dropped}.</span>` : ''}</div>` : ''}
        </div>`)}
      </div>
      <div class="hl-din"><input value=${q} maxLength="2000" placeholder="Ask in your words…" disabled=${busy}
          onInput=${e => setQ(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter') send(); }} />
        <button class="hl-run" disabled=${busy || !q.trim()} onClick=${send}>Send</button></div>
      <div class="hl-dfoot">golem.fm proposes · this golem checks the action, shows it, runs it on your tap, and verifies it.
        <button class="hl-link" onClick=${() => allow(false)}>Stop sending</button></div>`}
  </div>`;
}

// LA FEUILLE « Fix » (mockups/health-fix.html, écran 2) : le bridge décrit (POST sans `confirm`), le musicien décide.
// La garde est revérifiée par le bridge au moment du tap : la feuille peut avoir été ouverte avant une prise.
function FixSheet({ req, onClose, onStarted }) {
  const [plan, setPlan] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    post(FIX, { action: req.action, params: req.params || {} }).then(setPlan)
      .catch(e => setErr((e.body && e.body.error) || 'golem cannot describe this fix'));
  }, []);
  const apply = async () => {
    setBusy(true); setErr('');
    try {
      const r = await post(FIX, { action: req.action, params: req.params || {}, confirm: true, incident: req.incident || null, by: req.by || 'button' });
      onStarted(r.fix);
    } catch (e) { setErr((e.body && e.body.error) || 'refused'); setBusy(false); }
  };
  const blocked = plan && plan.blocked;
  return html`<div class="hl-dim" onClick=${onClose}></div>
    <div class="hl-sheet" role="dialog" aria-label=${plan ? plan.title : 'Fix'}>
      ${!plan ? html`<div class="hl-m">${err || 'Reading what this fix does…'}</div>` : html`
        <h2>${req.by === 'undo' ? 'Undo: ' + plan.title.replace(/^Fix: /, '') : plan.title}</h2>
        ${plan.why ? html`<div class="hl-why2">${plan.why}</div>` : ''}
        ${plan.before && plan.after ? html`<div class="hl-ba">
          <div><small>Now</small><b>${plan.before.value}</b>${plan.before.sub ? html`<span class="hl-m">${plan.before.sub}</span>` : ''}</div>
          <span class="hl-ar">→</span>
          <div class="hl-after"><small>After</small><b>${plan.after.value}</b>${plan.after.sub ? html`<span class="hl-m">${plan.after.sub}</span>` : ''}</div></div>` : ''}
        ${(plan.costs || []).map(c => html`<div class="hl-sl"><i>↻</i><span>${c}</span></div>`)}
        ${plan.verify ? html`<div class="hl-sl"><i>✓</i><span>${plan.verify}</span></div>` : ''}
        ${plan.undo && req.by !== 'undo' ? html`<div class="hl-sl"><i>⤺</i><span>${plan.undo}</span></div>` : ''}
        ${blocked || err ? html`<div class="hl-sl hl-no"><i>!</i><span>${err || 'Not now: ' + blocked + '.'}</span></div>` : ''}
        <div class="hl-acts"><button onClick=${onClose}>Not now</button>
          <button class="g" disabled=${busy || !!blocked} onClick=${apply}>${busy ? 'Starting…' : plan.apply_label}</button></div>`}
    </div>`;
}

// « WHY NO SOUND? » (docs/health.md §4.1, bridge/silence.py) : lecture seule — le musicien joue pendant quatre secondes,
// le bridge relève les crêtes le long de la chaîne, les pistes d'entrée et les fichiers des NAM/IR, et dit OÙ le signal
// s'arrête. Le rapport reste dans presets/.silence-<hhmmss>.json. Jamais pendant une prise ou une chanson (409 dit pourquoi).
const SIL = '/api/health/silence';
function SilenceHunt() {
  const [st, setSt] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    const load = () => api(SIL).then(d => alive && setSt(d)).catch(() => {});
    load();
    const t = setInterval(load, 1000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const run = async () => {
    setErr('');
    const r = await post(SIL, { seconds: 4 }).catch(e => ({ error: (e.body && e.body.error) || String(e) }));
    if (r.error) setErr(r.error);
    api(SIL).then(setSt).catch(() => {});
  };
  const phase = (st && st.phase) || 'idle';
  const rep = st && st.report;
  const v = rep && rep.verdict;
  const left = st && st.play_until ? Math.max(0, Math.ceil(st.play_until - st.now)) : null;
  const running = phase === 'listening' || phase === 'reading';
  return html`
    <div class="hl-chk"><span class="hl-cn"><b>Why no sound?</b><small>reads the levels along the chain, names the first silent stage</small></span>
      <span class="hl-cost"><span class="hl-tag ok">read-only</span><span class="hl-tag you">you play</span>
        <button class=${cls('hl-run edit-only', running && 'busy')} disabled=${running} onClick=${run}>
          ${phase === 'listening' ? 'Play now…' : phase === 'reading' ? 'Reading…' : 'Run'}</button></span></div>
    ${err ? html`<div class="hl-sil hl-bad"><b>Not now.</b> ${err}</div>` : ''}
    ${phase === 'listening' ? html`<div class="hl-sil hl-on"><b>Play now${left != null ? ' — ' + left + ' s' : ''}.</b> The bridge watches the peaks of every track while you play.</div>` : ''}
    ${phase === 'reading' ? html`<div class="hl-sil hl-on"><b>Reading the chain…</b> input tracks, hardware outputs, the files each NAM and IR loaded.</div>` : ''}
    ${phase === 'error' ? html`<div class="hl-sil hl-bad"><b>The hunt failed.</b> ${st.error || ''}</div>` : ''}
    ${phase === 'done' && v ? html`<div class=${'hl-sil hl-' + (v.level || 'bad')}>
        <div><b>${v.title}</b> <span class="hl-m">— stops at: ${v.stage}</span></div>
        <div class="hl-silt">${v.text}</div>
        ${rep.tracks && rep.tracks.length ? html`<div class="hl-trk">${rep.tracks.slice(0, 8).map(t => html`<span class=${cls('hl-tr', t.peak_db > -60 && 'sig', t.mute && 'mute')} title=${'peak ' + t.peak_db + ' dBFS · vol ' + t.vol_db + ' dB · hw sends ' + t.hw_sends + (t.mute ? ' · muted' : '')}>
            ${t.name.replace('Sandbox #', '')} <i>${t.peak_db > -100 ? t.peak_db + ' dB' : '—'}</i>${t.hw_sends ? ' ⇥' : ''}</span>`)}</div>` : ''}
        <div class="hl-m">${rep.file ? 'kept in ' + rep.file + ' · ' : ''}<button class="hl-link edit-only" onClick=${() => post(SIL, { action: 'clear' }).then(() => api(SIL).then(setSt))}>clear</button></div>
      </div>` : ''}`;
}
