import asyncio
import os
import shutil
import httpx
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.claude")

# Claude via the user's PAID Claude subscription (Claude Code CLI), not prepaid
# API credits. `claude -p` print mode uses the subscription login / the
# CLAUDE_CODE_OAUTH_TOKEN from credentials/.env. Raw Anthropic API is kept as a
# fallback ONLY if a real console API key (with credits) is ever configured.

CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"


class ClaudeProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="claude", priority=3, max_context_chars=200_000)  # CLI arg-length bound
        self.api_url = "https://api.anthropic.com/v1/messages"

    def _cli_available(self) -> bool:
        return bool(shutil.which("claude") or os.path.exists(CLAUDE_BIN))

    def _cli_env(self) -> Dict[str, str]:
        """Child env for the claude CLI: force subscription auth.
        Strips ANTHROPIC_API_KEY so a stale/console key can't hijack billing,
        and passes the Claude Code OAuth token when configured."""
        env = {
            k: v for k, v in os.environ.items()
            if not (k.startswith("ANTHROPIC") or k.startswith("CLAUDE"))
        }
        token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return env

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if self._cli_available():
            return await self._generate_cli(prompt, timeout)
        if settings.anthropic_api_key:
            return await self._generate_api(prompt, timeout)
        raise ValueError("claude CLI not installed and no ANTHROPIC_API_KEY configured")

    async def _generate_cli(self, prompt: str, timeout: int) -> ProviderResponse:
        # CLI startup is heavy (~5-10s) — give it headroom within the 60s wall clock
        effective_timeout = max(timeout, 55)
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, "-p", prompt,
            stdin=asyncio.subprocess.DEVNULL,   # claude -p waits for stdin EOF on an open pipe
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._cli_env(),
            cwd=os.path.expanduser("~"),   # neutral cwd — don't ingest whatever project forge runs from
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=effective_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError(f"claude CLI timed out after {effective_timeout}s")

        if proc.returncode != 0:
            raise ValueError(f"claude CLI exited {proc.returncode}: {stderr.decode()[:200]}")

        content = stdout.decode().strip()
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model="claude-code")

    async def _generate_api(self, prompt: str, timeout: int) -> ProviderResponse:
        headers = {
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            if response.status_code != 200:
                raise ValueError(f"Claude API error ({response.status_code}): {response.text}")
            data = response.json()
            content = self._validate_content(data["content"][0]["text"])
            return ProviderResponse(provider=self.name, content=content, model=data.get("model"))

    async def check_health(self) -> Dict[str, Any]:
        if self._cli_available():
            return {"ok": True, "backend": "claude-code CLI (subscription)"}
        if settings.anthropic_api_key:
            return {"ok": True, "backend": "anthropic API (prepaid credits)"}
        return {"ok": False, "reason": "claude CLI not installed and no API key"}
