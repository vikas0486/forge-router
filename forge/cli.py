import typer
import asyncio
import logging
import sys
import platform
import shutil
from typing import Optional
from forge_core.router.engine import router
from forge.ui.console import console, display_welcome, display_response, display_status
from forge_core.config.settings import settings, SHARED_ENV_PATH

app = typer.Typer(
    help="🛠️ Forge: High-performance AI Router & Interactive CLI",
    add_completion=False,
)

@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """🛠️ Forge: High-performance AI Router & Interactive CLI"""
    if ctx.invoked_subcommand is None:
        from forge.chat import ForgeChat
        chat_app = ForgeChat()
        asyncio.run(chat_app.start())
        raise typer.Exit()

@app.command()
def ask(
    prompt: str = typer.Argument(..., help="The question to ask"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a specific model"),
    timeout: int = typer.Option(settings.timeout, "--timeout", "-t", help="Timeout in seconds")
):
    """Ask a single question and get a response."""
    async def _ask():
        from forge.ui.console import ThinkingDisplay, Live
        try:
            thinking = ThinkingDisplay(initial_provider=model or "Auto")
            with Live(thinking, refresh_per_second=10):
                response = await router.route(
                    prompt, 
                    preferred=model, 
                    timeout=timeout,
                    on_progress=thinking.update
                )
            display_response(response.content, response.provider, response.model)
        except Exception as e:
            console.print(f"[error]Error:[/error] {str(e)}")

    asyncio.run(_ask())

@app.command()
def chat(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Force a specific model"),
    preview_flag: bool = typer.Option(False, "--preview", "-p", help="Open browser preview (renders Mermaid + Markdown live)"),
):
    """Start an interactive chat session."""
    from forge.chat import ForgeChat
    chat_app = ForgeChat(preferred_model=model, preview_mode=preview_flag)
    asyncio.run(chat_app.start())

@app.command()
def status():
    """Check the status and health of all providers."""
    async def _status():
        with console.status("[bold cyan]Checking provider health..."):
            results = await router.get_status()
        display_status(results)

    asyncio.run(_status())

@app.command()
def doctor(
    live: bool = typer.Option(
        False, "--live",
        help="Send a real 1-word generation to every provider — surfaces quota, credit, and auth failures that key checks miss",
    ),
):
    """Diagnose configuration and environment issues."""
    console.print("\n[bold info]⚒️ Forge Diagnosis Report[/bold info]\n")
    
    # 1. System Info
    console.print(f"[bold]System:[/bold]")
    console.print(f"  Python Version: {sys.version.split()[0]}")
    console.print(f"  OS: {platform.system()} ({platform.release()})")
    
    # 2. Environment Info
    console.print(f"\n[bold]Environment:[/bold]")
    if SHARED_ENV_PATH.exists():
        console.print(f"  [success]✓[/success] Credentials found at: {SHARED_ENV_PATH}")
    else:
        console.print(f"  [error]✗[/error] Credentials NOT found at: {SHARED_ENV_PATH}")
    
    # 3. Key Detection
    console.print(f"\n[bold]API Keys:[/bold]")
    keys = {
        "Groq": settings.groq_api_key,
        "Cerebras": settings.cerebras_api_key,
        "Mistral": settings.mistral_api_key,
        "Claude Code": settings.claude_code_oauth_token,
        "Claude API": settings.anthropic_api_key,
        "OpenAI": settings.openai_api_key,
        "Codex": settings.codex_api_key,
        "OpenRouter": settings.openrouter_api_key,
        "GitHub Token": settings.github_token,
    }
    for name, value in keys.items():
        status = "[success]✓ detected[/success]" if value else "[error]✗ missing[/error]"
        console.print(f"  {name.ljust(15)}: {status}")

    # 4. Tool Detection
    console.print(f"\n[bold]External Tools:[/bold]")
    tools = ["agy", "copilot", "ollama", "forge"]
    for cmd in tools:
        path = shutil.which(cmd)
        status = f"[success]✓ found[/success] ({path})" if path else "[warning]! not found[/warning]"
        console.print(f"  {cmd.ljust(15)}: {status}")

    # 5. Provider Health
    if live:
        console.print(f"\n[bold]Provider Health — LIVE PROBE[/bold] [dim](real generation per provider, ~40s max)[/dim]")
        async def run_deep_probe():
            with console.status("[bold cyan]Probing all providers concurrently..."):
                results = await router.deep_probe()
            from rich.table import Table
            table = Table(title="Live Provider Probe")
            table.add_column("Provider", style="yellow")
            table.add_column("Status", justify="center")
            table.add_column("Model / Reason", style="dim", max_width=90)
            table.add_column("Latency", justify="right")
            working = 0
            for name, r in results.items():
                if r["ok"]:
                    working += 1
                    table.add_row(name, "[green]✓ WORKS[/green]", r["model"], f"{r['latency_s']}s")
                else:
                    table.add_row(name, f"[red]✗ {r['stage'].upper()}[/red]", r["reason"], "—")
            console.print(table)
            console.print(f"\n[bold]{working}/{len(results)} providers actually working[/bold]")
        asyncio.run(run_deep_probe())
    else:
        console.print(f"\n[bold]Provider Health:[/bold] [dim](key/config check only — use --live for real access verification)[/dim]")
        async def run_health_checks():
            results = await router.get_status()
            for name, stat in results.items():
                if stat["ok"]:
                    console.print(f"  [success]✓[/success] {name.ljust(10)}: READY")
                else:
                    console.print(f"  [error]✗[/error] {name.ljust(10)}: FAILED ({stat.get('reason')})")
        asyncio.run(run_health_checks())

    console.print("\n[info]Diagnosis complete.[/info]\n")

@app.command()
def test():
    """Run automated tests."""
    import pytest
    console.print("[info]Running Forge Tests...[/info]")
    sys.exit(pytest.main(["tests"]))

@app.command()
def models():
    """List all supported models and their current status."""
    status()

# ── Gateway (Phase 1) ──────────────────────────────────────────────────────
gateway_app = typer.Typer(help="Run the Forge gateway and manage virtual keys.")
app.add_typer(gateway_app, name="gateway")


@gateway_app.command("serve")
def gateway_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8080, "--port", "-p", help="Port"),
):
    """Serve the Anthropic-compatible gateway.

    Point Claude Code at it with:
      ANTHROPIC_BASE_URL=http://HOST:PORT ANTHROPIC_API_KEY=fk-... claude
    """
    import uvicorn
    from forge_gateway import create_app
    from forge_gateway.compress import compression_available

    console.print(f"[info]forge-gateway on http://{host}:{port}[/info]")
    console.print(f"[info]compression: {'on' if compression_available() else 'off (headroom crusher unavailable)'}[/info]")
    console.print(f"[info]Claude Code:[/info] ANTHROPIC_BASE_URL=http://{host}:{port} ANTHROPIC_API_KEY=<fk-key> claude")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


