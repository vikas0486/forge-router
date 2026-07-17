import asyncio
import os
import re
import base64
import mimetypes
import datetime
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import in_paste_mode

from forge_core.router.engine import router, RoutingContext
from forge.ui.console import (
    console, display_welcome, display_response, ThinkingDisplay, Live,
    display_header, display_status
)
from forge.ui.preview_server import preview
from forge_core.config.settings import settings

HISTORY_FILE = Path.home() / ".forge_chat_history"
MEMORY_DIR = Path.home() / ".forge" / "repo-memory"   # /repo summaries for cross-session recall

# Directories to skip when walking a repo
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".nuxt",
    ".turbo", "coverage", ".tox", ".eggs", "*.egg-info",
}

# Source file extensions to include when reading a repo
_SRC_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
    ".cpp", ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt",
    ".scala", ".r", ".sql", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json", ".md", ".txt",
    ".env.example", ".gitignore", ".dockerignore",
}
_SRC_NAMES = {"Makefile", "Dockerfile", "Procfile", "README"}

# Local-file bridge: detects absolute or ~ filesystem paths in a prompt
# (at least two path segments, no spaces) so forge can read the file locally
# and inject it — cloud LLMs like Groq can't touch the filesystem themselves.
_PATH_CANDIDATE_RE = re.compile(r'(?<![\w:])(~?/[\w.@+~-]+(?:/[\w.@+~-]+)+/?)')
_AUTO_LOAD_MAX_PATHS = 3

# Extracts fenced code blocks: captures (lang, content)
_CODE_BLOCK_RE = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
# Max bytes of command output to inject back as context
_RUN_MAX_OUTPUT = 12_000

# ── Visual content detector ──────────────────────────────────────────────────
# Matches: mermaid/plantuml/graphviz code blocks, markdown images,
# HTML img tags, and direct media file links.
_VISUAL_RE = re.compile(
    r'```mermaid|```plantuml|```dot\b|```d2\b'
    r'|!\[.{0,200}\]\('
    r'|<img\s'
    r'|\[.{0,100}\]\(.{0,200}\.(png|jpg|jpeg|gif|svg|webp|mp4|webm|mp3|wav|ogg)\)',
    re.IGNORECASE,
)

def _has_visual(text: str) -> bool:
    return bool(_VISUAL_RE.search(text))


# ── Visual-intent detector (user prompt) ─────────────────────────────────────
# When the USER asks for anything visual, open the preview even if the response
# is plain ASCII art / fenced text the content detector can't recognize.
_VISUAL_PROMPT_RE = re.compile(
    r'\b(draw|sketch|paint|art|ascii|diagram|chart|graph|flowchart|mermaid|svg'
    r'|image|photo|picture|pic|video|animation|animate|visuali[sz]e|render'
    r'|plot|wireframe|mockup|logo|icon|banner|infographic|illustration)\b',
    re.IGNORECASE,
)


def _wants_visual(prompt: str) -> bool:
    return bool(_VISUAL_PROMPT_RE.search(prompt))


