/* Browserbase Web Agent — frontend application */

const TOOL_META = {
  browserbase_search:           { label: 'Search',    color: 'blue',   icon: '🔍' },
  browserbase_fetch:            { label: 'Fetch',     color: 'green',  icon: '📄' },
  browserbase_rendered_extract: { label: 'Render',    color: 'amber',  icon: '🖥️' },
  browserbase_interactive_task: { label: 'Interact',  color: 'red',    icon: '🤖' },
};

const TOOL_COLORS = {
  blue:  'bg-blue-100 text-blue-700 border-blue-200',
  green: 'bg-green-100 text-green-700 border-green-200',
  amber: 'bg-amber-100 text-amber-700 border-amber-200',
  red:   'bg-red-100 text-red-700 border-red-200',
};

const App = (() => {
  let threadId    = 'default';
  let msgCount    = 0;
  let busy        = false;
  let pendingApproval = null;    // { thread_id, url, task }
  let currentAgentEl = null;    // current streaming agent bubble
  let currentAgentText = '';    // accumulated markdown text
  let activeTools = new Set();

  // ── Initialise ────────────────────────────────────────────────────────────
  function init() {
    marked.setOptions({ breaks: true, gfm: true });
    document.getElementById('model-label').textContent =
      document.title.includes('gpt') ? 'gpt-4o' : 'gpt-4o';
    document.getElementById('thread-id-label').textContent = threadId;
  }

  // ── New session ───────────────────────────────────────────────────────────
  function newSession() {
    threadId = 'session-' + Date.now();
    msgCount = 0;
    currentAgentEl = null;
    currentAgentText = '';
    activeTools.clear();
    document.getElementById('chat').innerHTML = '';
    document.getElementById('msg-count').textContent = '0';
    document.getElementById('thread-id-label').textContent = threadId;
    document.getElementById('tool-log').innerHTML = '';
    document.getElementById('welcome').style.display = '';
    document.getElementById('chat').appendChild(document.getElementById('welcome'));
    document.getElementById('welcome').classList.remove('hidden');
  }

  // ── Send message ──────────────────────────────────────────────────────────
  async function send() {
    if (busy) return;
    const input = document.getElementById('input');
    const text  = input.value.trim();
    if (!text) return;

    hideWelcome();
    input.value = '';
    autoResize(input);
    appendUserMessage(text);
    setBusy(true);

    try {
      await streamRequest('/api/chat', { message: text, thread_id: threadId });
    } catch (err) {
      appendSystemMessage('Connection error: ' + err.message);
    } finally {
      setBusy(false);
    }
  }

  // ── Stream a request, parse SSE ───────────────────────────────────────────
  async function streamRequest(url, body) {
    currentAgentEl   = null;
    currentAgentText = '';

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            handleEvent(JSON.parse(line.slice(6)));
          } catch (_) {}
        }
      }
    }
  }

  // ── Handle a single SSE event ─────────────────────────────────────────────
  function handleEvent(ev) {
    switch (ev.type) {
      case 'tool_start':
        onToolStart(ev.tool, ev.input);
        break;

      case 'tool_end':
        onToolEnd(ev.tool);
        break;

      case 'token':
        onToken(ev.content);
        break;

      case 'approval_required':
        pendingApproval = ev;
        showApprovalModal(ev);
        break;

      case 'done':
        onDone(ev.content);
        break;

      case 'error':
        appendSystemMessage('Agent error: ' + ev.message);
        break;
    }
  }

  // ── Tool events ───────────────────────────────────────────────────────────
  function onToolStart(tool, input) {
    activeTools.add(tool);
    const meta = TOOL_META[tool] || { label: tool, color: 'blue', icon: '⚙️' };

    // Sidebar log entry
    const entry = document.createElement('div');
    entry.id = 'tool-' + tool;
    entry.className = `flex items-center gap-2 py-1.5 px-2 rounded-lg bg-slate-800`;
    entry.innerHTML = `
      <span class="animate-pulse w-1.5 h-1.5 rounded-full bg-${meta.color === 'amber' ? 'amber' : meta.color}-400"></span>
      <span class="text-slate-300">${meta.icon} ${meta.label}</span>
    `;
    document.getElementById('tool-log').prepend(entry);

    // Inline badge in chat
    ensureAgentBubble();
    const badge = document.createElement('span');
    badge.className = `tool-badge inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border mr-1 mb-1 ${TOOL_COLORS[meta.color] || TOOL_COLORS.blue}`;
    badge.textContent = `${meta.icon} ${meta.label}`;
    currentAgentEl.querySelector('.tool-badges').appendChild(badge);

    setStatus(`Running ${meta.label}…`);
  }

  function onToolEnd(tool) {
    activeTools.delete(tool);
    const entry = document.getElementById('tool-' + tool);
    if (entry) {
      entry.querySelector('span:first-child').className = 'w-1.5 h-1.5 rounded-full bg-green-400';
    }
    if (activeTools.size === 0) setStatus('Thinking…');
  }

  // ── Streaming tokens ──────────────────────────────────────────────────────
  function onToken(content) {
    ensureAgentBubble();
    currentAgentText += content;
    currentAgentEl.querySelector('.agent-body').innerHTML =
      marked.parse(currentAgentText);
    scrollToBottom();
  }

  // ── Done ──────────────────────────────────────────────────────────────────
  function onDone(content) {
    if (content && !currentAgentText) {
      ensureAgentBubble();
      currentAgentText = content;
      currentAgentEl.querySelector('.agent-body').innerHTML =
        marked.parse(content);
    }
    currentAgentEl  = null;
    currentAgentText = '';
    setStatus('Ready');
    scrollToBottom();
    msgCount++;
    document.getElementById('msg-count').textContent = msgCount;
  }

  // ── Approval modal ────────────────────────────────────────────────────────
  function showApprovalModal(ev) {
    document.getElementById('modal-url').textContent  = ev.url   || '';
    document.getElementById('modal-task').textContent = ev.task  || '';
    document.getElementById('modal-edit').value       = '';
    document.getElementById('approval-modal').classList.remove('hidden');
    setStatus('Waiting for approval…');
  }

  async function decide(decision) {
    document.getElementById('approval-modal').classList.add('hidden');
    if (!pendingApproval) return;

    const editVal = document.getElementById('modal-edit').value.trim();
    const body = {
      decision,
      task: editVal || pendingApproval.task || '',
    };

    const tid = pendingApproval.thread_id;
    pendingApproval = null;
    setBusy(true);

    try {
      await streamRequest(`/api/approve/${tid}`, body);
    } catch (err) {
      appendSystemMessage('Error resuming: ' + err.message);
    } finally {
      setBusy(false);
    }
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function hideWelcome() {
    const w = document.getElementById('welcome');
    if (w) w.style.display = 'none';
  }

  function appendUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'flex justify-end';
    el.innerHTML = `
      <div class="max-w-xl bg-brand-600 text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed shadow-sm">
        ${escapeHtml(text)}
      </div>
    `;
    document.getElementById('chat').appendChild(el);
    scrollToBottom();
    msgCount++;
    document.getElementById('msg-count').textContent = msgCount;
  }

  function ensureAgentBubble() {
    if (currentAgentEl) return;
    const el = document.createElement('div');
    el.className = 'flex items-start gap-3';
    el.innerHTML = `
      <div class="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center text-brand-600 font-bold text-xs flex-shrink-0 mt-1">AI</div>
      <div class="flex-1 min-w-0">
        <div class="tool-badges flex flex-wrap mb-2"></div>
        <div class="agent-body prose prose-sm max-w-none text-slate-800 bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm border border-slate-100 leading-relaxed"></div>
      </div>
    `;
    document.getElementById('chat').appendChild(el);
    currentAgentEl = el;
    scrollToBottom();
  }

  function appendSystemMessage(text) {
    const el = document.createElement('div');
    el.className = 'flex justify-center';
    el.innerHTML = `<p class="text-xs text-red-500 bg-red-50 border border-red-200 px-3 py-1.5 rounded-full">${escapeHtml(text)}</p>`;
    document.getElementById('chat').appendChild(el);
    scrollToBottom();
  }

  function setBusy(val) {
    busy = val;
    const btn = document.getElementById('send-btn');
    const inp = document.getElementById('input');
    btn.disabled = val;
    inp.disabled = val;
    if (val) setStatus('Thinking…');
  }

  function setStatus(text) {
    document.getElementById('header-status').innerHTML = `
      <span class="w-1.5 h-1.5 rounded-full ${busy ? 'bg-amber-400 animate-pulse' : 'bg-green-400'}"></span>
      ${escapeHtml(text)}
    `;
  }

  function scrollToBottom() {
    const chat = document.getElementById('chat');
    chat.scrollTop = chat.scrollHeight;
  }

  // ── Input helpers ─────────────────────────────────────────────────────────
  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function suggest(btn) {
    document.getElementById('input').value = btn.textContent.trim().replace(/^[^ ]+ /, '');
    send();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  init();
  return { send, newSession, onKey, autoResize, suggest, decide };
})();
