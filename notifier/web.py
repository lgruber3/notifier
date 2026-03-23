import asyncio
import json
import logging
import signal
from collections import deque
from pathlib import Path

import httpx
import yaml
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from .config import (
    AppConfig, ChannelConfig, KeywordRule, NtfyConfig, WebConfig,
    load_config, save_config, _parse_keywords,
)

logger = logging.getLogger(__name__)

# Ring buffer for recent log entries shown in the web UI
log_buffer: deque[dict] = deque(maxlen=200)

CONFIG_PATH = Path("config.yaml")

# Callback set by main.py to reload config without full restart
_reload_callback = None


def set_reload_callback(cb):
    global _reload_callback
    _reload_callback = cb


class WebLogHandler(logging.Handler):
    def emit(self, record):
        log_buffer.append({
            "time": self.format(record).split("]")[0].lstrip("[") if "]" in self.format(record) else record.asctime,
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        })


def _read_raw_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _config_to_json(raw: dict) -> dict:
    """Convert raw YAML dict to a JSON-friendly format for the frontend."""
    return {
        "ntfy": raw.get("ntfy", {}),
        "notify_on_first_run": raw.get("notify_on_first_run", False),
        "keywords": raw.get("keywords", []),
        "logging": raw.get("logging", {}),
        "web": raw.get("web", {}),
        "channels": raw.get("channels", []),
    }


async def index(request):
    return HTMLResponse(HTML_PAGE)


async def api_config_get(request):
    raw = _read_raw_config()
    return JSONResponse(_config_to_json(raw))


async def api_config_save(request):
    body = await request.json()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(body, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        # Hot-reload: re-read config and rebuild scheduler
        if _reload_callback:
            await _reload_callback()
            return JSONResponse({"ok": True, "message": "Config saved and applied!"})
        return JSONResponse({"ok": True, "message": "Config saved. Restart to apply."})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)


async def healthz(request):
    return PlainTextResponse("ok")


async def api_test_notification(request):
    body = await request.json()
    server = body.get("server", "https://ntfy.sh")
    topic = body.get("topic", "")
    if not topic:
        return JSONResponse({"ok": False, "message": "No topic set"}, status_code=400)

    url = f"{server.rstrip('/')}/{topic}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url,
                content=b"This is a test from your notifier. If you see this, notifications work!",
                headers={"Title": "Notifier Test", "Priority": "3", "Tags": "white_check_mark,test"})
            resp.raise_for_status()
        return JSONResponse({"ok": True, "message": "Test notification sent!"})
    except Exception as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=500)


async def api_logs(request):
    return JSONResponse(list(log_buffer))


def create_app() -> Starlette:
    handler = WebLogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)

    return Starlette(
        routes=[
            Route("/", index),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/api/config", api_config_get, methods=["GET"]),
            Route("/api/config", api_config_save, methods=["POST"]),
            Route("/api/test", api_test_notification, methods=["POST"]),
            Route("/api/logs", api_logs, methods=["GET"]),
        ],
    )


