"""Environment-driven defaults for provider examples."""

import os
from dataclasses import dataclass

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DEVICE = "cpu"
DEFAULT_EMBEDDING_BATCH_SIZE = 1
DEFAULT_EMBEDDING_NORMALIZE = True
DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_TEMPERATURE = 0.0


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


@dataclass(frozen=True)
class ProviderExampleConfig:
    embedding_model: str = os.getenv("NLWEB_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    embedding_device: str = os.getenv("NLWEB_EMBEDDING_DEVICE", DEFAULT_EMBEDDING_DEVICE)
    embedding_batch_size: int = env_int("NLWEB_EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE)
    embedding_normalize: bool = env_bool("NLWEB_EMBEDDING_NORMALIZE", DEFAULT_EMBEDDING_NORMALIZE)
    llm_model: str = os.getenv("NLWEB_OPENROUTER_MODEL", DEFAULT_LLM_MODEL)
    openrouter_base_url: str = os.getenv("NLWEB_OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)
    llm_temperature: float = env_float("NLWEB_LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE)


def get_config() -> ProviderExampleConfig:
    """Read provider-example runtime overrides from the current environment."""
    return ProviderExampleConfig(
        embedding_model=os.getenv("NLWEB_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        embedding_device=os.getenv("NLWEB_EMBEDDING_DEVICE", DEFAULT_EMBEDDING_DEVICE),
        embedding_batch_size=env_int("NLWEB_EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE),
        embedding_normalize=env_bool("NLWEB_EMBEDDING_NORMALIZE", DEFAULT_EMBEDDING_NORMALIZE),
        llm_model=os.getenv("NLWEB_OPENROUTER_MODEL", DEFAULT_LLM_MODEL),
        openrouter_base_url=os.getenv("NLWEB_OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL),
        llm_temperature=env_float("NLWEB_LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE),
    )
