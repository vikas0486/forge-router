"""
Forge Preview Server — renders forge chat responses as beautiful live HTML.

Runs as a daemon thread on localhost:7654.
Each LLM response is written to ~/.forge/results.md and pushed to the browser
via 1-second polling. Mermaid diagrams, syntax-highlighted code, and full
GitHub-dark markdown rendering — all in the browser while you chat in the terminal.

Usage:
    from forge.ui.preview_server import preview
    preview.write(content, provider="groq", model="llama-3.3-70b")
    preview.start()   # opens browser tab + starts server
    preview.stop()
"""
import json
import logging
import mimetypes
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger("forge.ui.preview")

PREVIEW_PORT = 7654
RESULTS_DIR = Path.home() / ".forge"
RESULTS_MD = RESULTS_DIR / "results.md"
STATE_FILE = RESULTS_DIR / "preview_state.json"  # current content + metadata
GENERATED_DIR = RESULTS_DIR / "generated"

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>⚒ Forge — Live Preview</title>

<!-- Mermaid -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<!-- Viz.js for Graphviz/DOT -->
<script src="https://cdn.jsdelivr.net/npm/viz.js@2.1.2/viz.js"></script>
<script src="https://cdn.jsdelivr.net/npm/viz.js@2.1.2/full.render.js"></script>
<!-- Marked (markdown parser) -->
<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
<!-- Highlight.js -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>

<style>
  :root {
    --bg:       #0d1117;
    --surface:  #161b22;
    --border:   #30363d;
    --text:     #e6edf3;
    --muted:    #8b949e;
    --accent:   #58a6ff;
    --green:    #3fb950;
    --orange:   #f0883e;
    --purple:   #d2a8ff;
    --red:      #ff7b72;
    --header-h: 54px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
  }

  /* ── Header ─────────────────────────────────────────────────────────────── */
  #forge-header {
    position: fixed;
    top: 0; left: 0; right: 0;
    height: var(--header-h);
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 16px;
    z-index: 100;
    backdrop-filter: blur(10px);
  }

  .logo {
    font-size: 18px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
  }

  .separator { color: var(--border); font-size: 20px; }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid;
  }

  #provider-badge {
    color: var(--green);
    border-color: #238636;
    background: rgba(35, 134, 54, 0.1);
  }

  #model-badge {
    color: var(--purple);
    border-color: #8957e5;
    background: rgba(137, 87, 229, 0.1);
  }

  #msg-badge {
    color: var(--orange);
    border-color: #9e6a03;
    background: rgba(158, 106, 3, 0.1);
  }

  .action-btn {
    appearance: none;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 999px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }

  .action-btn:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  .spacer { flex: 1; }

  #status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }

  #status-dot.stale { background: var(--muted); animation: none; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  #last-updated { color: var(--muted); font-size: 12px; }

  /* ── Content area ────────────────────────────────────────────────────────── */
  #wrapper {
    max-width: 900px;
    margin: 0 auto;
    padding: calc(var(--header-h) + 32px) 32px 80px;
  }

  /* ── Markdown styles ─────────────────────────────────────────────────────── */
  .md h1, .md h2, .md h3, .md h4, .md h5, .md h6 {
    margin-top: 24px;
    margin-bottom: 12px;
    font-weight: 600;
    line-height: 1.25;
    color: var(--text);
  }
  .md h1 { font-size: 2em; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  .md h2 { font-size: 1.5em; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .md h3 { font-size: 1.25em; }

  .md p { margin: 12px 0; }

  .md a { color: var(--accent); text-decoration: none; }
  .md a:hover { text-decoration: underline; }

  .md ul, .md ol { padding-left: 28px; margin: 12px 0; }
  .md li { margin: 4px 0; }

  .md blockquote {
    border-left: 4px solid var(--accent);
    padding: 8px 16px;
    margin: 16px 0;
    color: var(--muted);
    background: var(--surface);
    border-radius: 0 6px 6px 0;
  }

  .md code {
    background: rgba(110,118,129,0.15);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 13px;
    color: var(--red);
  }

  .md pre {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: auto;
    margin: 16px 0;
  }

  .md pre code {
    background: none;
    padding: 16px;
    display: block;
    color: var(--text);
    font-size: 13.5px;
    line-height: 1.55;
  }

  .md table {
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
    font-size: 14px;
  }
  .md th, .md td {
    border: 1px solid var(--border);
    padding: 8px 16px;
    text-align: left;
  }
  .md th {
    background: var(--surface);
    font-weight: 600;
    color: var(--accent);
  }
  .md tr:nth-child(even) { background: rgba(255,255,255,0.02); }

  .md hr {
    border: none;
    border-top: 1px solid var(--border);
    margin: 24px 0;
  }

  /* ── Mermaid override ────────────────────────────────────────────────────── */
  .md .mermaid {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    margin: 20px 0;
    text-align: center;
    overflow-x: auto;
  }

  .md .svg-block {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    margin: 20px 0;
    text-align: center;
    overflow: auto;
  }

  .md .svg-block svg {
    max-width: 100%;
    height: auto;
  }

  .md .kroki-diagram {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    margin: 20px 0;
    overflow: auto;
  }

  .md .kroki-diagram svg {
    max-width: 100%;
    height: auto;
  }

  .md .diagram-error {
    color: var(--orange);
    font-size: 13px;
    margin-top: 12px;
  }

  .md .mermaid-source {
    margin-top: 12px;
  }

  /* ── Empty state ─────────────────────────────────────────────────────────── */
  #empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 60vh;
    color: var(--muted);
    text-align: center;
    gap: 16px;
  }
  #empty-state .big-logo { font-size: 56px; }
  #empty-state h2 { color: var(--text); font-size: 22px; }
  #empty-state p { max-width: 420px; line-height: 1.7; }
  #empty-state code {
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 4px 10px;
    border-radius: 6px;
    color: var(--accent);
    font-size: 13px;
  }

  /* ── Slide-in animation for new content ──────────────────────────────────── */
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .fresh { animation: slideIn 0.3s ease-out; }
</style>
</head>

