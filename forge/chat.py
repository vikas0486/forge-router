import asyncio
import json
import os
import base64
import mimetypes
from pathlib import Path
from typing import Optional, List, Dict, Any
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import is_pasting

from forge.router.engine import router
from forge.ui.console import (
    console, display_welcome, display_response, ThinkingDisplay, Live, 
    display_header, display_status
)
from forge.config.settings import settings

HISTORY_FILE = Path.home() / ".forge_chat_history"

class ForgeChat:
    def __init__(self, preferred_model: Optional[str] = None):
        self.preferred_model = preferred_model
        self.session = PromptSession(history=FileHistory(str(HISTORY_FILE)))
        self.bindings = KeyBindings()
        self.setup_bindings()
        self.running = True
        self.msg_count = 0
        self.last_provider = "N/A"
        self.attachments = [] # List of encoded images

    def setup_bindings(self):
        @self.bindings.add("enter", filter=~is_pasting)
        def _(event):
            buffer = event.current_buffer
            if buffer.text.strip():
                buffer.validate_and_handle()
            else:
                pass

        @self.bindings.add("escape", "enter")
        def _(event):
            """Alt+Enter or Escape+Enter inserts a newline."""
            event.current_buffer.insert_text("\n")

        @self.bindings.add("c-j")
        def _(event):
            """Ctrl+J inserts a newline."""
            event.current_buffer.insert_text("\n")

        try:
            @self.bindings.add("shift-enter")
            def _(event):
                """Shift+Enter inserts a newline."""
                event.current_buffer.insert_text("\n")
        except ValueError:
            # Fallback if shift-enter is not supported by this prompt_toolkit version/platform
            pass

    def _encode_image(self, image_path: str) -> Dict[str, Any]:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        mime_type, _ = mimetypes.guess_type(image_path)
        return {
            "data": encoded_string,
            "mime_type": mime_type or "image/png",
            "name": os.path.basename(image_path),
            "path": image_path
        }

    async def handle_command(self, text: str):
        parts = text.split()
        cmd = parts[0].lower()
        
        if cmd == "/exit":
            self.running = False
            console.print("[info]Exiting Forge. Goodbye! 👋[/info]")
        elif cmd == "/clear":
            console.clear()
            display_welcome()
            self.msg_count = 0
            self.attachments = []
            console.print("[success]Chat cleared and state reset.[/success]")
        elif cmd == "/help":
            console.print("\n[bold]Available Commands:[/bold]")
            console.print("  /help            - Show this help")
            console.print("  /history         - Show previous prompts")
            console.print("  /clear           - Clear the screen")
            console.print("  /status /models  - Check provider/model status")
            console.print("  /provider        - Show current active provider")
            console.print("  /model <name>    - Switch to specific model (or 'auto')")
            console.print("  /image <path>    - Attach an image (Vision support)")
            console.print("  /exit            - Exit the chat\n")
        elif cmd == "/history":
            console.print("\n[bold]Chat History:[/bold]")
            history = list(self.session.history.get_strings())[-10:]
            for i, entry in enumerate(history):
                console.print(f"  [dim]{i+1}.[/dim] {entry.strip()[:100]}{'...' if len(entry) > 100 else ''}")
            console.print("")
        elif cmd == "/model":
            if len(parts) > 1:
                new_model = parts[1].lower()
                if new_model == "auto":
                    self.preferred_model = None
                    console.print("[success]Model set to [bold]auto-routing[/bold][/success]")
                else:
                    self.preferred_model = new_model
                    console.print(f"[success]Model set to [bold]{new_model}[/bold][/success]")
            else:
                console.print(f"[info]Current model: [bold]{self.preferred_model or 'auto-routing'}[/bold][/info]")
        elif cmd in ["/status", "/models"]:
            results = await router.get_status()
            display_status(results)
        elif cmd == "/provider":
            console.print(f"[info]Last active provider: [provider]{self.last_provider}[/provider][/info]")
        elif cmd == "/image":
            if len(parts) > 1:
                path = parts[1].strip("'\"") # Handle quoted paths
                if os.path.exists(path):
                    try:
                        encoded = self._encode_image(path)
                        self.attachments.append(encoded)
                        console.print(f"[success]📎 {encoded['name']} attached[/success]")
                    except Exception as e:
                        console.print(f"[error]Failed to load image: {str(e)}[/error]")
                else:
                    console.print(f"[error]File not found: {path}[/error]")
            else:
                console.print("[warning]Usage: /image <path/to/image.png>[/warning]")
        else:
            console.print(f"[error]Unknown command: {cmd}[/error]")

    async def start(self):
        display_welcome()
        
        style = Style.from_dict({
            'prompt': 'cyan bold',
            'model': 'yellow italic',
        })

        while self.running:
            try:
                # Redesigned Layout: Persistent Header
                mode = "auto" if not self.preferred_model else self.preferred_model
                provider_display = self.last_provider
                if self.attachments:
                    provider_display += f" (📎 {len(self.attachments)})"
                
                display_header(mode, provider_display, self.msg_count)
                
                prompt_text = HTML(f"<prompt>Forge ❯ </prompt>")
                
                user_input = await self.session.prompt_async(
                    prompt_text,
                    style=style,
                    key_bindings=self.bindings,
                    multiline=True
                )
                
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                    continue

                # Prepare image for provider (currently support 1 image per request)
                img_data = self.attachments[0] if self.attachments else None

                thinking = ThinkingDisplay(initial_provider=self.preferred_model or "Auto")
                with Live(thinking, refresh_per_second=10):
                    response = await router.route(
                        user_input, 
                        preferred=self.preferred_model,
                        on_progress=thinking.update,
                        image=img_data
                    )
                
                self.msg_count += 1
                self.last_provider = response.provider
                self.attachments = [] # Clear attachments after use
                display_response(response.content, response.provider, response.model)

            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            except Exception as e:
                from forge.ui.console import console
                console.print(Panel(f"[error]{str(e)}[/error]", title="Error", border_style="red"))

        console.print("[info]Goodbye! 👋[/info]")

