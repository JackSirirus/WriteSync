"""
Usage Tracker — Phase 6 LLM token usage tracking

Intercepts LLM calls to track token usage:
- UsageRecord dataclass: timestamp, project_id, agent_name, model, prompt_tokens, completion_tokens, latency_ms, provider
- UsageTracker class (singleton): record_call(), get_project_stats(project_id), get_global_stats()
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("writesync")

# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class UsageRecord:
    """Single LLM call usage record."""

    timestamp: str = ""                    # ISO timestamp
    project_id: str = ""                   # FK to project
    agent_name: str = ""                   # which agent made the call
    model: str = ""                        # model name
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0                    # milliseconds
    provider: str = "opencode"            # provider name

    @classmethod
    def now(cls, **kwargs) -> "UsageRecord":
        return cls(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            **kwargs,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UsageRecord":
        return cls(**{k: d.get(k, "") for k in [
            "timestamp", "project_id", "agent_name", "model",
            "prompt_tokens", "completion_tokens", "latency_ms", "provider",
        ]})


# ─────────────────────────────────────────────────────────────
# Singleton Tracker
# ─────────────────────────────────────────────────────────────

class UsageTracker:
    """Singleton usage tracker. Thread-safe."""

    _instance: Optional["UsageTracker"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._records: list[UsageRecord] = []
                    obj._storage_path: Path = Path("projects") / "_usage.jsonl"
                    obj._load()
                    cls._instance = obj
        return cls._instance

    def _load(self):
        """Load existing records from JSONL file."""
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._records.append(UsageRecord.from_dict(json.loads(line)))
                            except Exception:
                                pass
            except Exception as e:
                logger.warning("Failed to load usage records: %s", e)

    def _save(self, record: UsageRecord):
        """Append a single record to JSONL file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to save usage record: %s", e)

    def record_call(
        self,
        project_id: str = "",
        agent_name: str = "",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        provider: str = "opencode",
    ):
        """Record a single LLM call."""
        record = UsageRecord.now(
            project_id=project_id,
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            provider=provider,
        )
        self._records.append(record)
        self._save(record)

    def get_project_stats(self, project_id: str) -> dict:
        """Get usage statistics for a specific project."""
        records = [r for r in self._records if r.project_id == project_id]
        return self._compute_stats(records)

    def get_global_stats(self) -> dict:
        """Get global usage statistics."""
        return self._compute_stats(self._records)

    def get_all_records(self, project_id: str = "") -> list[dict]:
        """Get all records, optionally filtered by project."""
        records = [r for r in self._records if r.project_id == project_id] if project_id else list(self._records)
        return [r.to_dict() for r in records]

    def _compute_stats(self, records: list[UsageRecord]) -> dict:
        """Compute aggregate stats from records."""
        if not records:
            return {
                "total_calls": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_latency_ms": 0,
                "per_agent": {},
                "per_model": {},
            }

        total_prompt = sum(r.prompt_tokens for r in records)
        total_completion = sum(r.completion_tokens for r in records)
        total_tokens = total_prompt + total_completion
        total_calls = len(records)

        # Estimated cost: $0.001 per 1K tokens (rough average)
        cost_per_1k = 0.001
        total_cost = (total_tokens / 1000) * cost_per_1k

        avg_latency = sum(r.latency_ms for r in records) / total_calls if total_calls else 0

        # Per agent breakdown
        per_agent = {}
        for r in records:
            agent = r.agent_name or "unknown"
            if agent not in per_agent:
                per_agent[agent] = {"calls": 0, "tokens": 0, "cost": 0.0}
            agent_tokens = r.prompt_tokens + r.completion_tokens
            per_agent[agent]["calls"] += 1
            per_agent[agent]["tokens"] += agent_tokens
            per_agent[agent]["cost"] += (agent_tokens / 1000) * cost_per_1k

        # Per model breakdown
        per_model = {}
        for r in records:
            model = r.model or "unknown"
            if model not in per_model:
                per_model[model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            model_tokens = r.prompt_tokens + r.completion_tokens
            per_model[model]["calls"] += 1
            per_model[model]["tokens"] += model_tokens
            per_model[model]["cost"] += (model_tokens / 1000) * cost_per_1k

        return {
            "total_calls": total_calls,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "avg_latency_ms": round(avg_latency, 0),
            "per_agent": per_agent,
            "per_model": per_model,
        }

    def reset(self):
        """Clear all records (for testing)."""
        self._records = []
        if self._storage_path.exists():
            try:
                self._storage_path.unlink()
            except Exception:
                pass
