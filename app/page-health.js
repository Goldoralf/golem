// SPDX-License-Identifier: GPL-3.0-or-later
// SETTINGS ▸ HEALTH (docs/health.md §1 ; V2, maquette mockups/health-v2.html validée le 2026-11-25 — la V1,
// mockups/health.html, montrait treize faits au même niveau avec leurs fichiers sources : « très chargée, on ne comprend
// pas tout »). UN écran : le VERDICT en mots (peut-on jouer ?), « Needs you » (une carte par fait orange ou rouge : ce
// qui se passe, le geste qui répare), « Everything else is fine » (les faits verts en pastilles), « Test it » (deux
// contrôles à la demande, dits par ce qu'on y fait et ce que ça dure), « History » (bridge/incidents.py, groupé par
// sujet, en mots). Un tap ouvre le DÉTAIL d'un fait ; ses sources y sont repliées sous « For developers ».
// HEALTH ▸ FIX (docs/assistant.md §3, maquette mockups/health-fix.html validée le 2026-10-20) : quand le registre
// d'actions (bridge/fixes.py) sait répondre à un fait, la ligne porte « Fix… » ; la FEUILLE dit avant → après, ce que
// ça coûte, comment golem vérifiera et comment revenir — rien ne part sans le tap. La garde (une prise, une chanson,
// un mode verrouillé) est celle du bridge : l'écran affiche sa raison, il ne la juge pas.
// La page ne juge rien : elle affiche le verdict du bridge et ses dates.
import { html, useState, useEffect, api, post, go, cls } from './lib.js';
import { ago, hintCandidate, undoCandidate, lastFixUndo, needs, verdictWords, problemTitle, plainName, chipText, isInfo, offStage,
  OFF_STAGE_NOTE, sinceWords, historyRows, chipLevel } from './health-model.mjs';

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
  const [detail, setDetail] = useState(null);                // le fait dont la feuille de détail est ouverte
  const [hintOpen, setHintOpen] = useState(false);
  const [all, setAll] = useState(false);                     // la liste de tous les faits (« + N more »)          // « what fixed it? » déplié
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
  const now = doc.at;
  const age = ago(Math.max(0, (Date.now() / 1000) - doc.at));   // ≈ l'âge du cache (≤ 5 s) ; le bridge date, l'écran arrondit
  // HEALTH V2 (maquette mockups/health-v2.html, validée le 2026-11-25) : le verdict en mots, ce qui demande en cartes,
  // ce qui va bien en pastilles, l'historique par sujet ; le détail (et les sources) dans une feuille
  const need = needs(facts);
  // les conseils d'abord (ils ne doivent jamais tomber sous « + N more »), puis l'ordre du bridge
  const fine = facts.filter(f => !need.includes(f)).sort((a, b) => !!b.advice - !!a.advice);
  // autant de pastilles que la place en laisse (rangées de quatre, sous 0, 1, 2 ou 3 cartes) ; le reste dans « All checks »
  const room = [20, 16, 12, 8][Math.min(3, need.length)];
  const shownFine = fine.length > room ? fine.slice(0, room - 1) : fine;
  const vw = verdictWords((doc.verdict || {}).level, need.length);
  const v = cur ? { level: 'on', title: 'Checking the fix…', sub: cur.label + (cur.text ? ' · ' + cur.text : '') }
    : { level: (doc.verdict || {}).level || 'wait', ...vw };
  // la question facultative attend une prise ou une chanson, pas « quelqu'un a touché l'écran il y a 30 s » : c'est
  // justement la personne devant l'écran qui répond
  const ask = hintCandidate(incs, now, guard.free === false && !/^in use/.test(guard.why || '') ? guard.why : null);
  const undo = undoCandidate(incs);
  const lastUndo = running ? null : lastFixUndo(fix.last, now);
  const sendHint = h => { setHintOpen(false); post(INC + '/' + ask.id + '/hint', { hint: h }).then(() => api(INC).then(d => setIncs(d.items || []))).catch(() => {}); };
  const openFix = f => setSheet({ action: f.repair.action, params: f.repair.params, incident: f.incident });
  // le geste d'une carte : la réparation du registre, sinon la navigation du bridge
  const act = (f, primary) => {
    const r = f.repair;
    if (cur && r && (cur.incident ? cur.incident === f.incident : cur.action === r.action)) return html`<span class="hv-busy">checking…</span>`;
    if (r && !r.blocked && !running) return html`<button class=${cls('hv-btn edit-only', primary && 'p')} onClick=${e => { e.stopPropagation(); openFix(f); }}>${r.title || r.label}</button>`;
    if (r && (r.blocked || running)) return html`<span class="hv-busy" title=${r.blocked || ''}>${r.blocked ? 'not now — ' + r.blocked : 'another fix is running'}</span>`;
    if (f.fix) return html`<button class="hv-btn" onClick=${e => { e.stopPropagation(); go(f.fix.go); }}>${f.fix.label}</button>`;
    return '';
  };
  const hist = historyRows(incs, now);
  const HIST_MAX = lastUndo ? 3 : 4;
  const fc = doc.first_check || {};
  return html`
    <div class="hl-page pg-body hv-page">
      <div class="hv-main">
        <div class=${cls('hv-verdict', 'hv-' + v.level)} data-doc="health.verdict">
          <span class="hv-big"></span>
          <div class="hv-vt"><b>${v.title}</b><span>${v.sub}${cur ? '' : ' Checked ' + age + '.'}</span></div>
          ${assist && assist.available ? html`<button class="hv-ask" data-doc="health.ask" onClick=${() => setAskOpen(true)}>✦ Ask golem</button>` : ''}
        </div>
        ${need.length ? html`<div class="hv-gh">Needs you</div>
          <div class="hv-needs">${need.slice(0, 3).map(f => html`<div class=${cls('hv-need', 'hv-' + (offStage(f) ? 'info' : f.level), lit === f.id && 'hv-lit')} key=${f.id}
              data-doc=${'health.fact:' + f.id} onClick=${() => setDetail(f.id)}>
            <div class="hv-nt"><b>${problemTitle(f)}</b>${f.level === 'bad' ? html`<span class="hv-tag bad">BROKEN</span>` : f.id === 'dropouts' ? html`<span class="hv-tag now">NOW</span>` : ''}</div>
            <div class="hv-nw">${cur && f.repair && cur.action === f.repair.action ? cur.text : f.text}${offStage(f) ? (/[.!]$/.test(f.text) ? ' ' : '. ') + OFF_STAGE_NOTE : ''}</div>
            <div class="hv-na">${act(f, true)}<button class="hv-btn s" onClick=${e => { e.stopPropagation(); setDetail(f.id); }}>Details →</button></div>
          </div>`)}
          ${need.length > 3 ? html`<button class="hv-more" onClick=${() => setDetail(need[3].id)}>+ ${need.length - 3} more</button>` : ''}</div>` : ''}
        <div class="hv-fine" data-doc="health.now">
          <div class="hv-fh"><b>${!need.length ? 'What golem watches' : fine.every(f => f.level === 'ok' || isInfo(f)) ? 'Everything else is fine' : 'Everything else'}</b><span>${fine.some(f => f.advice) ? 'blue: a tip · ' : ''}tap one for the details</span></div>
          <div class=${cls('hv-chips', fine.length > 9 && 'many')}>${shownFine.map(f => html`<button class=${cls('hv-chip', 'hv-' + chipLevel(f), lit === f.id && 'hv-lit')} key=${f.id}
              data-doc=${'health.fact:' + f.id} aria-label=${plainName(f)} onClick=${() => setDetail(f.id)}>
            <i></i><span><b>${plainName(f)}</b><small>${chipText(f)}</small></span></button>`)}
            ${shownFine.length < fine.length ? html`<button class="hv-chip hv-morechip" onClick=${() => setAll(true)}>
              <span><b>+ ${fine.length - shownFine.length} more</b><small>all checks</small></span></button>` : ''}</div>
        </div>
      </div>
      <div class="hv-side">
        <div class="hv-card" data-doc="health.checks">
          <div class="hv-fh"><b>Test it</b><span>nothing runs by itself</span></div>
          <${SilenceHunt} />
          <div class="hv-test"><b>Full check</b>
            <span>Plug, listen, press a switch, find the buffer. ~3 min. Last: ${sinceWords(fc.done_at, now)}.</span>
            <button class="hv-btn edit-only" onClick=${async () => { await post('/api/health/first-check', { action: 'reset' }).catch(() => {}); go('live'); }}>Start</button></div>
          ${guard.free === false ? html`<div class="hv-guard">Not now: ${guard.why || 'the rack is in use'}.</div>` : ''}
        </div>
        <div class="hv-card hv-grow" data-doc="health.incidents">
          <div class="hv-fh"><b>History</b><span>30 days · sent with the reports</span></div>
          ${lastUndo ? html`<div class="hv-ev"><i class=${lastUndo.phase === 'done' ? 'ok' : 'now'}></i><b>${lastUndo.label}</b>
              <span>${lastUndo.phase === 'done' ? 'done' : 'failed'}${lastUndo.text ? ' · ' + lastUndo.text : ''} · <button class="hv-link edit-only" onClick=${() => setSheet({ ...lastUndo.undo, by: 'undo' })}>undo</button></span></div>` : ''}
          ${hist.length ? hist.slice(0, HIST_MAX).map(h => html`<div class="hv-ev" key=${h.id}><i class=${h.open ? 'now' : ''}></i><b>${h.title}</b>
              <span>${h.text}${undo && undo.id === h.id && !running ? html` · <button class="hv-link edit-only" onClick=${() => setSheet({ ...undo.undo, by: 'undo' })}>undo</button>` : ''}${ask && ask.id === h.id ? html` · <button class="hv-link" onClick=${() => setHintOpen(o => !o)}>what fixed it?</button>` : ''}</span></div>`)
            : html`<div class="hv-empty">Nothing in the last 30 days. When something fails, it shows here with how it ended.</div>`}
          ${ask && hintOpen ? html`<div class="hv-hint">${['cable', 'gain', 'power', 'other'].map(h => html`<button key=${h} class="hv-btn s" onClick=${() => sendHint(h)}>${h[0].toUpperCase() + h.slice(1)}</button>`)}</div>` : ''}
          ${hist.length > HIST_MAX ? html`<div class="hv-m">+ ${hist.length - HIST_MAX} earlier</div>` : ''}
        </div>
      </div>
      ${all ? html`<div class="hl-dim" onClick=${() => setAll(false)}></div>
        <div class="hl-sheet hv-detail" role="dialog" aria-label="All checks"><h2>All checks</h2>
          <div class="hv-all">${facts.map(f => html`<button key=${f.id} class=${cls('hv-chip', 'hv-' + chipLevel(f))} onClick=${() => { setAll(false); setDetail(f.id); }}>
            <i></i><span><b>${plainName(f)}</b><small>${chipText(f)}</small></span></button>`)}</div>
          <div class="hl-acts"><button onClick=${() => setAll(false)}>Close</button></div></div>` : ''}
      ${detail ? html`<${DetailSheet} f=${facts.find(f => f.id === detail)} act=${act} onClose=${() => setDetail(null)} />` : ''}
      ${askOpen && assist ? html`<${AskDrawer} assist=${assist} setAssist=${setAssist} convo=${convo} setConvo=${setConvo}
          onClose=${() => setAskOpen(false)}
          onReview=${pr => { const f = facts.find(x => x.repair && x.repair.action === pr.action);
            setAskOpen(false); setSheet({ action: pr.action, params: pr.params, incident: f && f.incident, by: 'assistant' }); }} />` : ''}
      ${sheet ? html`<${FixSheet} req=${sheet} onClose=${() => setSheet(null)} onStarted=${f => { setSheet(null); setDetail(null); setFix({ current: f }); }} />` : ''}
    </div>`;
}