# ---------------------------------------------------------------------------
# Embedded single-page HTML
# ---------------------------------------------------------------------------
HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Notifier Config</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a; --text: #e4e4e7;
    --muted: #888; --accent: #6366f1; --accent-hover: #818cf8;
    --danger: #ef4444; --success: #22c55e; --warn: #f59e0b;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.5; }
  .container { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 8px; }
  h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 12px; color: var(--muted); }
  .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 24px; }

  /* Tabs */
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 0; }
  .tab { padding: 8px 16px; border: none; background: none; color: var(--muted); cursor: pointer;
         font-size: 0.9rem; border-bottom: 2px solid transparent; transition: all 0.15s; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }

  .panel { display: none; }
  .panel.active { display: block; }

  /* Cards */
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
          padding: 16px; margin-bottom: 16px; }

  /* Form elements */
  label { display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 4px; font-weight: 500; }
  input, select { width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px;
                  background: var(--bg); color: var(--text); font-size: 0.9rem; outline: none; }
  input:focus, select:focus { border-color: var(--accent); }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .row-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .field { margin-bottom: 12px; }

  /* Buttons */
  .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
         font-weight: 500; transition: background 0.15s; }
  .btn-primary { background: var(--accent); color: white; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-danger { background: var(--danger); color: white; }
  .btn-danger:hover { opacity: 0.9; }
  .btn-outline { background: none; border: 1px solid var(--border); color: var(--text); }
  .btn-outline:hover { border-color: var(--muted); }
  .btn-sm { padding: 4px 10px; font-size: 0.8rem; }

  .actions { display: flex; gap: 8px; margin-top: 16px; }
  .actions-right { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }

  /* Tags / keyword chips */
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: var(--bg);
          border: 1px solid var(--border); border-radius: 16px; font-size: 0.8rem; }
  .chip.regex { border-color: var(--warn); color: var(--warn); }
  .chip button { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 0.9rem; padding: 0 2px; }
  .chip button:hover { color: var(--danger); }

  /* Channel type badge */
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;
           font-weight: 600; text-transform: uppercase; }
  .badge-rss { background: #1e3a5f; color: #60a5fa; }
  .badge-reddit { background: #3b1f0b; color: #fb923c; }

  /* Channel header */
  .ch-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .ch-header h3 { font-size: 1rem; display: flex; align-items: center; gap: 8px; }

  /* Logs */
  .log-box { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
             padding: 12px; max-height: 500px; overflow-y: auto; font-family: 'SF Mono', Consolas, monospace;
             font-size: 0.78rem; line-height: 1.6; }
  .log-line { white-space: pre-wrap; word-break: break-all; }
  .log-line .lvl-ERROR { color: var(--danger); }
  .log-line .lvl-WARNING { color: var(--warn); }
  .log-line .lvl-INFO { color: var(--success); }
  .log-line .lvl-DEBUG { color: var(--muted); }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 8px;
           font-size: 0.85rem; z-index: 999; opacity: 0; transition: opacity 0.2s; pointer-events: none; }
  .toast.show { opacity: 1; }
  .toast.ok { background: #166534; color: white; }
  .toast.err { background: #991b1b; color: white; }

  /* Keyword inherit note */
  .inherit-note { font-size: 0.78rem; color: var(--muted); font-style: italic; margin-bottom: 8px; }

  .empty-state { text-align: center; padding: 32px; color: var(--muted); }
</style>
</head>
<body>
<div class="container">
  <h1>Notifier</h1>
  <p class="subtitle">Keyword monitoring &amp; push notifications</p>

  <div class="tabs">
    <button class="tab active" data-tab="general">General</button>
    <button class="tab" data-tab="keywords">Keywords</button>
    <button class="tab" data-tab="channels">Channels</button>
    <button class="tab" data-tab="logs">Logs</button>
  </div>

  <!-- GENERAL -->
  <div class="panel active" id="tab-general">
    <div class="card">
      <h2>ntfy.sh Settings</h2>
      <div class="row">
        <div class="field">
          <label>Server</label>
          <input id="ntfy-server" placeholder="https://ntfy.sh">
        </div>
        <div class="field">
          <label>Topic</label>
          <input id="ntfy-topic" placeholder="my-secret-topic">
        </div>
      </div>
      <div class="row">
        <div class="field">
          <label>Default Priority (1-5)</label>
          <select id="ntfy-priority">
            <option value="1">1 - Min</option>
            <option value="2">2 - Low</option>
            <option value="3" selected>3 - Default</option>
            <option value="4">4 - High</option>
            <option value="5">5 - Urgent</option>
          </select>
        </div>
        <div class="field" style="display:flex;align-items:flex-end;">
          <button class="btn btn-outline" onclick="testNotification()">Send Test Notification</button>
        </div>
      </div>
    </div>
    <div class="card">
      <h2>General</h2>
      <div class="row">
        <div class="field">
          <label>Log Level</label>
          <select id="log-level">
            <option>DEBUG</option><option selected>INFO</option><option>WARNING</option><option>ERROR</option>
          </select>
        </div>
        <div class="field">
          <label>Notify on First Run</label>
          <select id="first-run">
            <option value="false" selected>No (skip existing items)</option>
            <option value="true">Yes (send all matches)</option>
          </select>
        </div>
      </div>
    </div>
  </div>

  <!-- KEYWORDS -->
  <div class="panel" id="tab-keywords">
    <div class="card">
      <h2>Global Keywords</h2>
      <p class="inherit-note">Applied to all channels unless the channel overrides them</p>
      <div class="chips" id="global-keywords"></div>
      <div class="row">
        <div class="field">
          <input id="new-keyword" placeholder="Add keyword..." onkeydown="if(event.key==='Enter')addGlobalKeyword()">
        </div>
        <div style="display:flex;gap:8px;align-items:flex-end;">
          <label style="display:flex;align-items:center;gap:4px;margin-bottom:8px;cursor:pointer;">
            <input type="checkbox" id="new-kw-regex"> Regex
          </label>
          <button class="btn btn-outline btn-sm" style="margin-bottom:4px;" onclick="addGlobalKeyword()">Add</button>
        </div>
      </div>
    </div>
  </div>

  <!-- CHANNELS -->
  <div class="panel" id="tab-channels">
    <div id="channels-list"></div>
    <div class="actions">
      <button class="btn btn-outline" onclick="addChannel('rss')">+ RSS Feed</button>
      <button class="btn btn-outline" onclick="addChannel('reddit')">+ Reddit</button>
    </div>
  </div>

  <!-- LOGS -->
  <div class="panel" id="tab-logs">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h2 style="margin:0;">Live Logs</h2>
        <button class="btn btn-outline btn-sm" onclick="fetchLogs()">Refresh</button>
      </div>
      <div class="log-box" id="log-box">
        <div class="empty-state">Loading logs...</div>
      </div>
    </div>
  </div>

  <!-- Save bar -->
  <div class="actions" style="margin-top:24px;">
    <button class="btn btn-primary" onclick="saveConfig()">Save Config</button>
    <span class="subtitle" style="margin:0;align-self:center;">Changes apply immediately after saving</span>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let config = {};

// --- Tabs ---
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById('tab-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'logs') fetchLogs();
  });
});

