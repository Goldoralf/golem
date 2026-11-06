// SPDX-License-Identifier: GPL-3.0-or-later
// Une confirmation DANS l'app, jamais la boîte du navigateur (2026-10-14 : « un modal in app, pas un panel
// system ») — la boîte système sort du format 1024×600, ne suit pas le thème et ne se tape pas au doigt.
//   const [ask, confirmEl] = useConfirm();
//   if (!await ask({ title, body, ok: 'Remove', danger: true })) return;
//   … et rendre ${confirmEl} dans la page.
//   `check: 'texte'` : une case à cocher, et OK ne s'ouvre qu'une fois cochée (un consentement EXPLICITE — avocat, 2026-10-20).
import { html, useState, useEffect } from './lib.js';

export function useConfirm() {
  const [req, setReq] = useState(null);                  // {title, body, ok, cancel, danger, resolve}
  const ask = opts => new Promise(resolve => setReq({ ...opts, resolve }));
  const done = v => { if (req) req.resolve(v); setReq(null); };
  return [ask, req ? html`<${ConfirmModal} req=${req} done=${done} />` : ''];
}

function ConfirmModal({ req, done }) {
  const [checked, setChecked] = useState(false);
  const can = !req.check || checked;
  useEffect(() => {
    const k = e => { if (e.key === 'Escape') done(false); else if (e.key === 'Enter' && can) done(true); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [req, can]);
  return html`<div class="detail cfm-scrim" onClick=${e => e.target.classList.contains('cfm-scrim') && done(false)}>
    <div class="detail-card cfm-card" role="alertdialog" aria-modal="true">
      <h3>${req.title}</h3>
      ${(Array.isArray(req.body) ? req.body : [req.body]).filter(Boolean).map(p => html`<p class="muted">${p}</p>`)}
      ${req.check ? html`<label class="cfm-check"><input type="checkbox" checked=${checked} onChange=${e => setChecked(e.target.checked)} />
        <span>${req.check}</span></label>` : ''}
      <div class="cfm-nav"><button class="chip" onClick=${() => done(false)}>${req.cancel || 'Cancel'}</button>
        <button class=${req.danger ? 'primary cfm-danger' : 'primary'} disabled=${!can} onClick=${() => can && done(true)}>${req.ok || 'OK'}</button></div>
    </div>
  </div>`;
}