class ForgeChat:
    def __init__(self, preferred_model: Optional[str] = None, preview_mode: bool = False):
        self.preferred_model = preferred_model
        self.session = PromptSession(history=FileHistory(str(HISTORY_FILE)))
        self.bindings = KeyBindings()
        self._setup_bindings()
        self.running = True
        self.msg_count = 0
        self.last_provider = "N/A"
        self.last_model = "N/A"
        self.attachments: List[Dict[str, Any]] = []
        self._ctrl_p_pending = False  # flag set by Ctrl+P binding, handled in main loop

        # Preview state:
        #   None  = auto mode — opens automatically when visual content detected
        #   True  = user explicitly ON
        #   False = user explicitly OFF — auto-open is suppressed
        self._preview_explicit: Optional[bool] = None

        # Last response (any type) — restored immediately when preview window opens/re-opens
        self._last_response_content: str = ""
        self._last_response_provider: str = "─"
        self._last_response_model: str = "─"
        self._last_response_msg_count: int = 0

        # Persistent conversation history — survives LLM fallbacks and model switches
        self._session_history: List[Dict[str, str]] = []

        # File/repo context — prepended to EVERY provider call so LLM switches are transparent
        self._context_files: List[Dict[str, Any]] = []

        if preview_mode:
            self._preview_explicit = True
            preview.start()
            console.print("[bold cyan]Preview[/bold cyan] [dim]WKWebView open[/dim]")

    # ── Key bindings ─────────────────────────────────────────────────────────

    def _setup_bindings(self):
        @self.bindings.add("enter", filter=~in_paste_mode)
        def _(event):
            buf = event.current_buffer
            if buf.text.strip():
                buf.validate_and_handle()

        @self.bindings.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        @self.bindings.add("c-j")
        def _(event):
            event.current_buffer.insert_text("\n")

        try:
            @self.bindings.add("shift-enter")
            def _(event):
                event.current_buffer.insert_text("\n")
        except ValueError:
            pass

        # Ctrl+P — set a flag and exit prompt cleanly so the main loop handles the toggle.
        # Never call console.print() inside a key binding — it corrupts prompt_toolkit's display.
        @self.bindings.add("c-p")
        def _toggle_preview(event):
            self._ctrl_p_pending = True
            event.app.exit(exception=KeyboardInterrupt())

    # ── Preview helpers ───────────────────────────────────────────────────────

    def _do_toggle_preview(self, show_status: bool = True):
        """Toggle the preview window. Called from key binding or /preview command."""
        # If window was closed externally (user hit X), sync state
        if preview.active and not preview.window_alive:
            preview.active = False

        if preview.active:
            preview.stop()
            self._preview_explicit = False
            if show_status:
                console.print("[dim]◈ Preview OFF  — Ctrl+P or /p to re-enable[/dim]")
        else:
            try:
                preview.start()             # starts HTTP server + opens WKWebView window
                self._preview_explicit = True
                # Restore last response immediately — no blank window on open
                if self._last_response_content:
                    preview.write(
                        self._last_response_content,
                        provider=self._last_response_provider,
                        model=self._last_response_model,
                        msg_count=self._last_response_msg_count,
                    )
                if show_status:
                    console.print("[bold cyan]◈ Preview ON[/bold cyan]  [dim]Ctrl+P or /p to toggle[/dim]")
            except OSError as e:
                console.print(f"[error]Preview failed to start (port conflict?): {e}[/error]")
                console.print("[dim]Try again in a moment — previous session may still be releasing the port.[/dim]")

    def _auto_preview(self, content: str, prompt: str = ""):
        """Auto-open preview when visual content is detected OR the user asked
        for something visual (draw/art/diagram/image...), unless user said OFF.
        Also re-raises the window if it was closed externally."""
        if self._preview_explicit is False:
            return  # user explicitly disabled — respect that
        if not (_has_visual(content) or _wants_visual(prompt)):
            return
        # Sync state if user closed the window with X
        if preview.active and not preview.window_alive:
            preview.active = False
        if not preview.active:
            try:
                preview.start()
                self._preview_explicit = True   # treat auto-open as "on"
                console.print(
                    "[bold cyan]◈ Preview[/bold cyan] [dim]auto-opened"
                    " (diagram/media detected) — Ctrl+P or /p to toggle[/dim]"
                )
            except OSError:
                pass  # port briefly unavailable — skip silently
        elif not preview.window_alive:
            # Server running but window was closed by X — reopen window only
            preview.start()

    def _push_to_preview(self, content: str, force: bool = False):
        """Update the live preview window.
        - Visual content (mermaid/images/media): always push, clears previous state.
        - force=True (user asked for something visual): push even plain ASCII art.
        - Plain text: only push if preview is already open (don't auto-update a stale window)."""
        if not preview.active or not preview.window_alive:
            return
        if not (_has_visual(content) or force):
            return  # window stays showing last state; text-only responses don't replace it
        preview.write(
            content,
            provider=self.last_provider,
            model=self.last_model,
            msg_count=self.msg_count,
        )

    # ── Image encoding ────────────────────────────────────────────────────────

    def _encode_image(self, image_path: str) -> Dict[str, Any]:
        with open(image_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        mime, _ = mimetypes.guess_type(image_path)
        return {
            "data": data,
            "mime_type": mime or "image/png",
            "name": os.path.basename(image_path),
            "path": image_path,
        }

    # ── Commands ──────────────────────────────────────────────────────────────

    async def handle_command(self, text: str):
        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/exit":
            self.running = False
            console.print("[info]Goodbye! 👋[/info]")

        elif cmd == "/clear":
            console.clear()
            display_welcome()
            self.msg_count = 0
            self.attachments = []
            self._session_history = []
            self._context_files = []
            console.print("[success]Chat cleared. Context, files, and history reset.[/success]")

        elif cmd == "/help":
            console.print("\n[bold]Commands:[/bold]")
            rows = [
                ("/help",              "Show this help"),
                ("/history",           "Show recent prompts"),
                ("/clear",             "Clear screen, files, and history"),
                ("/file <path>",       "Load a file into session context"),
                ("/repo <path>",       "Load entire repo into session context"),
                ("/context",           "Show loaded files  |  /context clear"),
                ("/write <path>",      "Write last LLM response (or code block) to file"),
                ("/run <command>",     "Run shell command, inject output as context"),
                ("(automatic)",        "Any real file/dir path in your message is auto-loaded"),
                ("/status  /models",   "Provider health"),
                ("/provider",          "Last active provider"),
                ("/stats   /kb",       "Session stats + memory KB"),
                ("/model <name|auto>", "Force or release model"),
                ("/image <path>",      "Attach image for Vision"),
                ("/p  /preview",       "Toggle WKWebView preview window"),
                ("Ctrl+P",             "Toggle preview (instant, no typing)"),
                ("/exit",              "Exit"),
            ]
            for cmd_str, desc in rows:
                console.print(f"  [cyan]{cmd_str:<24}[/cyan] {desc}")
            console.print("")

        elif cmd == "/history":
            console.print("\n[bold]Chat History:[/bold]")
            for i, entry in enumerate(list(self.session.history.get_strings())[-10:], 1):
                console.print(f"  [dim]{i}.[/dim] {entry.strip()[:120]}")
            console.print("")

        elif cmd == "/model":
            if len(parts) > 1:
                val = parts[1].lower()
                if val == "auto":
                    self.preferred_model = None
                    console.print("[success]Routing: auto[/success]")
                elif val in router._by_name:
                    self.preferred_model = val
                    console.print(f"[success]Model locked: {val}[/success]")
                else:
                    valid = ", ".join(sorted(router._by_name.keys()))
                    console.print(f"[error]Unknown provider: '{val}'[/error]")
                    console.print(f"[dim]Valid providers: {valid}[/dim]")
            else:
                console.print(f"[info]Model: {self.preferred_model or 'auto-routing'}[/info]")

        elif cmd in ("/status", "/models"):
            results = await router.get_status()
            display_status(results)

        elif cmd == "/provider":
            console.print(f"[info]Last provider: [bold]{self.last_provider}[/bold]  model: {self.last_model}[/info]")

        elif cmd in ("/preview", "/p"):
            self._do_toggle_preview(show_status=True)

        elif cmd in ("/stats", "/kb"):
            from forge_core.memory.knowledge_base import knowledge_base
            from forge_core.router.observability import observability
            kb = knowledge_base.stats()
            obs = observability.summary()
            console.print(f"\n[bold]Session[/bold]")
            ctx_size = sum(len(f["content"]) for f in self._context_files)
            console.print(f"  Messages        : {self.msg_count}")
            console.print(f"  Context turns   : {len(self._session_history)}")
            console.print(f"  Loaded files    : {len(self._context_files)} ({ctx_size:,} chars)")
            console.print(f"  Last provider   : {self.last_provider} ({self.last_model})")
            console.print(f"  Preview         : {'ON' if preview.active and preview.window_alive else 'OFF'}")
            console.print(f"\n[bold]Memory KB[/bold]")
            console.print(f"  Interactions    : {kb['total_interactions']}")
            console.print(f"  Memories indexed: {kb['index_size']} / {kb['total_memories']}")
            console.print(f"  Consolidations  : {kb['consolidations_run']}")
            if obs:
                console.print(f"\n[bold]Provider quality (avg /10)[/bold]")
                for p_name, avg in sorted(obs.items(), key=lambda x: -x[1]):
                    console.print(f"  {p_name:<16} {avg}")
            console.print("")

        elif cmd == "/image":
            if len(parts) > 1:
                path = parts[1].strip("'\"")
                if os.path.exists(path):
                    try:
                        enc = self._encode_image(path)
                        self.attachments.append(enc)
                        console.print(f"[success]Attached: {enc['name']}[/success]")
                    except Exception as e:
                        console.print(f"[error]Failed: {e}[/error]")
                else:
                    console.print(f"[error]Not found: {path}[/error]")
            else:
                console.print("[warning]Usage: /image <path>[/warning]")

        elif cmd == "/file":
            if len(parts) > 1:
                path = os.path.expanduser(parts[1].strip("'\""))
                if os.path.isfile(path):
                    try:
                        content = Path(path).read_text(errors="replace")
                        if len(content) > 120_000:
                            content = content[:120_000] + "\n\n... [truncated at 120KB]"
                        lang = Path(path).suffix.lstrip(".") or "text"
                        self._context_files.append({"type": "file", "path": path, "content": content, "lang": lang})
                        lines = len(content.splitlines())
                        console.print(f"[success]Loaded[/success] {path} — {lines} lines, {len(content):,} chars")
                        console.print(f"[dim]This file is now injected into every LLM call this session.[/dim]")
                    except Exception as e:
                        console.print(f"[error]Failed to read: {e}[/error]")
                else:
                    console.print(f"[error]Not found: {path}[/error]")
            else:
                console.print("[warning]Usage: /file <path>[/warning]")

        elif cmd == "/repo":
            if len(parts) > 1:
                path = os.path.expanduser(parts[1].strip("'\""))
                if os.path.isdir(path):
                    console.print(f"[dim]Reading repo: {path} ...[/dim]")
                    try:
                        content, file_count, total_chars = self._read_repo(path)
                        self._context_files.append({"type": "repo", "path": path, "content": content, "lang": ""})
                        console.print(f"[success]Loaded repo[/success] {path} — {file_count} files, {total_chars:,} chars")
                        console.print(f"[dim]Entire repo is now injected into every LLM call this session.[/dim]")
                        self._save_repo_memory(path, content, file_count)
                    except Exception as e:
                        console.print(f"[error]Failed: {e}[/error]")
                else:
                    console.print(f"[error]Not a directory: {path}[/error]")
            else:
                console.print("[warning]Usage: /repo <path>[/warning]")

        elif cmd == "/context":
            if len(parts) > 1 and parts[1] == "clear":
                self._context_files = []
                console.print("[success]Context files cleared.[/success]")
            else:
                if not self._context_files:
                    console.print("[dim]No files loaded. Use /file <path> or /repo <path>[/dim]")
                else:
                    console.print(f"\n[bold]Loaded context ({len(self._context_files)} items):[/bold]")
                    for i, item in enumerate(self._context_files, 1):
                        sz = len(item["content"])
                        console.print(f"  {i}. [{item['type']}] {item['path']}  ({sz:,} chars)")
                    total = sum(len(f["content"]) for f in self._context_files)
                    console.print(f"  Total: {total:,} chars\n")

        elif cmd == "/write":
            if len(parts) < 2:
                console.print("[warning]Usage: /write <path>  — saves last LLM response (or largest code block) to file[/warning]")
            elif not self._last_response_content:
                console.print("[error]No response yet — ask something first[/error]")
            else:
                path = os.path.expanduser(parts[1].strip("'\""))
                code, lang = self._extract_best_code_block(self._last_response_content)
                content_to_write = code if code else self._last_response_content
                try:
                    dest = Path(path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(content_to_write)
                    lines = len(content_to_write.splitlines())
                    label = f"code block ({lang})" if code else "raw response"
                    console.print(f"[success]Written[/success] {path} — {lines} lines [{label}]")
                    # Auto-load the written file into context so the LLM sees its own output
                    self._context_files.append({"type": "file", "path": path, "content": content_to_write, "lang": lang or Path(path).suffix.lstrip(".")})
                    console.print(f"[dim]File also added to session context.[/dim]")
                except Exception as e:
                    console.print(f"[error]Write failed: {e}[/error]")

        elif cmd == "/run":
            if len(parts) < 2:
                console.print("[warning]Usage: /run <shell command>  — runs command, injects output as context[/warning]")
            else:
                raw_cmd = text[len("/run"):].strip()
                console.print(f"[dim]$ {raw_cmd}[/dim]")
                try:
                    result = subprocess.run(
                        raw_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=os.getcwd(),
                    )
                    stdout = result.stdout or ""
                    stderr = result.stderr or ""
                    combined = stdout
                    if stderr:
                        combined += ("\n--- stderr ---\n" + stderr) if stdout else stderr
                    if len(combined) > _RUN_MAX_OUTPUT:
                        combined = combined[:_RUN_MAX_OUTPUT] + f"\n... [output truncated at {_RUN_MAX_OUTPUT} chars]"
                    rc = result.returncode

                    # Print to terminal
                    if combined.strip():
                        console.print(combined)
                    status_label = "[success]✓[/success]" if rc == 0 else f"[error]✗ exit {rc}[/error]"
                    console.print(f"{status_label} [dim]{raw_cmd}[/dim]")

                    # Inject into conversation history so the LLM knows what happened
                    run_record = (
                        f"[Command executed]\n$ {raw_cmd}\n"
                        f"Exit code: {rc}\n"
                        f"Output:\n```\n{combined.strip()}\n```"
                    )
                    self._session_history.append({"role": "user", "content": run_record})
                    self._session_history = self._session_history[-40:]

                except subprocess.TimeoutExpired:
                    console.print("[error]Command timed out after 120s[/error]")
                except Exception as e:
                    console.print(f"[error]Run failed: {e}[/error]")

        else:
            console.print(f"[error]Unknown: {cmd}  — /help for commands[/error]")

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def start(self):
        display_welcome()
        style = Style.from_dict({"prompt": "cyan bold", "model": "yellow italic"})

        while self.running:
            try:
                mode = self.preferred_model or "auto"
                provider_display = self.last_provider
                if self.attachments:
                    provider_display += f" +{len(self.attachments)}img"

                display_header(mode, provider_display, self.msg_count)

                user_input = await self.session.prompt_async(
                    HTML("<prompt>Forge ❯ </prompt>"),
                    style=style,
                    key_bindings=self.bindings,
                    multiline=True,
                )
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit", "bye", "q"):
                    await self.handle_command("/exit")
                    continue

                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                    continue

                # Local-file bridge: auto-load any real paths mentioned in the prompt
                self._auto_load_paths(user_input)

                img_data = self.attachments[0] if self.attachments else None

                # Build a per-turn context that carries the persistent history
                ctx = self._build_context(user_input)

                thinking = ThinkingDisplay(initial_provider=self.preferred_model or "Auto")
                with Live(thinking, refresh_per_second=10):
                    response = await router.route(
                        user_input,
                        preferred=self.preferred_model,
                        on_progress=thinking.update,
                        image=img_data,
                        context=ctx,
                    )

                self.msg_count += 1
                self.last_provider = response.provider
                self.last_model = response.model or response.provider
                self.attachments = []

                # Persist the updated conversation history for next turn
                self._update_history(ctx)

                display_response(response.content, response.provider, response.model)

                # Always track the latest response so preview can restore it on open
                self._last_response_content = response.content
                self._last_response_provider = self.last_provider
                self._last_response_model = self.last_model
                self._last_response_msg_count = self.msg_count

                # Auto-open preview for visual content or visual prompts; push update if open
                self._auto_preview(response.content, prompt=user_input)
                self._push_to_preview(response.content, force=_wants_visual(user_input))

            except KeyboardInterrupt:
                if self._ctrl_p_pending:
                    self._ctrl_p_pending = False
                    self._do_toggle_preview(show_status=True)
                continue
            except EOFError:
                break
            except Exception as e:
                console.print(f"[error]Error: {e}[/error]")

        preview.shutdown()   # close window + release HTTP port
        console.print("[info]Goodbye! 👋[/info]")

    # ── Context helpers ───────────────────────────────────────────────────────

    def _build_context(self, prompt: str) -> RoutingContext:
        """Create a per-turn context with persistent history and loaded file context."""
        ctx = router.new_context(prompt)
        ctx.history = list(self._session_history)
        ctx.system_prefix = self._build_file_prefix()
        return ctx

    def _update_history(self, ctx: RoutingContext):
        """Capture the updated history after a successful route() call."""
        self._session_history = ctx.history[-40:]

    def _build_file_prefix(self) -> str:
        """Render all loaded files/repos into a single context block for LLM injection."""
        if not self._context_files:
            return ""
        parts = [
            "## Project Context (loaded files — reference only, do not repeat verbatim)\n"
        ]
        for item in self._context_files:
            if item["type"] == "file":
                parts.append(f"### File: `{item['path']}`\n```{item['lang']}\n{item['content']}\n```")
            elif item["type"] == "repo":
                parts.append(f"### Repository: `{item['path']}`\n{item['content']}")
        return "\n\n".join(parts)

    def _read_repo(self, root: str, max_total: int = 300_000):
        """Walk a repo directory and return (formatted_content, file_count, total_chars)."""
        root_path = Path(root)
        file_blocks: List[str] = []
        tree_lines: List[str] = []
        file_count = 0
        total_chars = 0

        # Collect all non-skipped paths for the tree
        all_paths = []
        for p in sorted(root_path.rglob("*")):
            if any(part in _SKIP_DIRS for part in p.relative_to(root_path).parts):
                continue
            all_paths.append(p)

        # Build a simple file tree (dirs + files, max 300 lines)
        for p in all_paths[:300]:
            rel = p.relative_to(root_path)
            depth = len(rel.parts) - 1
            indent = "  " * depth
            marker = "/" if p.is_dir() else ""
            tree_lines.append(f"{indent}{rel.name}{marker}")

        tree = "```\n" + root_path.name + "/\n" + "\n".join(tree_lines) + "\n```"

        # Read source files
        for p in all_paths:
            if p.is_dir():
                continue
            if p.suffix.lower() not in _SRC_EXTS and p.name not in _SRC_NAMES:
                continue
            try:
                text = p.read_text(errors="replace")
            except Exception:
                continue

            if len(text) > 30_000:
                text = text[:30_000] + "\n... [file truncated at 30KB]"

            rel = p.relative_to(root_path)
            lang = p.suffix.lstrip(".") or "text"
            block = f"### `{rel}`\n```{lang}\n{text}\n```"
            file_blocks.append(block)
            file_count += 1
            total_chars += len(text)

            if total_chars >= max_total:
                file_blocks.append("... [repo truncated — total context limit reached]")
                break

        content = f"**File Tree:**\n{tree}\n\n**Source Files:**\n\n" + "\n\n".join(file_blocks)
        return content, file_count, total_chars

    def _extract_best_code_block(self, content: str) -> Tuple[Optional[str], str]:
        """Return (code, lang) for the largest fenced code block in the LLM response.
        Returns (None, '') if no code block found."""
        matches = _CODE_BLOCK_RE.findall(content)  # [(lang, code), ...]
        if not matches:
            return None, ""
        # Pick the largest block by character count
        lang, code = max(matches, key=lambda m: len(m[1]))
        return code.rstrip(), lang or "text"

    def _auto_load_paths(self, text: str):
        """Bridge local files to any LLM. Detects real filesystem paths in the
        prompt, reads them locally, and injects them into session context —
        so cloud providers (Groq, Claude, GPT...) can 'see' local files
        without the user typing /file or /repo."""
        loaded = {item["path"] for item in self._context_files}
        for cand in _PATH_CANDIDATE_RE.findall(text)[:_AUTO_LOAD_MAX_PATHS]:
            path = os.path.expanduser(cand.rstrip(".,;:!?'\")"))
            if path in loaded or not os.path.exists(path):
                continue
            try:
                if os.path.isdir(path):
                    content, file_count, total_chars = self._read_repo(path)
                    self._context_files.append({"type": "repo", "path": path, "content": content, "lang": ""})
                    console.print(
                        f"[bold cyan]◈ Auto-loaded repo[/bold cyan] {path} — {file_count} files, {total_chars:,} chars"
                    )
                    self._save_repo_memory(path, content, file_count)
                else:
                    raw = Path(path).read_bytes()
                    if b"\x00" in raw[:1024]:
                        console.print(f"[dim]◈ Skipped binary file: {path} (use /image for pictures)[/dim]")
                        continue
                    content = raw.decode("utf-8", errors="replace")
                    if len(content) > 120_000:
                        content = content[:120_000] + "\n\n... [truncated at 120KB]"
                    lang = Path(path).suffix.lstrip(".") or "text"
                    self._context_files.append({"type": "file", "path": path, "content": content, "lang": lang})
                    console.print(
                        f"[bold cyan]◈ Auto-loaded[/bold cyan] {path} — {len(content):,} chars"
                    )
                console.print("[dim]  forge read it locally — the LLM now sees its contents in every call.[/dim]")
                loaded.add(path)
            except Exception as e:
                console.print(f"[dim]◈ Auto-load failed for {path}: {e}[/dim]")

    def _save_repo_memory(self, repo_path: str, content: str, file_count: int):
        """Persist a repo summary to the shared memory directory for cross-session recall."""
        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            name = Path(repo_path).name
            ts = datetime.datetime.now().strftime("%Y-%m-%d")
            out = MEMORY_DIR / f"forge_repo_{name}.md"
            # Save only the file tree + metadata, not full file contents (that's session-only)
            tree_end = content.find("**Source Files:**")
            tree_section = content[:tree_end].strip() if tree_end > 0 else content[:2000]
            out.write_text(
                f"# Repo Context: {name}\n\n"
                f"**Path:** `{repo_path}`  \n"
                f"**Loaded:** {ts}  \n"
                f"**Files:** {file_count}\n\n"
                f"{tree_section}\n\n"
                f"_To reload in a new forge session: `/repo {repo_path}`_\n"
            )
            console.print(f"[dim]Memory saved → {out}[/dim]")
        except Exception as e:
            console.print(f"[dim]Memory save skipped: {e}[/dim]")