// --- Toast ---
function toast(msg, ok = true) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => el.className = 'toast', 3000);
}

// --- Load config ---
async function loadConfig() {
  const resp = await fetch('/api/config');
  config = await resp.json();
  renderAll();
}

function renderAll() {
  // General
  document.getElementById('ntfy-server').value = config.ntfy?.server || 'https://ntfy.sh';
  document.getElementById('ntfy-topic').value = config.ntfy?.topic || '';
  document.getElementById('ntfy-priority').value = config.ntfy?.default_priority || 3;
  document.getElementById('log-level').value = config.logging?.level || 'INFO';
  document.getElementById('first-run').value = config.notify_on_first_run ? 'true' : 'false';

  // Keywords
  renderGlobalKeywords();

  // Channels
  renderChannels();
}

// --- Keywords ---
function renderGlobalKeywords() {
  const el = document.getElementById('global-keywords');
  el.innerHTML = '';
  (config.keywords || []).forEach((kw, i) => {
    const isObj = typeof kw === 'object';
    const text = isObj ? kw.pattern : kw;
    const isRegex = isObj && kw.regex;
    const chip = document.createElement('span');
    chip.className = 'chip' + (isRegex ? ' regex' : '');
    chip.innerHTML = (isRegex ? '<small>regex:</small> ' : '') + escHtml(text) +
      ' <button onclick="removeGlobalKeyword(' + i + ')">&times;</button>';
    el.appendChild(chip);
  });
}

function addGlobalKeyword() {
  const input = document.getElementById('new-keyword');
  const isRegex = document.getElementById('new-kw-regex').checked;
  const val = input.value.trim();
  if (!val) return;
  if (!config.keywords) config.keywords = [];
  config.keywords.push(isRegex ? { pattern: val, regex: true } : val);
  input.value = '';
  document.getElementById('new-kw-regex').checked = false;
  renderGlobalKeywords();
}