// LE DÉTAIL D'UN FAIT (maquette health-v2, écran 3) : une feuille à droite, la page reste visible. Ce qui se passe, en
// clair ; ce qu'on peut faire (le geste de la carte) ; et, replié, ce que lisent les développeurs — la source du bridge.
function DetailSheet({ f, act, onClose }) {
  const [dev, setDev] = useState(false);
  if (!f) return '';
  const bad = f.level === 'warn' || f.level === 'bad';
  return html`<div class="hl-dim" onClick=${onClose}></div>
    <div class="hl-sheet hv-detail" role="dialog" aria-label=${plainName(f)}>
      <h2><span class=${'hv-dot hv-' + chipLevel(f)}></span>${bad && !isInfo(f) ? problemTitle(f) : plainName(f)}</h2>
      <div class="hv-sec"><h4>${bad && !isInfo(f) ? 'What is happening' : 'Now'}</h4><p>${f.text}${offStage(f) && bad ? (/[.!]$/.test(f.text) ? ' ' : '. ') + OFF_STAGE_NOTE : ''}</p></div>
      ${f.advice ? html`<div class="hv-sec"><h4>Could be better</h4><p>${f.advice}</p></div>` : ''}
      ${bad && (f.repair || f.fix) ? html`<div class="hv-sec"><h4>What you can do</h4>
        <p>${f.repair ? (f.repair.title || f.repair.label) + ' — golem shows what it changes, then checks that it held.'
          : 'Open ' + f.fix.label.replace(' →', '') + ' to look at it.'}</p></div>` : ''}
      <div class="hv-sec hv-devs"><button class="hv-link" onClick=${() => setDev(d => !d)}>For developers ${dev ? '▾' : '▸'}</button>
        ${dev ? html`<div class="hv-src">${f.id} · ${f.level} · ${f.source || ''}${f.detail ? ' · ' + JSON.stringify(f.detail) : ''}</div>` : ''}</div>
      <div class="hl-acts">${bad ? act(f, true) : ''}<button onClick=${onClose}>Close</button></div>
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
    <div class="hv-test"><b>Why no sound?</b><span>Play 4 seconds; golem shows where the sound stops. Changes nothing.</span>
      <button class=${cls('hv-btn p edit-only', running && 'busy')} disabled=${running} onClick=${run}>
        ${phase === 'listening' ? 'Play now…' : phase === 'reading' ? 'Reading…' : 'Start'}</button></div>
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
