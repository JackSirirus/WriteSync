"""
ItemLedger — Phase 4A 物品流转追踪

记录关键物品的获得、转移、消耗、丢失、销毁等交易，
提供物品历程查询和当前持有者查询。

Architecture:
  ItemLedger stores transactions via workspace.context_cache
  and persists to item_ledger.json in the project directory.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class ItemTransaction:
    """A single item possession change event."""

    item_id: str = ""                    # auto-generated
    item_name: str = ""                  # 物品名称
    action: str = "acquire"             # "acquire"|"transfer_in"|"transfer_out"|"consume"|"lose"|"destroy"
    holder: str = ""                      # 当前持有角色
    previous_holder: str = ""             # 上一持有角色
    chapter: int = 0                      # 发生章节
    quantity: int = 1                     # 数量
    note: str = ""                        # 备注（≤100字）

    def __post_init__(self):
        if not self.item_id:
            import hashlib
            raw = f"{self.item_name}:{self.action}:{self.chapter}:{self.holder}"
            self.item_id = hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "action": self.action,
            "holder": self.holder,
            "previous_holder": self.previous_holder,
            "chapter": self.chapter,
            "quantity": self.quantity,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ItemTransaction":
        return cls(
            item_id=d.get("item_id", ""),
            item_name=d.get("item_name", ""),
            action=d.get("action", "acquire"),
            holder=d.get("holder", ""),
            previous_holder=d.get("previous_holder", ""),
            chapter=d.get("chapter", 0),
            quantity=d.get("quantity", 1),
            note=d.get("note", ""),
        )


# ─────────────────────────────────────────────────────────────
# Pydantic response models for LLM structured output
# ─────────────────────────────────────────────────────────────

class TxItem(BaseModel):
    item_name: str = Field(description="物品名称")
    action: str = Field(description="动作: acquire/transfer_in/transfer_out/consume/lose/destroy")
    holder: str = Field(description="当前持有角色")
    previous_holder: str = Field(default="", description="上一持有角色")
    quantity: int = Field(default=1, description="数量")
    note: str = Field(default="", description="备注（≤100字）")


class TxList(BaseModel):
    transactions: list[TxItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# ItemLedger
# ─────────────────────────────────────────────────────────────

class ItemLedger:
    """
    Item possession tracking via transaction log.
    """

    def __init__(self, workspace):
        self._workspace = workspace
        self._state = workspace.raw_state
        self._transactions: list[ItemTransaction] = []
        self._load_from_cache()

    # ── Lifecycle ─────────────────────────────────────────────

    def _load_from_cache(self):
        """Load transactions from context_cache."""
        cached = self._workspace.context_cache.get("item_ledger")
        if cached:
            try:
                loaded = json.loads(cached) if isinstance(cached, str) else cached
                self._transactions = [ItemTransaction.from_dict(t) for t in loaded]
            except Exception:
                pass

    def _persist_to_cache(self):
        """Write transactions to context_cache."""
        self._workspace.context_cache["item_ledger"] = json.dumps(
            [t.to_dict() for t in self._transactions], ensure_ascii=False
        )

    def _persist_to_disk(self):
        """Write to item_ledger.json in project dir."""
        if not hasattr(self._workspace, "_project_dir") or not self._workspace._project_dir:
            return
        from pathlib import Path
        try:
            path = Path(self._workspace._project_dir) / "item_ledger.json"
            data = {
                "transactions": [t.to_dict() for t in self._transactions],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("item_ledger disk persist failed: %s", e)

    def save(self):
        """Persist to cache and disk."""
        self._persist_to_cache()
        self._persist_to_disk()

    # ── Transaction CRUD ─────────────────────────────────────

    def record_transaction(self, tx: ItemTransaction):
        """Record a new item transaction."""
        self._transactions.append(tx)
        self.save()
        logger.debug("[item_ledger] tx: %s %s → %s (ch%d)", tx.action, tx.item_name, tx.holder, tx.chapter)

    def record_transactions(self, txs: list[ItemTransaction]):
        """Record multiple transactions."""
        self._transactions.extend(txs)
        self.save()
        logger.info("[item_ledger] recorded %d txs (total=%d)", len(txs), len(self._transactions))

    def get_item_history(self, item_name: str) -> list[ItemTransaction]:
        """Get all transactions for a specific item, sorted by chapter."""
        txs = [t for t in self._transactions if t.item_name == item_name]
        txs.sort(key=lambda t: t.chapter)
        return txs

    def get_current_holder(self, item_name: str) -> str:
        """Get the current holder of an item. Returns empty string if unknown."""
        history = self.get_item_history(item_name)
        if not history:
            return ""
        # Latest transaction determines current holder
        latest = max(history, key=lambda t: t.chapter)
        if latest.action in ("acquire", "transfer_in"):
            return latest.holder
        elif latest.action in ("consume", "destroy", "lose"):
            return "（已消耗/丢失/销毁）"
        elif latest.action == "transfer_out":
            # Need to find where it went (next transfer_in)
            for t in history:
                if t.chapter > latest.chapter and t.action == "transfer_in":
                    return t.holder
            return "（去向不明）"
        return latest.holder

    def get_all_transactions(self) -> list[ItemTransaction]:
        """Return all transactions."""
        return list(self._transactions)

    def get_transactions_by_chapter(self, chapter_num: int) -> list[ItemTransaction]:
        """Get all transactions in a chapter."""
        return [t for t in self._transactions if t.chapter == chapter_num]

    # ── LLM Extraction ───────────────────────────────────────

    def extract_from_chapter(self, chapter_content: str, chapter_num: int,
                             llm=None) -> list[ItemTransaction]:
        """
        LLM-based item transaction extraction.
        Uses complete_structured (MD_JSON) with 60s timeout.
        On failure, falls back to regex scanning.

        Returns list of ItemTransaction objects (not yet persisted).
        """
        if not chapter_content:
            return []

        t0 = time.time()

        try:
            new_txs = self._llm_extract(chapter_content, chapter_num, llm)
            elapsed = (time.time() - t0) * 1000
            logger.info(
                "[item_ledger.extract] ch=%d txs=%d method=llm elapsed=%.0fms",
                chapter_num, len(new_txs), elapsed,
            )
            return new_txs
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            logger.warning(
                "[item_ledger.extract] ch=%d llm_failed=%s elapsed=%.0fms, using regex",
                chapter_num, e, elapsed,
            )
            return self._regex_extract(chapter_content, chapter_num)

    def _llm_extract(self, chapter_content: str, chapter_num: int,
                     llm=None) -> list[ItemTransaction]:
        """LLM structured output for item transaction extraction."""
        from ..utils.llm import create_llm_client
        if llm is None:
            llm = create_llm_client()

        snippet = chapter_content[:4000]

        prompt = (
            "从以下章节正文中提取关键物品的流转信息。\n\n"
            f"## 第{chapter_num}章正文（前4000字）\n\n{snippet}\n\n"
            "## 规则\n"
            "1. action: acquire(获得)/transfer_in(转入)/transfer_out(转出)/consume(消耗)/lose(丢失)/destroy(销毁)\n"
            "2. holder: 当前持有该物品的角色名\n"
            "3. previous_holder: 转出前一持有者（action为transfer_in时必填）\n"
            "4. 只记录法器/丹药/秘籍/信物/钥匙等关键物品，忽略日常物品\n"
            "5. 若本章没有物品流转，返回空列表"
        )

        try:
            result = llm.complete_structured(
                prompt, output_class=TxList,
                temperature=0.3, max_tokens=2048, timeout=60, max_retries=0,
            )
            transactions = []
            for item in result.transactions:
                transactions.append(ItemTransaction(
                    item_name=item.item_name,
                    action=item.action,
                    holder=item.holder,
                    previous_holder=item.previous_holder,
                    chapter=chapter_num,
                    quantity=item.quantity,
                    note=item.note,
                ))
            return transactions
        except Exception:
            raise

    def _regex_extract(self, chapter_content: str, chapter_num: int) -> list[ItemTransaction]:
        """
        Regex fallback: scan for item possession patterns.
        Matches patterns like "获得了X", "将X交给Y", "X被毁", "消耗了X".
        """
        transactions = []
        action_patterns = [
            (r'([\u4e00-\u9fff]{2,4})(?:获得|得到|拿到|捡到|拾得)了?([\u4e00-\u9fff]{2,10}(?:剑|刀|丹|药|符|宝|戒|甲|鼎|镜|珠|扇|卷|令|石|玉|旗|印|环|铃|戟|枪|斧|锤|鞭|伞|琴))', "acquire"),
            (r'([\u4e00-\u9fff]{2,4})将([\u4e00-\u9fff]{2,10}(?:剑|刀|丹|药|符|宝|戒|甲|鼎|镜|珠|扇|卷|令|石|玉|旗|印|环|铃|戟|枪|斧|锤|鞭|伞|琴))(?:交给|递给|送给|给予)([\u4e00-\u9fff]{2,4})', "transfer_in"),
            (r'([\u4e00-\u9fff]{2,4})(?:失去|丢失|掉落)了?([\u4e00-\u9fff]{2,10}(?:剑|刀|丹|药|符|宝|戒|甲|鼎|镜|珠|扇|卷|令|石|玉|旗|印|环|铃|戟|枪|斧|锤|鞭|伞|琴))', "lose"),
            (r'([\u4e00-\u9fff]{2,4})(?:消耗|用掉|服用|服下)了?([\u4e00-\u9fff]{2,10}(?:丹|药|液|草|果|丸|散))', "consume"),
            (r'([\u4e00-\u9fff]{2,10}(?:剑|刀|丹|药|符|宝|戒|甲|鼎|镜|珠|扇|卷|令|石|玉|旗|印|环|铃|戟|枪|斧|锤|鞭|伞|琴))被?(?:毁|碎|炸|焚|化)', "destroy"),
        ]

        seen = set()
        for pat, action in action_patterns:
            for m in re.finditer(pat, chapter_content):
                if action == "acquire":
                    holder = m.group(1)
                    item_name = m.group(2)
                    note = ""
                elif action == "transfer_in":
                    previous_holder = m.group(1)
                    item_name = m.group(2)
                    holder = m.group(3)
                    note = f"从{previous_holder}转入"
                elif action == "lose":
                    holder = m.group(1)
                    item_name = m.group(2)
                    note = f"{holder}丢失了{item_name}"
                elif action == "consume":
                    holder = m.group(1)
                    item_name = m.group(2)
                    note = f"{holder}消耗了{item_name}"
                elif action == "destroy":
                    item_name = m.group(1)
                    holder = "（已销毁）"
                    note = f"{item_name}被毁"
                else:
                    continue

                unique_key = f"{item_name}:{action}:{holder}:{chapter_num}"
                if unique_key in seen:
                    continue
                seen.add(unique_key)

                # Try to extract previous_holder for transfer_in
                prev_holder = ""
                if action == "transfer_in":
                    prev_holder = m.group(1) if m.lastindex >= 3 else ""

                transactions.append(ItemTransaction(
                    item_name=item_name,
                    action=action,
                    holder=holder,
                    previous_holder=prev_holder,
                    chapter=chapter_num,
                    note=note,
                ))

        logger.info(
            "[item_ledger.regex] ch=%d txs=%d",
            chapter_num, len(transactions),
        )
        return transactions

    def apply_extraction(self, transactions: list[ItemTransaction]):
        """Merge extracted transactions into the ledger."""
        existing_keys = {
            (t.item_name, t.action, t.holder, t.chapter)
            for t in self._transactions
        }
        new = [t for t in transactions
               if (t.item_name, t.action, t.holder, t.chapter) not in existing_keys]
        if new:
            self.record_transactions(new)


# ─────────────────────────────────────────────────────────────
# Async helper
# ─────────────────────────────────────────────────────────────

async def extract_items_async(ledger: ItemLedger, content: str,
                               chapter_num: int):
    """Fire-and-forget async wrapper for item extraction."""
    try:
        loop = asyncio.get_running_loop()
        new_txs = await loop.run_in_executor(
            None, ledger.extract_from_chapter, content, chapter_num
        )
        ledger.apply_extraction(new_txs)
        logger.info(
            "[item_ledger.async] ch=%d extracted=%d (total=%d)",
            chapter_num, len(new_txs), len(ledger.get_all_transactions()),
        )
    except Exception as e:
        logger.warning("[item_ledger.async] ch=%d failed: %s", chapter_num, e)
