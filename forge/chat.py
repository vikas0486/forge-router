import asyncio
import json
import os
import re
import base64
import mimetypes
from pathlib import Path
from typing import Optional, List, Dict, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import in_paste_mode

from forge.router.engine import router, RoutingContext
from forge.ui.console import (
    console, display_welcome, display_response, ThinkingDisplay, Live,
    display_header, display_status
)
from forge.ui.preview_server import preview
from forge.config.settings import settings

HISTORY_FILE = Path.home() / ".forge_chat_history"

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

    def _auto_preview(self, content: str):
        """Auto-open preview when visual content is detected, unless user said OFF.
        Also re-raises the window if it was closed externally."""
        if self._preview_explicit is False:
            return  # user explicitly disabled — respect that
        if not _has_visual(content):
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

    def _push_to_preview(self, content: str):
        """Update the live preview window.
        - Visual content (mermaid/images/media): always push, clears previous state.
        - Plain text: only push if preview is already open (don't auto-update a stale window)."""
        if not preview.active or not preview.window_alive:
            return
        if not _has_visual(content):
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
            self._session_history = []  # clear conversation context too
            console.print("[success]Chat cleared. Context and history reset.[/success]")

        elif cmd == "/help":
            console.print("\n[bold]Commands:[/bold]")
            rows = [
                ("/help",             "Show this help"),
                ("/history",          "Show recent prompts"),
                ("/clear",            "Clear screen + reset context"),
                ("/status  /models",  "Provider health"),
                ("/provider",         "Last active provider"),
                ("/stats   /kb",      "Session stats + memory KB"),
                ("/model <name|auto>","Force or release model"),
                ("/image <path>",     "Attach image for Vision"),
                ("/p  /preview",      "Toggle WKWebView preview window"),
                ("Ctrl+P",            "Toggle preview (instant, no typing)"),
                ("/exit",             "Exit"),
            ]
            for cmd_str, desc in rows:
                console.print(f"  [cyan]{cmd_str:<22}[/cyan] {desc}")
            console.print("")

        elif cmd == "/history":
            console.print("\n[bold]Recent prompts:[/bold]")
            for i, entry in enumerate(list(self.session.history.get_strings())[-10:], 1):
                console.print(f"  [dim]{i}.[/dim] {entry.strip()[:120]}")
            console.print("")

        elif cmd == "/model":
            if len(parts) > 1:
                val = parts[1].lower()
                if val == "auto":
                    self.preferred_model = None
                    console.print("[success]Routing: auto[/success]")
                else:
                    self.preferred_model = val
                    console.print(f"[success]Model locked: {val}[/success]")
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
            from forge.memory.knowledge_base import knowledge_base
            from forge.router.observability import observability
            kb = knowledge_base.stats()
            obs = observability.summary()
            console.print(f"\n[bold]Session[/bold]")
            console.print(f"  Messages        : {self.msg_count}")
            console.print(f"  Context turns   : {len(self._session_history)}")
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

                # Auto-open preview for visual content; push update if already open
                self._auto_preview(response.content)
                self._push_to_preview(response.content)

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
        """Create a fresh per-turn context but inject the persistent session history."""
        ctx = router.new_context(prompt)
        # Copy history so multi-turn context reaches the provider
        ctx.history = list(self._session_history)
        return ctx

    def _update_history(self, ctx: RoutingContext):
        """Capture the updated history after a successful route() call."""
        # ctx.history was mutated in-place by route() — it now has the latest assistant message
        # Keep last 20 turns (40 entries: 20 user + 20 assistant) to bound context size
        self._session_history = ctx.history[-40:]