function removeGlobalKeyword(i) {
  config.keywords.splice(i, 1);
  renderGlobalKeywords();
}

// --- Channels ---
function renderChannels() {
  const el = document.getElementById('channels-list');
  if (!config.channels || config.channels.length === 0) {
    el.innerHTML = '<div class="empty-state">No channels configured. Add one below.</div>';
    return;
  }
  el.innerHTML = '';
  config.channels.forEach((ch, i) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = renderChannelCard(ch, i);
    el.appendChild(card);
  });
}

function renderChannelCard(ch, i) {
  const badgeClass = ch.type === 'reddit' ? 'badge-reddit' : 'badge-rss';
  let fields = '';

  if (ch.type === 'reddit') {
    fields = `
      <div class="row">
        <div class="field">
          <label>Subreddits (comma-separated)</label>
          <input value="${escAttr((ch.subreddits||[]).join(', '))}" onchange="updateChannelField(${i},'subreddits',this.value)">
        </div>
        <div class="field">
          <label>Sort</label>
          <select onchange="updateChannelField(${i},'sort',this.value)">
            <option${ch.sort==='new'?' selected':''}>new</option>
            <option${ch.sort==='hot'?' selected':''}>hot</option>
            <option${ch.sort==='rising'?' selected':''}>rising</option>
          </select>
        </div>
      </div>`;
  } else if (ch.type === 'rss') {
    fields = `
      <div class="field">
        <label>Feed URLs (one per line)</label>
        <textarea style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:0.85rem;min-height:60px;resize:vertical;font-family:monospace;" onchange="updateChannelField(${i},'feeds',this.value)">${escHtml((ch.feeds||[]).join('\\n'))}</textarea>
      </div>`;
  }

  // Channel keywords
  const hasOwnKw = ch.hasOwnProperty('keywords');
  const kwChips = hasOwnKw && Array.isArray(ch.keywords)
    ? ch.keywords.map((kw, ki) => {
        const isObj = typeof kw === 'object';
        const text = isObj ? kw.pattern : kw;
        const isRegex = isObj && kw.regex;
        return `<span class="chip${isRegex?' regex':''}">` +
          (isRegex ? '<small>regex:</small> ' : '') + escHtml(text) +
          ` <button onclick="removeChannelKeyword(${i},${ki})">&times;</button></span>`;
      }).join('')
    : '';

  const kwSection = `
    <div style="margin-top:8px;">
      <label>Keywords</label>
      <select onchange="setChannelKeywordMode(${i},this.value)" style="margin-bottom:8px;width:auto;">
        <option value="inherit"${!hasOwnKw?' selected':''}>Inherit global</option>
        <option value="all"${hasOwnKw&&ch.keywords&&ch.keywords.length===0?' selected':''}>Match all (no filter)</option>
        <option value="custom"${hasOwnKw&&ch.keywords&&ch.keywords.length>0?' selected':''}>Custom keywords</option>
      </select>
      ${hasOwnKw && Array.isArray(ch.keywords) ? '<div class="chips">' + kwChips + '</div>' : ''}
      ${hasOwnKw && ch.keywords && ch.keywords.length >= 0 ? `
        <div style="display:flex;gap:8px;align-items:center;">
          <input placeholder="Add keyword..." id="ch-kw-${i}" onkeydown="if(event.key==='Enter')addChannelKeyword(${i})" style="flex:1;">
          <button class="btn btn-outline btn-sm" onclick="addChannelKeyword(${i})">Add</button>
        </div>` : ''}
    </div>`;

  return `
    <div class="ch-header">
      <h3><span class="badge ${badgeClass}">${ch.type}</span> ${escHtml(ch.name)}</h3>
      <button class="btn btn-danger btn-sm" onclick="removeChannel(${i})">Remove</button>
    </div>
    <div class="row-3">
      <div class="field">
        <label>Name</label>
        <input value="${escAttr(ch.name)}" onchange="config.channels[${i}].name=this.value">
      </div>
      <div class="field">
        <label>Poll Interval (seconds)</label>
        <input type="number" value="${ch.poll_interval||600}" onchange="config.channels[${i}].poll_interval=+this.value">
      </div>
      <div class="field">
        <label>Priority (blank=default)</label>
        <input type="number" min="1" max="5" value="${ch.priority||''}" placeholder="inherit"
               onchange="config.channels[${i}].priority=this.value?+this.value:undefined">
      </div>
    </div>
    ${fields}
    ${kwSection}`;
}