<body>

<div id="forge-header">
  <span class="logo">⚒ FORGE</span>
  <span class="separator">|</span>
  <span class="badge" id="provider-badge">─</span>
  <span class="badge" id="model-badge">─</span>
  <span class="badge" id="msg-badge">─</span>
  <span class="spacer"></span>
  <button id="copy-btn" class="action-btn" type="button" title="Copy current preview output">Copy</button>
  <span id="last-updated">Waiting for first response…</span>
  <span id="status-dot" class="stale" title="Live connection"></span>
</div>

<div id="wrapper">
  <div id="empty-state">
    <div class="big-logo">⚒</div>
    <h2>Forge Preview</h2>
    <p>Your forge chat responses will appear here, fully rendered — including Mermaid diagrams, tables, and syntax-highlighted code.</p>
    <p>Type a message in your terminal: <code>forge chat --preview</code></p>
  </div>
  <div id="content" class="md" style="display:none"></div>
</div>

<script>
  mermaid.initialize({
    startOnLoad: false,
    theme: 'dark',
    darkMode: true,
    themeVariables: {
      primaryColor: '#1f6feb',
      primaryTextColor: '#e6edf3',
      primaryBorderColor: '#30363d',
      lineColor: '#8b949e',
      secondaryColor: '#161b22',
      tertiaryColor: '#0d1117',
      background: '#0d1117',
      mainBkg: '#161b22',
      nodeBorder: '#30363d',
      clusterBkg: '#161b22',
      titleColor: '#e6edf3',
      edgeLabelBackground: '#0d1117',
    },
    flowchart: { useMaxWidth: true, htmlLabels: true },
  });

  let _lastTs = 0;
  let _pollFail = 0;
  let _lastMarkdown = '';
  let _mermaidSeq = 0;
  const _viz = typeof Viz !== 'undefined' ? new Viz() : null;

  function escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showMermaidFallback(node, source, error) {
    node.innerHTML =
      `<pre class="mermaid-source"><code>${escapeHtml(source)}</code></pre>` +
      `<div class="diagram-error">Mermaid preview could not render this diagram.${error ? ' ' + escapeHtml(String(error)) : ''}</div>`;
  }

  function createMermaidNode(code) {
    const node = document.createElement('div');
    node.className = 'mermaid';
    node.textContent = code.trim();
    return node;
  }

  async function copyCurrentOutput() {
    const selected = window.getSelection ? String(window.getSelection()).trim() : '';
    const text = selected || _lastMarkdown || document.getElementById('content').innerText || '';
    if (!text) return;

    const btn = document.getElementById('copy-btn');
    const prev = btn.textContent;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      btn.textContent = 'Copied';
    } catch (e) {
      console.warn('copy failed:', e);
      btn.textContent = 'Copy failed';
    }
    setTimeout(() => { btn.textContent = prev; }, 1200);
  }

  function setHeader(data) {
    const p = document.getElementById('provider-badge');
    const m = document.getElementById('model-badge');
    const n = document.getElementById('msg-badge');
    p.textContent = '◈ ' + (data.provider || '?');
    m.textContent = data.model || '?';
    n.textContent = '#' + (data.msg_count || 1);
    const d = new Date(data.updated_at * 1000);
    document.getElementById('last-updated').textContent =
      d.toLocaleTimeString();
    document.getElementById('status-dot').className = '';
  }

  async function render(markdown) {
    _lastMarkdown = markdown || '';
    const pureMermaid = markdown.trim().match(/^```mermaid\s*\r?\n([\s\S]*?)```$/i);
    const el = document.getElementById('content');

    if (pureMermaid) {
      el.innerHTML = '';
      el.appendChild(createMermaidNode(pureMermaid[1]));
      el.style.display = 'block';
      el.classList.remove('fresh');
      void el.offsetWidth;
      el.classList.add('fresh');
      document.getElementById('empty-state').style.display = 'none';
    } else {
    // Pre-process visual blocks before marked parses them.
    // Accept case variants and CRLF line endings because models are inconsistent.
      const processed = markdown
      .replace(/```mermaid\s*\r?\n([\s\S]*?)```/gi, (_, code) => {
        return `<div class="mermaid">${code.trim()}</div>`;
      })
      .replace(/```svg\s*\r?\n([\s\S]*?)```/gi, (_, code) => {
        return `<div class="svg-block">${code.trim()}</div>`;
      })
      .replace(/```(?:dot|graphviz)\s*\r?\n([\s\S]*?)```/gi, (_, code) => {
        return `<div class="kroki-diagram" data-diagram-type="graphviz"><pre class="diagram-source" style="display:none">${escapeHtml(code.trim())}</pre></div>`;
      })
      .replace(/```(plantuml|d2)\s*\r?\n([\s\S]*?)```/gi, (_, type, code) => {
        return `<div class="kroki-diagram" data-diagram-type="${type}"><pre class="diagram-source" style="display:none">${escapeHtml(code.trim())}</pre></div>`;
      });

      // Parse markdown (skip mermaid blocks — already converted)
      const html = marked.parse(processed);
      el.innerHTML = html;
      el.style.display = 'block';
      el.classList.remove('fresh');
      void el.offsetWidth; // force reflow
      el.classList.add('fresh');

      document.getElementById('empty-state').style.display = 'none';
    }

    // Render mermaid
    const mermaidNodes = Array.from(document.querySelectorAll('.mermaid'));
    for (const node of mermaidNodes) {
      const source = node.textContent || '';
      try {
        const rendered = await mermaid.render(`forge-mermaid-${_mermaidSeq++}`, source);
        node.innerHTML = rendered.svg;
        if (rendered.bindFunctions) {
          rendered.bindFunctions(node);
        }
      } catch(e) {
        console.warn('mermaid:', e);
        showMermaidFallback(node, source, e && e.message ? e.message : e);
      }
    }

    // Render DOT locally in-browser and PlantUML/D2 via Kroki.
    await Promise.all(Array.from(document.querySelectorAll('.kroki-diagram')).map(async (el) => {
      const type = el.dataset.diagramType || '';
      const source = el.querySelector('.diagram-source')?.textContent || '';
      if (!source) return;
      try {
        if (type === 'graphviz' && _viz) {
          el.innerHTML = await _viz.renderString(source);
          return;
        }
        const endpoint = `https://kroki.io/${type}/svg`;
        const resp = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          body: source,
        });
        if (!resp.ok) throw new Error(`${type} ${resp.status}`);
        el.innerHTML = await resp.text();
      } catch (e) {
        console.warn('diagram render:', type, e);
        el.innerHTML = `<pre><code>${escapeHtml(source)}</code></pre><div class="diagram-error">Preview could not render this ${type} diagram.</div>`;
      }
    }));

    // Syntax-highlight code blocks
    document.querySelectorAll('pre code').forEach(block => {
      if (!block.parentElement.querySelector('svg')) {
        hljs.highlightElement(block);
      }
    });
  }

  async function poll() {
    try {
      const r = await fetch('/state');
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      _pollFail = 0;
      if (data.updated_at !== _lastTs) {
        _lastTs = data.updated_at;
        setHeader(data);
        await render(data.content);
      }
    } catch(e) {
      _pollFail++;
      if (_pollFail > 3) {
        document.getElementById('status-dot').className = 'stale';
      }
    }
  }

  // Poll every 800ms — snappy but not aggressive
  document.getElementById('copy-btn').addEventListener('click', copyCurrentOutput);
  setInterval(poll, 800);
  poll();
