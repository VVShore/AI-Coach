"""
config.py
=========
Central configuration for the Coach AI system.

All paths, Ollama parameters, and pipeline behavior knobs live here.
Every value can be overridden with an environment variable so you can
run the same code against different vaults/models without editing
source. Defaults are sane for a local Ollama install.

Nothing in this module talks to disk or network -- it is pure
configuration construction, which keeps it trivially testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    return int(val) if val is not None else default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    return float(val) if val is not None else default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class OllamaConfig:
    """Configuration for talking to a local Ollama server."""

    host: str = field(default_factory=lambda: _env_str("OLLAMA_HOST", "http://localhost:11434"))
    model: str = field(default_factory=lambda: _env_str("OLLAMA_MODEL", "llama3.1:8b"))
    context_length: int = field(default_factory=lambda: _env_int("OLLAMA_NUM_CTX", 8192))
    temperature: float = field(default_factory=lambda: _env_float("OLLAMA_TEMPERATURE", 0.2))
    timeout_seconds: int = field(default_factory=lambda: _env_int("OLLAMA_TIMEOUT", 180))
    max_retries: int = field(default_factory=lambda: _env_int("OLLAMA_MAX_RETRIES", 3))

    @property
    def generate_url(self) -> str:
        return f"{self.host.rstrip('/')}/api/generate"


@dataclass(frozen=True)
class VaultConfig:
    """Paths inside the Obsidian vault. All derived from vault_root so
    the whole layout moves together if the vault is relocated."""

    vault_root: Path = field(
        default_factory=lambda: Path(_env_str("VAULT_ROOT", "./Obsidian Vault"))
    )

    @property
    def daily_journal_dir(self) -> Path:
        return self.vault_root / "Daily Journal"

    @property
    def trade_journal_dir(self) -> Path:
        return self.vault_root / "Trade Journal"

    @property
    def ai_dir(self) -> Path:
        return self.vault_root / "AI"

    @property
    def memory_dir(self) -> Path:
        return self.ai_dir / "Memory"

    @property
    def weekly_reviews_dir(self) -> Path:
        return self.ai_dir / "Weekly Reviews"

    @property
    def templates_dir(self) -> Path:
        return self.vault_root / "Templates"

    # Individual memory files -----------------------------------------
    @property
    def identity_profile_path(self) -> Path:
        return self.memory_dir / "identity_profile.md"

    @property
    def active_goals_path(self) -> Path:
        return self.memory_dir / "active_goals.md"

    @property
    def behavioral_hypotheses_path(self) -> Path:
        return self.memory_dir / "behavioral_hypotheses.md"

    @property
    def observed_patterns_path(self) -> Path:
        return self.memory_dir / "observed_patterns.md"

    @property
    def productive_patterns_path(self) -> Path:
        """Deprecated alias for observed_patterns_path, kept for
        backwards compatibility with any code/tests still referencing
        the old 'productive_patterns' naming. The AI now records
        observations rather than prematurely classifying them as
        productive, so 'observed_patterns' is the canonical name --
        this alias just points at the same path."""
        return self.observed_patterns_path

    @property
    def avoidance_patterns_path(self) -> Path:
        return self.memory_dir / "avoidance_patterns.md"

    @property
    def trader_profile_path(self) -> Path:
        return self.memory_dir / "trader_profile.md"

    def all_memory_paths(self) -> dict:
        """Name -> Path mapping for every known memory file. The keys
        here are the canonical memory-file identifiers used throughout
        the rest of the system (schemas, pipeline, markdown writer)."""
        return {
            "identity_profile": self.identity_profile_path,
            "active_goals": self.active_goals_path,
            "behavioral_hypotheses": self.behavioral_hypotheses_path,
            "observed_patterns": self.observed_patterns_path,
            "avoidance_patterns": self.avoidance_patterns_path,
            "trader_profile": self.trader_profile_path,
        }

    def ensure_directories_exist(self) -> None:
        """Create any vault directories that don't exist yet. Called
        once at startup so a fresh vault doesn't crash the pipeline."""
        for d in (
            self.daily_journal_dir,
            self.trade_journal_dir,
            self.ai_dir,
            self.memory_dir,
            self.weekly_reviews_dir,
            self.templates_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class PipelineConfig:
    """Knobs controlling pipeline execution, retries, and file layout
    of the Python project itself (as opposed to the vault)."""

    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    logs_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "logs"
    )
    prompts_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "prompts"
    )
    intermediate_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "logs" / "intermediate"
    )
    max_json_retries: int = field(default_factory=lambda: _env_int("MAX_JSON_RETRIES", 3))
    week_starts_on_monday: bool = field(
        default_factory=lambda: _env_bool("WEEK_STARTS_MONDAY", True)
    )

    def ensure_directories_exist(self) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    """Top-level configuration bundle passed around the whole app."""

    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    def ensure_directories_exist(self) -> None:
        self.vault.ensure_directories_exist()
        self.pipeline.ensure_directories_exist()


def load_config() -> Config:
    """Factory used by main.py. Centralizes construction behind one
    function so tests (or future config-file loading) only need to
    monkeypatch this single entry point."""
    return Config()