keys_app = typer.Typer(help="Manage gateway virtual keys.")
gateway_app.add_typer(keys_app, name="keys")


def _store():
    from forge_gateway.store import GatewayStore
    return GatewayStore()


@keys_app.command("create")
def keys_create(
    name: str = typer.Argument(..., help="Unique name for the key"),
    models: Optional[str] = typer.Option(None, "--models", help="Comma-separated allow-list (default: all)"),
):
    """Create a virtual key. The plaintext key is shown ONCE."""
    allowed = [m.strip() for m in models.split(",")] if models else None
    try:
        key = _store().create_key(name, allowed_models=allowed)
    except Exception as e:
        console.print(f"[error]Could not create key:[/error] {e}")
        raise typer.Exit(1)
    console.print(f"[info]Virtual key '{name}' created — copy it now, it is not stored:[/info]")
    console.print(f"\n  {key}\n")


@keys_app.command("list")
def keys_list():
    """List virtual keys (prefixes only)."""
    rows = _store().list_keys()
    if not rows:
        console.print("[info]No keys yet. Create one: forge gateway keys create <name>[/info]")
        return
    for r in rows:
        state = "disabled" if r["disabled"] else "active"
        allowed = ",".join(r["allowed_models"]) if r["allowed_models"] else "all"
        console.print(f"  {r['prefix']}…  {r['name']:20} [{state}]  models={allowed}")


@keys_app.command("revoke")
def keys_revoke(name: str = typer.Argument(..., help="Key name to revoke")):
    """Disable a virtual key by name."""
    if _store().revoke(name):
        console.print(f"[info]Revoked '{name}'.[/info]")
    else:
        console.print(f"[error]No key named '{name}'.[/error]")


@gateway_app.command("top")
def gateway_top(days: int = typer.Option(7, "--days", "-d", help="Window in days")):
    """Show usage per virtual key (estimated tokens)."""
    rows = _store().top(days=days)
    if not rows:
        console.print(f"[info]No usage in the last {days}d.[/info]")
        return
    console.print(f"[info]Usage — last {days}d (token counts are estimates):[/info]")
    console.print(f"  {'key':20} {'reqs':>6} {'in_tok':>9} {'out_tok':>9} {'avg_ms':>8} {'ok':>5}")
    for r in rows:
        console.print(
            f"  {r['key_name']:20} {r['requests']:>6} {r['prompt_tokens']:>9} "
            f"{r['completion_tokens']:>9} {r['avg_latency_ms']:>8} {r['ok']:>5}"
        )


def main():
    """Entry point for the console script."""
    try:
        app()
    except Exception as e:
        print(f"Fatal Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
