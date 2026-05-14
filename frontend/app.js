/* Browserbase Web Agent — frontend application */

const TOOL_META = {
  browserbase_search:           { label: 'Search',   color: 'blue',  icon: '🔍' },
  browserbase_fetch:            { label: 'Read',     color: 'green', icon: '📄' },
  browserbase_rendered_extract: { label: 'Render',   color: 'amber', icon: '🖥️' },
  browserbase_interactive_task: { label: 'Interact', color: 'red',   icon: '🤖' },
};

const TOOL_COLORS = {
  blue:  'bg-blue-100 text-blue-700 border-blue-200',
  green: 'bg-green-100 text-green-700 border-green-200',
  amber: 'bg-amber-100 text-amber-700 border-amber-200',
  red:   'bg-red-100 text-red-700 border-red-200',
};

// Pool of example prompts — one per category is picked each session
const SUGGESTIONS = [
  // Search — web research & fact finding
  { category: 'Search', color: 'blue', icon: '🔍',
    text: 'What are the top Python web scraping libraries in 2026?' },
  { category: 'Search', color: 'blue', icon: '🔍',
    text: "What's new in the latest React release and should I upgrade?" },
  { category: 'Search', color: 'blue', icon: '🔍',
    text: 'Compare the leading AI agent frameworks available today' },

  // Read — fetch full page text
  { category: 'Read', color: 'green', icon: '📄',
    text: 'Summarise the LangChain documentation home page' },
  { category: 'Read', color: 'green', icon: '📄',
    text: 'What does the FastAPI docs say about dependency injection?' },
  { category: 'Read', color: 'green', icon: '📄',
    text: 'Read the Anthropic blog and tell me the latest post' },

  // Render — extract content from JS-heavy pages
  { category: 'Render', color: 'amber', icon: '🖥️',
    text: 'What is the current Browserbase pricing?' },
  { category: 'Render', color: 'amber', icon: '🖥️',
    text: 'List all features shown on the Vercel homepage' },
  { category: 'Render', color: 'amber', icon: '🖥️',
    text: 'What plans does Supabase offer and what are the limits?' },

  // Interact — click, navigate, fill forms
  { category: 'Interact', color: 'red', icon: '🤖',
    text: 'Find the latest LangGraph release notes on GitHub' },
  { category: 'Interact', color: 'red', icon: '🤖',
    text: 'Search Hacker News for "AI agents" and summarise the top thread' },
  { category: 'Interact', color: 'red', icon: '🤖',
    text: 'Go to the Python Package Index and find the most downloaded package this month' },
];

const BADGE_COLORS = {
  blue:  'bg-blue-100 text-blue-700',
  green: 'bg-green-100 text-green-700',
  amber: 'bg-amber-100 text-amber-700',
  red:   'bg-red-100 text-red-700',
};

const MAX_MSG_LEN = 10_000;

