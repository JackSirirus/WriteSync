"""
WriteSync Provider Configuration Data Model

Defines AIProviderConfig and ProviderRegistry for multi-source LLM support.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("writesync")


@dataclass
class AIProviderConfig:
    """Configuration for a single AI provider endpoint."""

    name: str  # "openai", "deepseek", "ollama", etc.
    provider_type: str  # "openai", "anthropic", "ollama", "custom"
    base_url: str
    api_key: str = ""
    default_model: str = ""
    max_tokens: int = 4096
    context_window: int = 128000
    is_default: bool = False

    @staticmethod
    def create_ollama(
        model: str = "llama3", base_url: str = "http://localhost:11434/v1"
    ) -> AIProviderConfig:
        """Factory method to create an Ollama local provider config."""
        return AIProviderConfig(
            name="ollama",
            provider_type="ollama",
            base_url=base_url,
            default_model=model,
        )

    def to_dict(self, mask_key: bool = False) -> dict:
        """Serialize to dict.  If mask_key=True, api_key is replaced with ****."""
        d = asdict(self)
        if mask_key:
            d["api_key"] = "****" if self.api_key else ""
        return d

    @classmethod
    def from_dict(cls, data: dict) -> AIProviderConfig:
        """Deserialize from dict."""
        # Filter unknown keys to stay forward-compatible
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class ProviderRegistry:
    """Holds all configured providers and provides lookup helpers."""

    providers: list[AIProviderConfig] = field(default_factory=list)

    def get_default(self) -> Optional[AIProviderConfig]:
        """Return the provider marked as default, or the first provider, or None."""
        for p in self.providers:
            if p.is_default:
                return p
        return self.providers[0] if self.providers else None

    def get_by_name(self, name: str) -> Optional[AIProviderConfig]:
        """Lookup by provider name (case-insensitive)."""
        name_lower = name.lower()
        for p in self.providers:
            if p.name.lower() == name_lower:
                return p
        return None

    def add(self, config: AIProviderConfig) -> None:
        """Add a new provider.  If it is the first provider, auto-mark as default."""
        # Remove existing provider with same name to avoid duplicates
        self.remove(config.name)
        self.providers.append(config)
        if len(self.providers) == 1:
            config.is_default = True

    def remove(self, name: str) -> bool:
        """Remove a provider by name.  Returns True if removed."""
        name_lower = name.lower()
        original_len = len(self.providers)
        self.providers = [p for p in self.providers if p.name.lower() != name_lower]
        removed = len(self.providers) < original_len
        if removed and self.providers and not any(p.is_default for p in self.providers):
            self.providers[0].is_default = True
        return removed

    def set_default(self, name: str) -> bool:
        """Mark a provider as default.  Returns True if found."""
        target = self.get_by_name(name)
        if target is None:
            return False
        for p in self.providers:
            p.is_default = False
        target.is_default = True
        return True

    def to_dict(self, mask_key: bool = False) -> dict:
        return {"providers": [p.to_dict(mask_key=mask_key) for p in self.providers]}

    @classmethod
    def from_dict(cls, data: dict) -> ProviderRegistry:
        providers = [AIProviderConfig.from_dict(p) for p in data.get("providers", [])]
        return cls(providers=providers)

    def __len__(self) -> int:
        return len(self.providers)

    def __iter__(self):
        return iter(self.providers)
