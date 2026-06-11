import asyncio
import logging
from typing import List, Optional, Dict, Any
from forge.providers.base import BaseProvider, ProviderResponse
from forge.providers.gemini import GeminiProvider
from forge.providers.groq import GroqProvider
from forge.providers.claude import ClaudeProvider
from forge.providers.copilot import CopilotProvider
from forge.providers.openai import OpenAIProvider
from forge.providers.codex import CodexProvider
from forge.providers.ollama import OllamaProvider

logger = logging.getLogger("forge.router")

class RouterEngine:
    def __init__(self):
        self.providers: List[BaseProvider] = [
            GeminiProvider(),
            GroqProvider(),
            ClaudeProvider(),
            CodexProvider(),
            CopilotProvider(),
            OpenAIProvider(),
            OllamaProvider()
        ]
        # Sort by priority
        self.providers.sort(key=lambda x: x.priority)

    async def route(self, prompt: str, preferred: Optional[str] = None, timeout: int = 30, on_progress: Optional[callable] = None, image: Optional[Dict[str, Any]] = None) -> ProviderResponse:
        # 1. Handle preferred provider
        if preferred:
            provider = next((p for p in self.providers if p.name == preferred), None)
            if provider:
                if on_progress:
                    on_progress(provider=provider.name, status="Using preferred provider...")
                logger.info(f"Using preferred provider: {preferred}")
                try:
                    return await provider.generate(prompt, timeout=timeout, image=image)
                except Exception as e:
                    if on_progress:
                        on_progress(failed_provider=provider.name, status="Preferred provider failed, falling back...")
                    logger.warning(f"Preferred provider {preferred} failed: {str(e)}")
            else:
                logger.warning(f"Preferred provider {preferred} not found, falling back.")

        # 2. Fallback chain
        for provider in self.providers:
            try:
                if on_progress:
                    on_progress(provider=provider.name, status="Trying provider...")
                
                # Check health first (quick check)
                health = await provider.check_health()
                if not health["ok"]:
                    if on_progress:
                        on_progress(failed_provider=provider.name, status=f"Skipping (unhealthy: {health.get('reason')})")
                    logger.debug(f"Skipping {provider.name}: {health.get('reason')}")
                    continue

                logger.info(f"Trying provider: {provider.name}")
                response = await provider.generate(prompt, timeout=timeout, image=image)
                return response
            except Exception as e:
                if on_progress:
                    on_progress(failed_provider=provider.name, status="Provider failed, trying next...")
                logger.error(f"Provider {provider.name} failed: {str(e)}")
                continue

        raise ValueError("All providers failed to generate a response.")

    async def get_status(self) -> Dict[str, Dict[str, Any]]:
        results = {}
        for provider in self.providers:
            results[provider.name] = await provider.check_health()
        return results

router = RouterEngine()
