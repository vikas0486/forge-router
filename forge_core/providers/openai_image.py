import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
import logging

from forge_core.config.settings import settings
from forge_core.providers.base import BaseProvider, ProviderResponse

logger = logging.getLogger("forge_core.providers.openai_image")

GENERATED_DIR = Path.home() / ".forge" / "generated"
IMAGES_URL = "https://api.openai.com/v1/images/generations"
IMAGE_MODEL = "gpt-image-1"


class OpenAIImageProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="openai_image", priority=4, max_context_chars=40_000)

    def _api_key(self) -> Optional[str]:
        return settings.openai_api_key or settings.codex_api_key

    def _choose_size(self, prompt: str) -> str:
        low = prompt.lower()
        if any(k in low for k in ("landscape", "wide", "banner", "architecture", "system design")):
            return "1536x1024"
        if any(k in low for k in ("portrait", "vertical", "poster")):
            return "1024x1536"
        return "1024x1024"

    def _write_image(self, b64_json: str, prompt: str, output_format: str) -> str:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
        ext = output_format if output_format in {"png", "jpeg", "webp"} else "png"
        path = GENERATED_DIR / f"forge_{digest}.{ext}"
        path.write_bytes(base64.b64decode(b64_json))
        return path.name

    async def generate(self, prompt: str, image: Optional[Dict[str, Any]] = None, timeout: int = 60) -> ProviderResponse:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY or CODEX_API_KEY for image generation")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": IMAGE_MODEL,
            "prompt": prompt,
            "size": self._choose_size(prompt),
            "quality": "medium",
            "output_format": "png",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(IMAGES_URL, headers=headers, json=payload)
        if response.status_code != 200:
            raise ValueError(f"OpenAI image API error ({response.status_code}): {response.text[:200]}")

        data = response.json()
        items = data.get("data") or []
        if not items:
            raise ValueError("OpenAI image API returned no image data")
        item = items[0]
        b64_json = item.get("b64_json")
        if not b64_json:
            raise ValueError("OpenAI image API returned no b64_json payload")

        output_format = item.get("output_format", "png")
        filename = self._write_image(b64_json, prompt, output_format)
        markdown = (
            f"Generated image with `{IMAGE_MODEL}`.\n\n"
            f"![Generated image](/generated/{filename})"
        )
        return ProviderResponse(
            provider=self.name,
            content=markdown,
            model=IMAGE_MODEL,
            usage=self._usage_from_openai(data) or self._estimated_usage(prompt, markdown),
        )

    async def check_health(self) -> Dict[str, Any]:
        if not self._api_key():
            return {"ok": False, "reason": "Missing OPENAI_API_KEY or CODEX_API_KEY"}
        return {"ok": True, "backend": IMAGE_MODEL}
