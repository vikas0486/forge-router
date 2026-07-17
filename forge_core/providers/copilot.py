import asyncio
import logging
from typing import Optional, Dict, Any
from forge_core.providers.base import BaseProvider, ProviderResponse
from forge_core.config.settings import settings

logger = logging.getLogger("forge_core.providers.copilot")

class CopilotProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="copilot", priority=5, max_context_chars=60_000)

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        try:
            process = await asyncio.create_subprocess_exec(
                "copilot", "-p", prompt, "--allow-all", "-s",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                raise ValueError(f"Copilot CLI timed out after {timeout}s")

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                raise ValueError(f"Copilot CLI failed (exit {process.returncode}): {error_msg}")

            content = stdout.decode().strip()
            content = self._validate_content(content)
            return ProviderResponse(provider=self.name, content=content)
        except Exception as e:
            logger.error(f"Copilot error: {str(e)}")
            raise

    async def check_health(self) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                "copilot", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode != 0:
                return {"ok": False, "reason": "copilot CLI not found in PATH"}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
