# utils/ai_client.py
"""
Thin, shared wrapper around the Groq client so every AI cog doesn't
re-implement client creation and error handling slightly differently.
"""
from __future__ import annotations

import logging
import os

from groq import Groq

from config import GROQ_MODEL_ID

log = logging.getLogger("nextermc.ai")

_client: Groq | None = None


class AIConfigError(RuntimeError):
    """Raised when the bot is asked to use AI features but isn't configured for them."""


class AIResponseError(RuntimeError):
    """Raised when the AI provider returns an empty or unusable response."""


def get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise AIConfigError(
                "GROQ_API_KEY is not set. AI-powered commands are disabled until it is configured."
            )
        _client = Groq(api_key=api_key)
    return _client


async def ask(
    prompt: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    response_format: dict | None = None,
) -> str:
    """
    Run one completion against the shared model. Synchronous under the hood
    (the groq SDK used here is sync), but every call site in this project
    awaits it via asyncio.to_thread so it never blocks the bot's event loop.
    """
    import asyncio

    client = get_client()

    def _call():
        request = {
            "model": GROQ_MODEL_ID,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if response_format is not None:
            request["response_format"] = response_format
        completion = client.chat.completions.create(**request)
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("The AI provider completed without returning report text.")
        return content.strip()

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        log.exception("Groq completion failed")
        raise
