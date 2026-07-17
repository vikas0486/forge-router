import asyncio
import logging
import shutil
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse

logger = logging.getLogger("forge_core.providers.antigravity")

AGY_BIN = shutil.which("agy") or "/Users/vikash/.local/bin/agy"

class AntigravityProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="antigravity", priority=0)

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        if not shutil.which("agy") and not __import__("os").path.exists(AGY_BIN):
            raise ValueError("agy CLI not found")

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
        import os
        if not (shutil.which("agy") or os.path.exists(AGY_BIN)):
            return {"ok": False, "reason": "agy CLI not installed"}
        return {"ok": True}
