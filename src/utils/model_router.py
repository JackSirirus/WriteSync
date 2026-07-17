"""
WriteSync Model Router

Selects optimal (provider, model) pair based on task type and user preference.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from src.utils.provider_config import AIProviderConfig, ProviderRegistry

logger = logging.getLogger("writesync")


class ModelRouter:
    """Routes task types to the best available provider/model pair."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def select(
        self, task_type: str, user_preference: Optional[str] = None
    ) -> Tuple[AIProviderConfig, str]:
        """
        Select a provider and model for the given task.

        Args:
            task_type: "orchestrator", "agent", "proofreader", etc.
            user_preference: Optional provider name override.

        Returns:
            Tuple of (AIProviderConfig, model_name).
        """
        # 1. User override takes absolute precedence
        if user_preference:
            provider = self.registry.get_by_name(user_preference)
            if provider:
                model = provider.default_model or self._fallback_model(provider.provider_type)
                logger.info("Router: user_preference=%s → %s / %s", user_preference, provider.name, model)
                return provider, model
            logger.warning("Router: user_preference=%s not found, falling back to rules", user_preference)

        # 2. Task-based routing
        if task_type == "orchestrator":
            return self._route_by_model_suffix(suffixes=["-pro", "_pro"], fallback_msg="orchestrator")
        elif task_type == "agent":
            return self._route_by_model_suffix(suffixes=["-flash", "_flash", "-fast", "_fast"], fallback_msg="agent")
        elif task_type == "proofreader":
            # proofreader → any provider's default model
            provider = self.registry.get_default()
            if provider is None:
                raise ValueError("No providers configured")
            model = provider.default_model or self._fallback_model(provider.provider_type)
            logger.info("Router: proofreader → %s / %s", provider.name, model)
            return provider, model
        else:
            # Unknown task_type → default provider
            provider = self.registry.get_default()
            if provider is None:
                raise ValueError("No providers configured")
            model = provider.default_model or self._fallback_model(provider.provider_type)
            logger.info("Router: unknown task_type=%s → %s / %s", task_type, provider.name, model)
            return provider, model

    def _route_by_model_suffix(
        self, suffixes: list[str], fallback_msg: str
    ) -> Tuple[AIProviderConfig, str]:
        """Find a provider whose default_model ends with one of the suffixes."""
        for provider in self.registry.providers:
            model = provider.default_model
            if model and any(model.lower().endswith(s.lower()) for s in suffixes):
                logger.info("Router: %s → %s / %s (suffix match)", fallback_msg, provider.name, model)
                return provider, model

        # Fallback to default provider
        provider = self.registry.get_default()
        if provider is None:
            raise ValueError("No providers configured")
        model = provider.default_model or self._fallback_model(provider.provider_type)
        logger.info("Router: %s → %s / %s (fallback)", fallback_msg, provider.name, model)
        return provider, model

    @staticmethod
    def _fallback_model(provider_type: str) -> str:
        """Return a sensible fallback model name when default_model is empty."""
        if provider_type == "anthropic":
            return "claude-sonnet-4-20250514"
        elif provider_type == "ollama":
            return "llama3"
        else:
            return "deepseek-v4-flash"
