from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.rule import Rule
import time

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "provider": "magenta bold",
})

console = Console(theme=custom_theme)

class ThinkingDisplay:
    def __init__(self, initial_provider: str = "Auto"):
        self.start_time = time.time()
        self.current_provider = initial_provider
        self.status = "Forging response..."
        self.history = [] # List of (provider, result) e.g. ("groq", "Timed out")

    def update(self, provider: str = None, status: str = None, failed_provider: str = None):
        if provider:
            self.current_provider = provider
        if status:
            self.status = status
        if failed_provider:
            reason = status or "failed"
            if not self.history or self.history[-1][0] != failed_provider:
                self.history.append((failed_provider, reason))

    def __rich__(self):
        elapsed = time.time() - self.start_time
        
        header = Text.assemble(
            ("⚒ ", "bold cyan"),
            (f"{self.status} ", "bold white"),
            (f"({elapsed:.1f}s)", "dim")
        )
        
        info = Table.grid(padding=(0, 1))
        info.add_row(Text("Provider:", style="info"), Text(self.current_provider, style="provider"))
        
        renderables = [header, info]
        
        if self.history:
            history_text = Text("\nFallbacks:", style="warning")
            for p, res in self.history:
                history_text.append(f"\n  {p} → ", style="dim")
                history_text.append(res, style="error")
            renderables.append(history_text)
        
        return Group(*renderables)

def display_welcome():
    console.print(Panel.fit(
        "[bold cyan]⚒️  FORGE INTERACTIVE CODE  ⚒️[/bold cyan]\n"
        "[gray]High-performance multi-LLM routing engine.[/gray]",
        border_style="cyan"
    ))

def display_header(mode: str, provider: str, msg_count: int):
    """Display a persistent session header."""
    header_text = Text.assemble(
        (" Forge ", "bold cyan"),
        ("─ ", "dim"),
        (f"{mode} ", "yellow"),
        ("─ ", "dim"),
        (f"{provider} ", "provider"),
        ("─ ", "dim"),
        (f"{msg_count} msgs ", "info")
    )
    console.print(Rule(header_text, style="dim cyan"))

def display_response(content: str, provider: str, model: str = None):
    title = f"[provider]{provider}[/provider]"
    if model:
        title += f" ([dim]{model}[/dim])"
    
    # Try to render as markdown if it looks like it
    content_renderable = Markdown(content) if "```" in content or "#" in content else content
    
    console.print(Panel(
        content_renderable,
        title=title,
        border_style="cyan",
        padding=(1, 2)
    ))

def display_status(status_map):
    table = Table(title="Forge Provider Status")
    table.add_column("Provider", style="yellow")
    table.add_column("Status", justify="center")
    table.add_column("Reason/Details", style="dim")

    for name, stat in status_map.items():
        status_icon = "[green]✓[/green]" if stat["ok"] else "[red]✗[/red]"
        table.add_row(name, status_icon, stat.get("reason") or stat.get("details") or "")

    console.print(table)
