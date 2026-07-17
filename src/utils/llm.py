"""
WriteSync LLM 客户端

统一的 LLM 调用接口，支持 OpenAI 兼容端点（OpenCode Go 等）和 Anthropic。
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from src.utils.provider_config import AIProviderConfig

logger = logging.getLogger("writesync")


class LLMClient(ABC):
    """LLM 客户端抽象基类"""

    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        """同步调用 LLM，返回文本"""
        ...

    @abstractmethod
    def complete_structured(self, prompt: str, output_class: type, **kwargs) -> Any:
        """同步调用 LLM，返回结构化对象（使用 instructor）"""
        ...


class OpenAIClient(LLMClient):
    """OpenAI 兼容客户端（支持 OpenCode Go 等端点）"""

    DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
    DEFAULT_MODEL = "deepseek-v4-flash"
    DEFAULT_API_KEY = os.environ.get("LLM_API_KEY", "")

    # 推理模型的 max_tokens 需要覆盖 reasoning + content，大幅调高
    # 非推理模型速度更快（如 qwen3.6-plus），适合常规生成
    REASONING_MODELS = {"deepseek-v4-pro", "kimi-k2.5", "kimi-k2.6",
                        "minimax-m2.7", "minimax-m2.5", "mimo-v2-pro", "mimo-v2-omni",
                        "mimo-v2.5-pro", "mimo-v2.5"}

    # 这些模型的 API 不支持 response_format: {type: "json_schema", ...} 严格模式
    # 但仍支持 JSON 输出（使用 MD_JSON 降级：prompt 要求 → markdown JSON 提取）
    JSON_SCHEMA_UNSUPPORTED = {"deepseek-v4-flash", "deepseek-chat", "deepseek-coder"}

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model or os.environ.get("LLM_MODEL", self.DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("LLM_API_KEY", self.DEFAULT_API_KEY)
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", self.DEFAULT_BASE_URL)

    def _is_reasoning_model(self) -> bool:
        """判断当前模型是否为推理模型（会输出 reasoning_content）"""
        return self.model in self.REASONING_MODELS

    def complete(self, prompt: str, **kwargs) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        max_retries = max(kwargs.pop("max_retries", 3), 1)
        timeout = kwargs.pop("timeout", 300 if self._is_reasoning_model() else 180)

        # 推理模型的 max_tokens 覆盖 reasoning + content，需要大幅调高
        default_max_tokens = 16384 if self._is_reasoning_model() else 4096
        max_tokens = kwargs.pop("max_tokens", default_max_tokens)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    timeout=timeout,
                    **kwargs
                )
                message = response.choices[0].message
                content = message.content
                # 推理模型可能 content 为空，实际输出在 reasoning_content 中
                if not content:
                    reasoning = getattr(message, "reasoning_content", None)
                    if reasoning:
                        content = reasoning
                return content or ""
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise last_err

    def complete_structured(self, prompt: str, output_class: type, **kwargs) -> Any:
        try:
            import instructor
            from instructor import Mode
        except ImportError:
            raise ImportError("请安装 instructor: pip install instructor")

        from openai import OpenAI

        # 推理模型或 API 不支持 JSON_SCHEMA 严格模式的模型，使用兼容性最好的 MD_JSON
        # MD_JSON 原理：在 prompt 中要求模型输出 markdown 代码块包裹的 JSON，然后提取
        if self._is_reasoning_model() or self.model in self.JSON_SCHEMA_UNSUPPORTED:
            mode = kwargs.pop("mode", Mode.MD_JSON)
        else:
            mode = kwargs.pop("mode", Mode.JSON_SCHEMA)

        client = instructor.from_openai(OpenAI(api_key=self.api_key, base_url=self.base_url), mode=mode)

        # 从 kwargs 提取 timeout 和 max_retries，允许 agent 级覆盖
        # 注意：opencode.ai 网关延迟较高，结构化输出典型耗时 ~100-170s
        timeout = kwargs.pop("timeout", 300 if self._is_reasoning_model() else 180)
        max_retries = kwargs.pop("max_retries", 1)
        default_max_tokens = 16384 if self._is_reasoning_model() else 4096
        max_tokens = kwargs.pop("max_tokens", default_max_tokens)
        # 推理模型的 reasoning tokens 占用 max_tokens 预算，保证 content 有充足空间
        if self._is_reasoning_model() and max_tokens < 4096:
            max_tokens = 4096

        # 某些 provider（如阿里云）要求消息中出现 "json" 一词才能使用 json_object/json_schema
        # 自动追加以确保兼容性
        json_hint = "\n\n请以 JSON 格式输出。"
        if json_hint not in prompt:
            prompt = prompt + json_hint

        # 外层重试：仅对连接/网络错误重试，输出校验失败（InstructorRetryException）不重试
        # Non-retryable errors (BadRequest, Auth, etc.) bubble up to _safe_agent_call
        from openai import APIConnectionError, APITimeoutError
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                return client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_model=output_class,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    max_retries=0,  # instructor 内部不重试，由外层循环处理
                    **kwargs
                )
            except (APIConnectionError, APITimeoutError, ConnectionError, OSError) as e:
                last_err = e
                if attempt < max_retries:
                    import time as _time
                    _time.sleep(2 ** attempt)
                    continue
                raise last_err


class AnthropicClient(LLMClient):
    """Anthropic Claude / 兼容 API 客户端"""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")

    def complete(self, prompt: str, **kwargs) -> str:
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("请安装 anthropic: pip install anthropic")

        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = Anthropic(**client_kwargs)

        max_retries = kwargs.pop("max_retries", 3)
        timeout = kwargs.pop("timeout", 180)

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=kwargs.pop("max_tokens", 4096),
                    timeout=timeout,
                    messages=[{"role": "user", "content": prompt}],
                    **kwargs
                )
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        return block.text
                return ""
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise last_err

    def complete_structured(self, prompt: str, output_class: type, **kwargs) -> Any:
        try:
            import instructor
        except ImportError:
            raise ImportError("请安装 instructor: pip install instructor")

        from anthropic import Anthropic

        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = instructor.from_anthropic(Anthropic(**client_kwargs))
        return client.messages.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_model=output_class,
            max_tokens=kwargs.pop("max_tokens", 4096),
            timeout=kwargs.pop("timeout", 180),
            **kwargs
        )


class ResilientLLMClient(LLMClient):
    """Wraps a primary client and a list of fallback clients.

    On timeout / connection error, automatically retries with the next fallback.
    """

    def __init__(self, clients: List[LLMClient]):
        if not clients:
            raise ValueError("At least one client required")
        self.clients = clients

    def complete(self, prompt: str, **kwargs) -> str:
        last_err: Exception | None = None
        for idx, client in enumerate(self.clients):
            try:
                if idx > 0:
                    logger.warning("Fallback to provider %s/%s", type(client).__name__, getattr(client, 'model', '?'))
                return client.complete(prompt, **kwargs)
            except Exception as e:
                last_err = e
                # Only fall back on timeout/connection errors
                if not self._is_retryable(e):
                    raise
                logger.warning("Provider %s failed: %s", type(client).__name__, e)
                continue
        raise last_err or RuntimeError("All providers failed")

    def complete_structured(self, prompt: str, output_class: type, **kwargs) -> Any:
        last_err: Exception | None = None
        for idx, client in enumerate(self.clients):
            try:
                if idx > 0:
                    logger.warning("Fallback to provider %s/%s", type(client).__name__, getattr(client, 'model', '?'))
                return client.complete_structured(prompt, output_class, **kwargs)
            except Exception as e:
                last_err = e
                if not self._is_retryable(e):
                    raise
                logger.warning("Provider %s failed: %s", type(client).__name__, e)
                continue
        raise last_err or RuntimeError("All providers failed")

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Determine whether an exception warrants fallback to the next provider."""
        retryable_names = (
            "APITimeoutError", "APIConnectionError", "ConnectionError",
            "OSError", "TimeoutError", "ReadTimeout",
        )
        if type(exc).__name__ in retryable_names:
            return True
        # Also check openai-specific exceptions if available
        try:
            from openai import APIConnectionError, APITimeoutError
            if isinstance(exc, (APIConnectionError, APITimeoutError)):
                return True
        except Exception:
            pass
        return False


