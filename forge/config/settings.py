import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Path to the shared credentials file
SHARED_ENV_PATH = Path("/Users/vikash/Documents/Projects/credentials/.env")

class Settings(BaseSettings):
    # Gemini
    gemini_api_key: Optional[str] = None
    
    # Groq
    groq_api_key: Optional[str] = None
    
    # GitHub (Claude Code, Codex, Copilot)
    github_token: Optional[str] = None
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    
    # App Settings
    debug: bool = False
    timeout: int = 30
    
    model_config = SettingsConfigDict(
        env_file=SHARED_ENV_PATH if SHARED_ENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
