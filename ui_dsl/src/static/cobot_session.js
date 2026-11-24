/*
 * Sessioni cobot lato UI.
 *
 * Il servizio cobot accetta comandi solo dalla sessione in testa alla coda
 * (POST /api/sessions). Questo modulo apre la sessione al primo comando,
 * aspetta il proprio turno, aggiunge X-Session-Id alle richieste e la rilascia
 * quando serve (o dopo l'inattività, lato server).
 *
 *   await CobotSession.fetch('api/motion/move-home', {method: 'POST', ...})
 *   await CobotSession.ensure()      // solo apertura/attesa del turno
 *   CobotSession.headers()           // {'X-Session-Id': ...}
 *   await CobotSession.release()
 */
(function () {
  const PROXY = '/cobot-proxy';
  const ID_KEY = 'cobotSessionId';
  const CLIENT_KEY = 'cobotClientId';
  const POLL_MS = 1000;
  const MAX_WAIT_MS = 15 * 60 * 1000;
  const DEAD_STATES = new Set(['failed', 'closed', 'expired', 'cancelled']);

  const NEEDS_SESSION = [
    /^api\/motion[a-z-]*\//,
    /^api\/gripper\/(home|open|close|grasp|release|reconnect)$/,
    /^api\/robot\/collision-behavior$/,
  ];

  function randomId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
    return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
  }

  let clientId = sessionStorage.getItem(CLIENT_KEY);
  if (!clientId) { clientId = randomId(); sessionStorage.setItem(CLIENT_KEY, clientId); }
  let sessionId = sessionStorage.getItem(ID_KEY);
  let pending = null;
  let badge = null;
  let abortWait = false;

  function setId(id) {
    sessionId = id;
    if (id) sessionStorage.setItem(ID_KEY, id); else sessionStorage.removeItem(ID_KEY);
  }

  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

  function showState(kind, text) {
    if (!badge) return;
    badge.dataset.kind = kind;
    badge.querySelector('.cs-text').textContent = text;
    badge.querySelector('button').hidden = kind === 'none';
  }

  function buildBadge() {
    const style = document.createElement('style');
    style.textContent = `
      #cobot-session-badge{position:fixed;right:14px;bottom:14px;z-index:9999;display:flex;gap:8px;align-items:center;
        padding:7px 12px;border-radius:999px;font:12px/1.2 system-ui,sans-serif;background:#1f2933;color:#fff;
        box-shadow:0 2px 10px rgba(0,0,0,.25);opacity:.92}
      #cobot-session-badge[data-kind=active]{background:#1b7f3b}
      #cobot-session-badge[data-kind=waiting]{background:#b36b00}
      #cobot-session-badge[data-kind=error]{background:#b3261e}
      #cobot-session-badge button{border:0;border-radius:999px;padding:3px 9px;font:inherit;cursor:pointer;
        background:rgba(255,255,255,.22);color:inherit}`;
    document.head.appendChild(style);
    badge = document.createElement('div');
    badge.id = 'cobot-session-badge';
    badge.innerHTML = '<span class="cs-text"></span><button type="button" title="Rilascia il turno sul robot">Rilascia</button>';
    badge.querySelector('button').addEventListener('click', () => CobotSession.release());
    document.body.appendChild(badge);
    showState(sessionId ? 'idle' : 'none', sessionId ? 'Sessione cobot aperta' : 'Nessuna sessione cobot');
  }

  async function call(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await window.fetch(`${PROXY}/${path}`, options);
    const data = await response.json().catch(() => ({}));
    return { status: response.status, ok: response.ok, data };
  }

  async function open() {
    const { status, data } = await call('POST', 'api/sessions', { client_id: clientId });
    if (status !== 201 && status !== 202) {
      throw new Error(data.error || data.message || `Impossibile aprire la sessione cobot (HTTP ${status})`);
    }
    setId(data.session_id);
    return data;
  }

  async function waitForTurn(session) {
    const started = Date.now();
    abortWait = false;
    while (session.state !== 'active') {
      if (abortWait) throw new Error('Attesa del turno annullata');
      if (DEAD_STATES.has(session.state)) throw new Error(`Sessione cobot ${session.state}`);
      if (Date.now() - started > MAX_WAIT_MS) throw new Error('Timeout in attesa del turno sul robot');
      showState('waiting', `In coda: posizione ${session.position ?? '?'}`);
      await sleep(POLL_MS);
      const poll = await call('GET', `api/sessions/${sessionId}`);
      if (poll.status === 404) throw new Error('Sessione cobot sconosciuta');
      session = poll.data;
    }
    return session;
  }

  async function doEnsure() {
    let session = null;
    if (sessionId) {
      const check = await call('GET', `api/sessions/${sessionId}`);
      if (check.ok && !DEAD_STATES.has(check.data.state)) {
        session = check.data;
      } else {
        // sessione scaduta o fallita: libera il turno e ne apre una nuova
        if (check.ok) await call('DELETE', `api/sessions/${sessionId}`);
        setId(null);
      }
    }
    if (!session) session = await open();
    try {
      await waitForTurn(session);
    } catch (error) {
      showState('error', error.message);
      throw error;
    }
    showState('active', 'Sessione cobot attiva');
    return sessionId;
  }

  function needsSession(method, path) {
    return method !== 'GET' && NEEDS_SESSION.some(re => re.test(path));
  }

  const CobotSession = {
    clientId: () => clientId,
    id: () => sessionId,
    headers: () => (sessionId ? { 'X-Session-Id': sessionId } : {}),

    ensure() {
      if (!pending) pending = doEnsure().finally(() => { pending = null; });
      return pending;
    },

    // fetch verso /cobot-proxy: apre la sessione quando il comando la richiede
    async fetch(path, options = {}) {
      const method = (options.method || 'GET').toUpperCase();
      const url = `${PROXY}/${path}`;
      if (!needsSession(method, path)) return window.fetch(url, options);
      await CobotSession.ensure();
      const withSession = () => window.fetch(url, {
        ...options,
        headers: { ...(options.headers || {}), ...CobotSession.headers() },
      });
      let response = await withSession();
      if (response.status === 409 || response.status === 404) {
        const data = await response.clone().json().catch(() => ({}));
        if (data.state && DEAD_STATES.has(data.state) || data.error === 'sessione sconosciuta') {
          setId(null);
          await CobotSession.ensure();
          response = await withSession();
        }
      }
      return response;
    },

    async release() {
      abortWait = true;
      const id = sessionId;
      setId(null);
      if (id) await call('DELETE', `api/sessions/${id}`).catch(() => {});
      showState('none', 'Nessuna sessione cobot');
    },
  };

  window.addEventListener('pagehide', () => {
    if (sessionId) {
      window.fetch(`${PROXY}/api/sessions/${sessionId}`, { method: 'DELETE', keepalive: true }).catch(() => {});
    }
  });

  window.CobotSession = CobotSession;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', buildBadge);
  else buildBadge();
})();
