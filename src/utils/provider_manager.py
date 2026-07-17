"""
WriteSync Provider Manager

CRUD operations for AI provider configurations with encrypted API keys.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

from src.utils.provider_config import AIProviderConfig, ProviderRegistry

logger = logging.getLogger("writesync")

# Default storage paths
_DEFAULT_CONFIG_DIR = Path.home() / ".writesync"
_PROVIDERS_FILE = _DEFAULT_CONFIG_DIR / "providers.json"
_KEY_FILE = _DEFAULT_CONFIG_DIR / ".key"


class ProviderManager:
    """Manages provider configurations: load, save, CRUD, encryption, test."""

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        providers_file: Optional[Path] = None,
        key_file: Optional[Path] = None,
    ):
        self.config_dir = Path(config_dir) if config_dir else _DEFAULT_CONFIG_DIR
        self.providers_file = Path(providers_file) if providers_file else _PROVIDERS_FILE
        self.key_file = Path(key_file) if key_file else _KEY_FILE
        self._registry: ProviderRegistry = ProviderRegistry()
        self._fernet = None
        self._encryption_available = False
        self._init_encryption()
        self.load()

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _init_encryption(self) -> None:
        """Try to initialise Fernet encryption; fall back to base64 on failure."""
        try:
            from cryptography.fernet import Fernet

            if self.key_file.exists():
                key = self.key_file.read_bytes()
                self._fernet = Fernet(key)
                self._encryption_available = True
            else:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key()
                self.key_file.write_bytes(key)
                self._fernet = Fernet(key)
                self._encryption_available = True
                logger.info("Generated new Fernet key at %s", self.key_file)
        except ImportError:
            logger.warning(
                "cryptography not installed; API keys will be stored as base64 (not secure). "
                "Install with: pip install cryptography"
            )
            self._encryption_available = False
        except Exception as e:
            logger.warning("Encryption init failed (%s); falling back to base64", e)
            self._encryption_available = False

    def _encrypt(self, plaintext: str) -> str:
        if self._encryption_available and self._fernet:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return base64.b64encode(plaintext.encode("utf-8")).decode("utf-8")

    def _decrypt(self, ciphertext: str) -> str:
        if self._encryption_available and self._fernet:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        return base64.b64decode(ciphertext.encode("utf-8")).decode("utf-8")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> ProviderRegistry:
        """Load registry from disk.  Returns empty registry if file missing."""
        if not self.providers_file.exists():
            self._registry = ProviderRegistry()
            return self._registry
        try:
            raw = json.loads(self.providers_file.read_text(encoding="utf-8"))
            self._registry = ProviderRegistry.from_dict(raw)
            # Decrypt api_keys
            for p in self._registry.providers:
                if p.api_key:
                    try:
                        p.api_key = self._decrypt(p.api_key)
                    except Exception as e:
                        logger.warning("Failed to decrypt api_key for %s: %s", p.name, e)
            logger.info("Loaded %d provider(s)", len(self._registry))
        except Exception as e:
            logger.warning("Failed to load providers: %s", e)
            self._registry = ProviderRegistry()
        return self._registry

    def save(self) -> None:
        """Persist registry to disk with encrypted api_keys."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Build a copy with encrypted keys
        encrypted_providers = []
        for p in self._registry.providers:
            d = p.to_dict()
            if d.get("api_key"):
                d["api_key"] = self._encrypt(d["api_key"])
            encrypted_providers.append(d)
        payload = {"providers": encrypted_providers}
        try:
            self.providers_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved %d provider(s)", len(self._registry))
        except Exception as e:
            logger.error("Failed to save providers: %s", e)
            raise

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @property
    def registry(self) -> ProviderRegistry:
        return self._registry

    def list_providers(self) -> list[AIProviderConfig]:
        return list(self._registry.providers)

    def get_default(self) -> Optional[AIProviderConfig]:
        return self._registry.get_default()

    def get_by_name(self, name: str) -> Optional[AIProviderConfig]:
        return self._registry.get_by_name(name)

    def add_provider(self, config: AIProviderConfig) -> None:
        """Add or replace a provider and persist."""
        self._registry.add(config)
        self.save()

    def remove_provider(self, name: str) -> bool:
        """Remove a provider by name and persist."""
        removed = self._registry.remove(name)
        if removed:
            self.save()
        return removed

    def update_provider(self, name: str, **kwargs) -> bool:
        """Update fields of an existing provider and persist."""
        existing = self._registry.get_by_name(name)
        if existing is None:
            return False
        for key, value in kwargs.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        self.save()
        return True

    def set_default(self, name: str) -> bool:
        """Mark a provider as default and persist."""
        ok = self._registry.set_default(name)
        if ok:
            self.save()
        return ok

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self, config: AIProviderConfig) -> dict:
        """
        Test connectivity to a provider by calling its models list endpoint.
        Returns {"ok": bool, "models": [...], "error": str|None}.
        """
        import urllib.request
        import urllib.error

        models: list[str] = []
        error: Optional[str] = None

        # Build the models endpoint URL
        base = config.base_url.rstrip("/")
        if not base.endswith("/v1"):
            # Some providers (Ollama) expose /v1/models under the base URL
            url = f"{base}/v1/models"
        else:
            url = f"{base}/models"

        req = urllib.request.Request(url, method="GET")
        if config.api_key:
            req.add_header("Authorization", f"Bearer {config.api_key}")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # OpenAI-compatible format: data["data"] = [{"id": "model-name"}, ...]
                raw_models = data.get("data", []) if isinstance(data, dict) else []
                if isinstance(raw_models, list):
                    models = [m.get("id", str(m)) for m in raw_models if isinstance(m, dict)]
                else:
                    models = []
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}: {e.reason}"
            # Try to read error body
            try:
                body = e.read().decode("utf-8")
                if body:
                    error += f" | {body[:200]}"
            except Exception:
                pass
        except urllib.error.URLError as e:
            error = f"Connection error: {e.reason}"
        except Exception as e:
            error = str(e)

        ok = len(models) > 0 and error is None
        return {"ok": ok, "models": models, "error": error}


# Singleton for process-wide access
_manager_instance: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Return the global ProviderManager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ProviderManager()
    return _manager_instance


def reset_provider_manager() -> None:
    """Reset the singleton (mainly for tests)."""
    global _manager_instance
    _manager_instance = None