function updateChannelField(i, field, value) {
  if (field === 'subreddits') {
    config.channels[i].subreddits = value.split(',').map(s => s.trim()).filter(Boolean);
  } else if (field === 'feeds') {
    config.channels[i].feeds = value.split('\\n').map(s => s.trim()).filter(Boolean);
  } else {
    config.channels[i][field] = value;
  }
}

function setChannelKeywordMode(i, mode) {
  if (mode === 'inherit') {
    delete config.channels[i].keywords;
  } else if (mode === 'all') {
    config.channels[i].keywords = [];
  } else {
    if (!Array.isArray(config.channels[i].keywords)) config.channels[i].keywords = [];
  }
  renderChannels();
}

function addChannelKeyword(i) {
  const input = document.getElementById('ch-kw-' + i);
  const val = input.value.trim();
  if (!val) return;
  if (!Array.isArray(config.channels[i].keywords)) config.channels[i].keywords = [];
  config.channels[i].keywords.push(val);
  renderChannels();
}

function removeChannelKeyword(ci, ki) {
  config.channels[ci].keywords.splice(ki, 1);
  renderChannels();
}

function addChannel(type) {
  if (!config.channels) config.channels = [];
  const ch = { name: '', type, poll_interval: 600 };
  if (type === 'reddit') { ch.subreddits = []; ch.sort = 'new'; ch.name = 'New Reddit Channel'; }
  if (type === 'rss') { ch.feeds = []; ch.name = 'New RSS Feed'; }
  config.channels.push(ch);
  renderChannels();
  // Scroll to new channel
  const list = document.getElementById('channels-list');
  list.lastElementChild?.scrollIntoView({ behavior: 'smooth' });
}

function removeChannel(i) {
  config.channels.splice(i, 1);
  renderChannels();
}

// --- Save ---
async function saveConfig() {
  // Gather current form values into config
  config.ntfy = {
    server: document.getElementById('ntfy-server').value,
    topic: document.getElementById('ntfy-topic').value,
    default_priority: +document.getElementById('ntfy-priority').value,
  };
  config.logging = { level: document.getElementById('log-level').value };
  config.notify_on_first_run = document.getElementById('first-run').value === 'true';

  const resp = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  const data = await resp.json();
  toast(data.message, data.ok);
}

// --- Test ---
async function testNotification() {
  const server = document.getElementById('ntfy-server').value;
  const topic = document.getElementById('ntfy-topic').value;
  const resp = await fetch('/api/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server, topic }),
  });
  const data = await resp.json();
  toast(data.message, data.ok);
}

// --- Logs ---
async function fetchLogs() {
  const resp = await fetch('/api/logs');
  const logs = await resp.json();
  const box = document.getElementById('log-box');
  if (logs.length === 0) {
    box.innerHTML = '<div class="empty-state">No logs yet</div>';
    return;
  }
  box.innerHTML = logs.map(l =>
    `<div class="log-line"><span class="lvl-${l.level}">[${l.level}]</span> ${escHtml(l.name)}: ${escHtml(l.message)}</div>`
  ).join('');
  box.scrollTop = box.scrollHeight;
}

// --- Util ---
function escHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function escAttr(s) { return (s || '').replace(/"/g, '&quot;'); }

// --- Init ---
loadConfig();
// Auto-refresh logs every 5s when on logs tab
setInterval(() => {
  if (document.querySelector('.tab[data-tab="logs"]').classList.contains('active')) fetchLogs();
}, 5000);
</script>
</body>
</html>
"""
