import asyncio
import logging
import os
import shutil
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.antigravity")

# Resolve agy binary: PATH lookup first, then platform-agnostic home dir fallback.
_AGY_LOCAL = Path(os.environ.get("AGY_BIN", str(Path.home() / ".local" / "bin" / "agy")))
AGY_BIN = shutil.which("agy") or str(_AGY_LOCAL)


class AntigravityProvider(BaseProvider):
    """Antigravity is Gemini-Flash based. The `agy` CLI's headless --print mode
    stalls (auth succeeds but no piped output), so we call the Gemini REST API
    directly when a GEMINI_API_KEY is available, and only fall back to the agy
    CLI when no usable key is configured."""

    def __init__(self):
        super().__init__(name="antigravity", priority=0)
        self.model = "gemini-2.5-flash"
        self.gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def _has_rest_key(self) -> bool:
        key = settings.gemini_api_key or ""
        return bool(key) and not key.startswith("AQ.")  # AQ. = CLI auth token, not a REST key

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if self._has_rest_key():
            return await self._gemini(prompt, image, timeout)
        return await self._agy(prompt, timeout)

    async def _gemini(self, prompt: str, image: Optional[Dict[str, Any]], timeout: int) -> ProviderResponse:
        parts = [{"text": prompt}]
        if image and "data" in image and "mime_type" in image:
            parts.append({"inlineData": {"mimeType": image["mime_type"], "data": image["data"]}})
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.gemini_url}?key={settings.gemini_api_key}", json={"contents": [{"parts": parts}]})
            if resp.status_code != 200:
                raise ValueError(f"Antigravity (Gemini) error ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            try:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                raise ValueError(f"Unexpected Antigravity response: {str(data)[:200]}")
            return ProviderResponse(provider=self.name, content=self._validate_content(content), model=f"{self.model} (antigravity)")

    async def _agy(self, prompt: str, timeout: int) -> ProviderResponse:
        if not shutil.which("agy") and not os.path.exists(AGY_BIN):
            raise ValueError("agy CLI not found and no GEMINI_API_KEY for REST fallback")
        proc = await asyncio.create_subprocess_exec(
            AGY_BIN, "--print", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError(f"agy timed out after {timeout}s")
        if proc.returncode != 0:
            raise ValueError(f"agy exited {proc.returncode}: {stderr.decode()[:200]}")
        content = stdout.decode().strip()
        return ProviderResponse(provider=self.name, content=self._validate_content(content), model="agy")

    async def check_health(self) -> Dict[str, Any]:
        if self._has_rest_key():
            return {"ok": True}
        if shutil.which("agy") or os.path.exists(AGY_BIN):
            return {"ok": True}
        return {"ok": False, "reason": "No GEMINI_API_KEY and agy CLI not available"}