</script>

</body>
</html>
"""


class _PreviewState:
    def __init__(self):
        self.content = ""
        self.provider = "─"
        self.model = "─"
        self.msg_count = 0
        self.updated_at = 0.0
        self._lock = threading.Lock()

    def update(self, content: str, provider: str, model: str, msg_count: int):
        with self._lock:
            self.content = content
            self.provider = provider
            self.model = model or provider
            self.msg_count = msg_count
            self.updated_at = time.time()
        # Write to disk too (for persistence across restarts)
        try:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            RESULTS_MD.write_text(content, encoding="utf-8")
            STATE_FILE.write_text(self.to_json(), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[preview] disk write failed: {e}")

    def to_json(self) -> str:
        with self._lock:
            return json.dumps({
                "content": self.content,
                "provider": self.provider,
                "model": self.model,
                "msg_count": self.msg_count,
                "updated_at": self.updated_at,
            })


_state = _PreviewState()


class _Server(HTTPServer):
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default HTTP logging

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", _HTML.encode())
        elif self.path == "/state":
            self._send(200, "application/json", _state.to_json().encode())
        elif self.path.startswith("/generated/"):
            self._send_generated()
        else:
            self._send(404, "text/plain", b"Not Found")

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_generated(self):
        rel = unquote(urlparse(self.path).path.removeprefix("/generated/"))
        filename = Path(rel).name
        path = GENERATED_DIR / filename
        if not path.exists() or not path.is_file():
            self._send(404, "text/plain", b"Not Found")
            return
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, ctype, path.read_bytes())


class ForgePreview:
    """
    Two-tier lifecycle:
      _ensure_server() — starts the HTTP server once per forge session, keeps it up.
      start()          — ensures server + opens/reopens the WKWebView window.
      stop()           — closes the WKWebView window ONLY; server stays running.
      shutdown()       — closes window + stops server (called on forge chat exit).

    Separating server and window lifetimes avoids all port-rebind issues.
    The port is bound once and released only when the session ends.
    """
    PREVIEW_PORT = PREVIEW_PORT

    def __init__(self):
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._window_proc: Optional[subprocess.Popen] = None
        self.active = False   # True when the WKWebView window is open

    @property
    def window_alive(self) -> bool:
        """True if the WKWebView subprocess is still running."""
        return (
            self._window_proc is not None
            and self._window_proc.poll() is None
        )

    def write(self, content: str, provider: str = "─", model: str = "", msg_count: int = 1):
        """Push new content to the preview. Thread-safe."""
        _state.update(content, provider, model, msg_count)

    def _ensure_server(self):
        """Start the HTTP server if not already running. Raises OSError on port conflict."""
        if self._server:
            return
        self._server = _Server(("127.0.0.1", PREVIEW_PORT), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"[preview] HTTP server listening on :{PREVIEW_PORT}")

    def start(self):
        """Ensure server is running and open the WKWebView window.
        Idempotent — safe to call when already active."""
        self._ensure_server()   # no-op if already running; raises OSError on conflict
        self.active = True
        if not self.window_alive:
            self._open_browser(f"http://localhost:{PREVIEW_PORT}")

    def stop(self):
        """Close the WKWebView window. HTTP server stays running.
        Use shutdown() to fully stop everything at session end.
        Non-blocking: terminate() fires and returns immediately so key bindings don't stall."""
        self.active = False
        if self._window_proc and self._window_proc.poll() is None:
            self._window_proc.terminate()   # fire-and-forget — subprocess exits in background
        self._window_proc = None
        logger.info("[preview] window closed")

    def shutdown(self):
        """Full teardown — close window + stop HTTP server. Call on forge chat exit."""
        self.stop()
        if self._server:
            self._server.shutdown()
        self._server = None
        self._thread = None
        logger.info("[preview] server stopped")

    def _open_browser(self, url: str):
        """Launch the native WKWebView window as a subprocess."""
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "forge.ui.preview_window", url],
                cwd=str(Path(__file__).parent.parent.parent),  # forge-router root
            )
            self._window_proc = proc
            logger.info(f"[preview] WKWebView window launched (pid={proc.pid})")
        except Exception as e:
            logger.warning(f"[preview] window launch failed: {e} — falling back to browser")
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", url])
                else:
                    subprocess.Popen(["xdg-open", url])
            except Exception:
                pass


# Singleton
preview = ForgePreview()