def _client_from_provider_config(config: AIProviderConfig) -> LLMClient:
    """Instantiate the correct LLMClient subclass from an AIProviderConfig."""
    ptype = config.provider_type.lower()
    if ptype in ("openai", "opencode", "ollama", "custom"):
        return OpenAIClient(
            model=config.default_model or None,
            api_key=config.api_key or None,
            base_url=config.base_url or None,
        )
    elif ptype == "anthropic":
        return AnthropicClient(
            model=config.default_model or "claude-sonnet-4-20250514",
            api_key=config.api_key or None,
            base_url=config.base_url or None,
        )
    else:
        raise ValueError(f"不支持的 provider_type: {config.provider_type}")


def create_llm_client(
    provider: Optional[str] = None,
    provider_config: Optional[AIProviderConfig] = None,
    **kwargs,
) -> LLMClient:
    """
    工厂函数：创建 LLM 客户端

    默认使用 OpenCode Go（OpenAI 兼容端点）。
    可通过环境变量 LLM_PROVIDER 切换为 anthropic。

    Args:
        provider: 供应商名称（"openai"/"opencode"/"anthropic"）。
        provider_config: 可选的 AIProviderConfig；若提供则优先使用其配置。
    """
    if provider_config is not None:
        return _client_from_provider_config(provider_config)

    provider = provider or os.environ.get("LLM_PROVIDER", "opencode")
    if provider == "openai":
        return OpenAIClient(**kwargs)
    elif provider == "opencode":
        return OpenAIClient(**kwargs)
    elif provider == "anthropic":
        return AnthropicClient(**kwargs)
    else:
        raise ValueError(f"不支持的 LLM provider: {provider}")


def create_llm_client_with_fallback(
    primary_config: Optional[AIProviderConfig] = None,
    fallback_configs: Optional[List[AIProviderConfig]] = None,
    provider: Optional[str] = None,
    **kwargs,
) -> LLMClient:
    """
    创建支持故障转移的 LLM 客户端。

    当主供应商超时或连接失败时，自动按顺序尝试备用供应商。

    Args:
        primary_config: 主供应商配置。
        fallback_configs: 备用供应商配置列表。
        provider: 当 primary_config 为 None 时的传统供应商名称。
    """
    clients: List[LLMClient] = []

    if primary_config is not None:
        clients.append(_client_from_provider_config(primary_config))
    else:
        clients.append(create_llm_client(provider=provider, **kwargs))

    for cfg in (fallback_configs or []):
        try:
            clients.append(_client_from_provider_config(cfg))
        except Exception as e:
            logger.warning("Skipping fallback provider %s: %s", cfg.name, e)

    if len(clients) == 1:
        return clients[0]
    return ResilientLLMClient(clients)