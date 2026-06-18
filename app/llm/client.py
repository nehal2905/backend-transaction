"""Gemini wrapper: JSON-mode calls with tenacity exponential-backoff retry.

This module is the single boundary to the one external dependency that can fail.
Callers get back parsed JSON or a raised exception after retries are exhausted;
the pipeline decides how to degrade gracefully.
"""

import json
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


class LLMError(Exception):
    """Raised when the LLM call fails or returns unparseable output."""


class LLMNotConfigured(LLMError):
    """Raised when no API key is configured."""


def _is_retryable(exc: BaseException) -> bool:
    # Retry transient LLM failures, but not a missing-key config error
    # (it will never succeed on retry — fail fast and let callers degrade).
    return isinstance(exc, LLMError) and not isinstance(exc, LLMNotConfigured)


def _retry_decorator():
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
    )


@_retry_decorator()
def call_gemini_json(prompt: str, response_schema: dict | None = None) -> dict:
    """Call Gemini forcing JSON output. Returns the parsed dict.

    Retries (exp backoff, max attempts = settings.llm_max_retries) on transient
    failures. Raises LLMError on final failure or unparseable output.
    """
    if not settings.gemini_api_key:
        # Configuration errors are not retryable; raise a distinct type so the
        # retry predicate (LLMError subclass) still applies but message is clear.
        raise LLMNotConfigured("GEMINI_API_KEY is not set")

    url = GEMINI_URL.format(model=settings.gemini_model)
    generation_config: dict = {"response_mime_type": "application/json"}
    if response_schema is not None:
        generation_config["response_schema"] = response_schema

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }

    try:
        resp = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"HTTP error calling Gemini: {exc}") from exc

    if resp.status_code >= 500 or resp.status_code == 429:
        raise LLMError(f"Gemini transient error {resp.status_code}: {resp.text[:300]}")
    if resp.status_code != 200:
        # 4xx (other than 429) are not transient, but still surface as LLMError so
        # the pipeline degrades gracefully rather than crashing the job.
        raise LLMError(f"Gemini error {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Unexpected Gemini response shape: {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini returned non-JSON content: {exc}") from exc