const App = (() => {
  let threadId        = 'session-' + Date.now();
  let msgCount        = 0;
  let busy            = false;
  let pendingApproval = null;
  let currentAgentEl  = null;
  let currentAgentText = '';
  let activeTools     = new Set();
  let currentAbort    = null;

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    marked.setOptions({ breaks: true, gfm: true });
    _syncThreadLabel();
    renderSuggestions();
    fetch('/api/health')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.model) {
          document.getElementById('model-label').textContent = data.model;
        }
      })
      .catch(() => {});
  }

  // ── Dynamic suggestion rendering ─────────────────────────────────────────
  function renderSuggestions() {
    const grid = document.getElementById('suggestions-grid');
    if (!grid) return;

    // Pick one from each category, randomised within each pool
    const categories = ['Search', 'Read', 'Render', 'Interact'];
    const picked = categories.map(cat => {
      const pool = SUGGESTIONS.filter(s => s.category === cat);
      return pool[Math.floor(Math.random() * pool.length)];
    });

    grid.innerHTML = picked.map(s => `
      <button
        data-prompt="${escapeHtml(s.text)}"
        onclick="App.suggest(this)"
        class="suggest-btn group text-left px-4 py-3.5 rounded-xl border border-slate-200 bg-white
               hover:border-brand-500 hover:bg-brand-50 hover:shadow-sm transition-all duration-150"
      >
        <span class="inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-0.5 rounded-full ${BADGE_COLORS[s.color]} mb-2">
          ${s.icon} ${s.category}
        </span>
        <p class="text-sm text-slate-600 group-hover:text-slate-800 leading-snug">${escapeHtml(s.text)}</p>
      </button>
    `).join('');
  }

  // ── New session ───────────────────────────────────────────────────────────
  function newSession() {
    if (currentAbort) { currentAbort.abort(); currentAbort = null; }
    threadId = 'session-' + Date.now();
    msgCount = 0;
    currentAgentEl   = null;
    currentAgentText = '';
    activeTools.clear();
    busy = false;

    document.getElementById('chat').innerHTML = '';
    document.getElementById('msg-count').textContent = '0';
    document.getElementById('tool-log').innerHTML = '';
    document.getElementById('send-btn').disabled = false;
    document.getElementById('input').disabled = false;
    _syncThreadLabel();

    document.getElementById('chat').appendChild(buildWelcome());
    renderSuggestions();
    setStatus('Ready');
  }

  function buildWelcome() {
    const d = document.createElement('div');
    d.id = 'welcome';
    d.className = 'flex flex-col items-center justify-center min-h-full text-center py-10 px-4';
    d.innerHTML = `
      <div class="w-16 h-16 rounded-2xl bg-brand-500 flex items-center justify-center text-white text-2xl font-bold mb-4 shadow-lg shadow-brand-500/20">BB</div>
      <h2 class="text-xl font-semibold text-slate-800 mb-1.5">Browserbase Web Agent</h2>
      <p class="text-slate-500 text-sm max-w-sm leading-relaxed">
        Powered by Browserbase + LangGraph. Ask me to research topics, read websites,
        extract data from JavaScript-heavy pages, or interact with web apps.
      </p>
      <div class="mt-7 grid grid-cols-2 sm:grid-cols-4 gap-3 w-full max-w-2xl">
        <div class="capability-card bg-blue-50 border border-blue-100">
          <span class="text-xl mb-1">🔍</span>
          <span class="text-xs font-semibold text-blue-700">Search</span>
          <span class="text-xs text-blue-500/80 leading-tight">Web research &amp;<br>fact finding</span>
        </div>
        <div class="capability-card bg-green-50 border border-green-100">
          <span class="text-xl mb-1">📄</span>
          <span class="text-xs font-semibold text-green-700">Read</span>
          <span class="text-xs text-green-500/80 leading-tight">Fetch any page's<br>full content</span>
        </div>
        <div class="capability-card bg-amber-50 border border-amber-100">
          <span class="text-xl mb-1">🖥️</span>
          <span class="text-xs font-semibold text-amber-700">Render</span>
          <span class="text-xs text-amber-500/80 leading-tight">Extract JS-rendered<br>site content</span>
        </div>
        <div class="capability-card bg-red-50 border border-red-100">
          <span class="text-xl mb-1">🤖</span>
          <span class="text-xs font-semibold text-red-700">Interact</span>
          <span class="text-xs text-red-500/80 leading-tight">Click, type &amp;<br>fill forms</span>
        </div>
      </div>
      <p class="mt-8 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Try asking</p>
      <div id="suggestions-grid" class="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl"></div>
    `;
    return d;
  }

  // ── Send ──────────────────────────────────────────────────────────────────
  async function send() {
    if (busy) return;
    const input = document.getElementById('input');
    const text  = input.value.trim();
    if (!text) return;
    if (text.length > MAX_MSG_LEN) {
      appendSystemMessage('Message too long (max 10,000 characters).');
      return;
    }

    hideWelcome();
    input.value = '';
    autoResize(input);
    appendUserMessage(text);
    setBusy(true);

    try {
      await streamRequest('/api/chat', { message: text, thread_id: threadId });
    } catch (err) {
      if (err.name !== 'AbortError') {
        appendSystemMessage('Connection error: ' + err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  // ── SSE stream ────────────────────────────────────────────────────────────
  async function streamRequest(url, body) {
    currentAgentEl   = null;
    currentAgentText = '';

    if (currentAbort) currentAbort.abort();
    currentAbort = new AbortController();

    const res = await fetch(url, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
      signal:  currentAbort.signal,
    });

    if (!res.ok) throw new Error(`Server error ${res.status}`);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { handleEvent(JSON.parse(line.slice(6))); } catch (_) {}
        }
      }
    }
  }

  // ── Event router ─────────────────────────────────────────────────────────
  function handleEvent(ev) {
    switch (ev.type) {
      case 'tool_start':        onToolStart(ev.tool);       break;
      case 'tool_end':          onToolEnd(ev.tool);         break;
      case 'token':             onToken(ev.content);        break;
      case 'approval_required': pendingApproval = ev; showApprovalModal(ev); break;
      case 'done':              onDone(ev.content);         break;
      case 'error':             appendSystemMessage('Agent error: ' + (ev.message || 'unknown')); break;
    }
  }

  // ── Tool events ───────────────────────────────────────────────────────────
  function onToolStart(tool) {
    activeTools.add(tool);
    const meta = TOOL_META[tool] || { label: tool, color: 'blue', icon: '⚙️' };

    // Sidebar entry — replace if already present
    const existing = document.getElementById('tool-entry-' + tool);
    if (existing) existing.remove();
    const entry = document.createElement('div');
    entry.id = 'tool-entry-' + tool;
    entry.className = 'flex items-center gap-2 py-1.5 px-2.5 rounded-lg bg-slate-800';
    entry.innerHTML =
      `<span class="tool-dot-${tool} animate-pulse w-1.5 h-1.5 rounded-full bg-${meta.color === 'amber' ? 'amber' : meta.color}-400 flex-shrink-0"></span>` +
      `<span class="text-slate-300">${meta.icon} ${escapeHtml(meta.label)}</span>`;
    document.getElementById('tool-log').prepend(entry);

    // Inline badge in agent bubble
    ensureAgentBubble();
    const badge = document.createElement('span');
    badge.className = `tool-badge inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border mr-1 mb-1 ${TOOL_COLORS[meta.color] || TOOL_COLORS.blue}`;
    badge.innerHTML = `${meta.icon} ${escapeHtml(meta.label)}`;
    currentAgentEl.querySelector('.tool-badges').appendChild(badge);

    setStatus(`Running ${meta.label}…`);
  }

  function onToolEnd(tool) {
    activeTools.delete(tool);
    const dot = document.querySelector('.tool-dot-' + tool);
    if (dot) {
      dot.classList.remove('animate-pulse');
      dot.className = 'w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0';
    }
    if (activeTools.size === 0) setStatus('Thinking…');
  }

  // ── Streaming tokens ──────────────────────────────────────────────────────
  function onToken(content) {
    ensureAgentBubble();
    currentAgentText += content;
    try {
      const html = DOMPurify.sanitize(marked.parse(currentAgentText));
      currentAgentEl.querySelector('.agent-body').innerHTML = html;
    } catch (_) {}
    scrollToBottom();
  }

  // ── Done ──────────────────────────────────────────────────────────────────
  function onDone(content) {
    if (content && !currentAgentText) {
      ensureAgentBubble();
      try {
        const html = DOMPurify.sanitize(marked.parse(content));
        currentAgentEl.querySelector('.agent-body').innerHTML = html;
      } catch (_) {
        currentAgentEl.querySelector('.agent-body').textContent = content;
      }
    }
    if (currentAgentEl) {
      const body = currentAgentEl.querySelector('.agent-body');
      if (body) body.classList.add('done');
    }
    currentAgentEl   = null;
    currentAgentText = '';
    setStatus('Ready');
    scrollToBottom();
    msgCount++;
    document.getElementById('msg-count').textContent = msgCount;
  }

  // ── Approval modal ────────────────────────────────────────────────────────
  function showApprovalModal(ev) {
    document.getElementById('modal-url').textContent  = ev.url  || '';
    document.getElementById('modal-task').textContent = ev.task || '';
    document.getElementById('modal-edit').value       = '';
    document.getElementById('approval-modal').classList.remove('hidden');
    document.getElementById('modal-edit').focus();
    setStatus('Waiting for approval…');
  }

  async function decide(decision) {
    document.getElementById('approval-modal').classList.add('hidden');
    if (!pendingApproval) return;

    const editVal = document.getElementById('modal-edit').value.trim();
    const body    = { decision, task: editVal || pendingApproval.task || '' };
    const tid     = pendingApproval.thread_id;
    pendingApproval = null;
    setBusy(true);

    try {
      await streamRequest(`/api/approve/${encodeURIComponent(tid)}`, body);
    } catch (err) {
      if (err.name !== 'AbortError') appendSystemMessage('Error resuming: ' + err.message);
    } finally {
      setBusy(false);
    }
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function hideWelcome() {
    const w = document.getElementById('welcome');
    if (w) w.remove();
  }

  function appendUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'flex justify-end';
    el.innerHTML =
      `<div class="max-w-xl bg-brand-600 text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed shadow-sm whitespace-pre-wrap break-words">${escapeHtml(text)}</div>`;
    document.getElementById('chat').appendChild(el);
    scrollToBottom();
    msgCount++;
    document.getElementById('msg-count').textContent = msgCount;
  }

  function ensureAgentBubble() {
    if (currentAgentEl) return;
    const el = document.createElement('div');
    el.className = 'flex items-start gap-3';
    el.innerHTML =
      `<div class="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center text-brand-600 font-bold text-xs flex-shrink-0 mt-1" aria-hidden="true">AI</div>` +
      `<div class="flex-1 min-w-0">` +
        `<div class="tool-badges flex flex-wrap mb-1.5"></div>` +
        `<div class="agent-body prose prose-sm max-w-none text-slate-800 bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm border border-slate-100 leading-relaxed"></div>` +
      `</div>`;
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
    document.getElementById('send-btn').disabled = val;
    document.getElementById('input').disabled    = val;
    if (val) setStatus('Thinking…');
  }

  function setStatus(text) {
    const dot = busy
      ? '<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>'
      : '<span class="w-1.5 h-1.5 rounded-full bg-green-400"></span>';
    document.getElementById('header-status').innerHTML = `${dot} ${escapeHtml(text)}`;
  }

  function _syncThreadLabel() {
    const short = threadId.replace('session-', '').slice(-8);
    document.getElementById('thread-id-label').textContent = threadId;
    const h = document.getElementById('header-thread');
    if (h) h.textContent = '#' + short;
  }

  function scrollToBottom() {
    const chat = document.getElementById('chat');
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function suggest(btn) {
    const text = btn.dataset.prompt || btn.textContent.trim();
    document.getElementById('input').value = text;
    autoResize(document.getElementById('input'));
    send();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  init();
  return { send, newSession, onKey, autoResize, suggest, decide };
})();
