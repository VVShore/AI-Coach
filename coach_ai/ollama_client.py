"""
ollama_client.py
=================
Thin, dedicated wrapper around the Ollama REST API (/api/generate).

Responsibilities of this module and ONLY this module:
  - Send prompts to Ollama.
  - Surface network/timeout errors as a typed exception.
  - Report basic timing/token metadata for logging.

It does NOT know about JSON schemas, retries-on-validation-failure, or
prompt templates -- that orchestration lives in pipeline.py. Keeping
this module dumb makes it trivial to swap in a different backend
(OpenAI-compatible endpoint, llama.cpp server, etc.) later without
touching the rest of the system.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from config import OllamaConfig
from utils import approx_token_count


class OllamaError(Exception):
    """Raised when Ollama is unreachable, times out, or returns a
    non-2xx / malformed HTTP response. This is distinct from a JSON
    validation failure (that's a valid HTTP response with content the
    schema rejects, handled in json_validator.py / pipeline.py)."""


@dataclass
class OllamaResponse:
    text: str
    prompt_tokens_est: int
    response_tokens_est: int
    duration_seconds: float
    model: str
    done: bool


class OllamaClient:
    """Stateless-ish client; holds only configuration, no mutable
    request state, so a single instance is safe to reuse across every
    stage of the pipeline."""

    def __init__(self, config: OllamaConfig):
        self._config = config

    def generate(self, prompt: str, system: str = "") -> OllamaResponse:
        """
        Send a single-shot generation request to Ollama and return the
        raw text response plus timing/size metadata.

        Raises OllamaError on any transport-level failure (connection
        refused, timeout, non-200, malformed response body). Callers
        should let this propagate -- the pipeline treats an
        OllamaError as fatal for the current run rather than something
        to retry indefinitely, since it usually means the server is
        down or misconfigured rather than a one-off bad generation.
        """
        payload = {
            "model": self._config.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": self._config.temperature,
                "num_ctx": self._config.context_length,
            },
        }

        import time

        start = time.monotonic()
        try:
            resp = requests.post(
                self._config.generate_url,
                json=payload,
                timeout=self._config.timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise OllamaError(
                f"Ollama request timed out after {self._config.timeout_seconds}s "
                f"(model={self._config.model})"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError(
                f"Could not connect to Ollama at {self._config.host}. "
                f"Is `ollama serve` running?"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        duration = time.monotonic() - start

        if resp.status_code != 200:
            raise OllamaError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:500]}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama response was not valid JSON: {exc}") from exc

        text = body.get("response")
        if text is None:
            raise OllamaError(f"Ollama response missing 'response' field: {body}")

        return OllamaResponse(
            text=text,
            prompt_tokens_est=body.get("prompt_eval_count", approx_token_count(prompt)),
            response_tokens_est=body.get("eval_count", approx_token_count(text)),
            duration_seconds=duration,
            model=self._config.model,
            done=bool(body.get("done", True)),
        )

    def check_connection(self) -> bool:
        """Lightweight health check hitting Ollama's tags endpoint.
        Used by main.py to fail fast with a clear message instead of
        burning through Stage 1 retries against a dead server."""
        base = self._config.host.rstrip("/")
        try:
            resp = requests.get(f"{base}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            return False
