import asyncio
import logging
from typing import Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.config.settings import settings

logger = logging.getLogger("forge.providers.gemini")

class GeminiProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="gemini", priority=1)

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 30) -> ProviderResponse:
        logger.debug(f"Calling Gemini CLI for prompt: {prompt[:50]}...")
        try:
            # Use the 'gemini' CLI as per the existing ai-router implementation
            process = await asyncio.create_subprocess_exec(
                "gemini", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                raise ValueError(f"Gemini CLI timed out after {timeout}s")

            if process.returncode != 0:
                error_msg = stderr.decode().strip()
                raise ValueError(f"Gemini CLI failed (exit {process.returncode}): {error_msg}")

            content = self._validate_content(stdout.decode().strip())
            return ProviderResponse(provider=self.name, content=content)
        except Exception as e:
            logger.error(f"Gemini error: {str(e)}")
            raise

    async def check_health(self) -> Dict[str, Any]:
        if not settings.gemini_api_key:
            return {"ok": False, "reason": "Missing GEMINI_API_KEY"}
        
        try:
            # Check if gemini command exists
            process = await asyncio.create_subprocess_exec(
                "which", "gemini",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode != 0:
                return {"ok": False, "reason": "gemini CLI not found in PATH"}
            
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}
