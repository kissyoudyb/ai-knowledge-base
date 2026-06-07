"""统一的 LLM 调用客户端，支持 DeepSeek / Qwen / OpenAI。

通过环境变量配置：
    LLM_PROVIDER: deepseek | qwen | openai（默认 deepseek）
    DEEPSEEK_API_KEY / QWEN_API_KEY / OPENAI_API_KEY
"""

import os
import time
import json
import uuid
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from loguru import logger


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

PROVIDER_CONFIG = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "input_price": 0.27,      # $/1M tokens
        "output_price": 1.10,
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "QWEN_API_KEY",
        "input_price": 0.80,
        "output_price": 2.00,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
        "input_price": 0.15,
        "output_price": 0.60,
    },
}

DEFAULT_PROVIDER = "deepseek"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 60


# ──────────────────────────────────────────────
#  Data Models
# ──────────────────────────────────────────────


@dataclass
class Usage:
    """Token 用量统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 调用返回结果。"""

    content: str
    usage: Usage = field(default_factory=Usage)
    provider: str = ""
    model: str = ""


# ──────────────────────────────────────────────
#  Abstract Base
# ──────────────────────────────────────────────


class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """发送对话并返回回复。

        Args:
            messages: OpenAI 格式的消息列表。
            **kwargs: 额外参数（temperature, max_tokens 等）。

        Returns:
            LLMResponse: 模型回复及用量统计。
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算文本消耗的 token 数。

        Args:
            text: 输入文本。

        Returns:
            估算的 token 数量。
        """
        ...


# ──────────────────────────────────────────────
#  OpenAI-Compatible Implementation
# ──────────────────────────────────────────────


class OpenAICompatibleProvider(LLMProvider):
    """通过 OpenAI 兼容 API 调用 LLM 的实现。"""

    PROVIDER_NAME = ""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        config = PROVIDER_CONFIG[provider_name]
        self.base_url = config["base_url"]
        self.model = config["model"]
        api_key = os.environ.get(config["api_key_env"], "")
        if not api_key:
            logger.warning(f"环境变量 {config['api_key_env']} 未设置")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=TIMEOUT_SECONDS,
        )
        self._input_price = config["input_price"]
        self._output_price = config["output_price"]

    def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """发送对话请求并返回结构化响应。

        Args:
            messages: OpenAI 格式消息列表。
            **kwargs: 可选参数，支持 temperature、max_tokens、top_p。

        Returns:
            LLMResponse: 包含回复内容和用量统计。

        Raises:
            httpx.HTTPError: API 请求失败时抛出。
        """
        payload: dict[str, object] = {
            "model": kwargs.pop("model", self.model),
            "messages": messages,
            "temperature": kwargs.pop("temperature", 0.7),
            "max_tokens": kwargs.pop("max_tokens", 4096),
            **kwargs,
        }
        logger.debug("请求 {}: {} 条消息", self.provider_name, len(messages))

        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        usage_raw = data.get("usage", {})

        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        logger.debug(
            "{} 回复完成 — 输入 {} / 输出 {} tokens",
            self.provider_name,
            usage.prompt_tokens,
            usage.completion_tokens,
        )
        return LLMResponse(
            content=content,
            usage=usage,
            provider=self.provider_name,
            model=payload["model"],
        )

    def count_tokens(self, text: str) -> int:
        """基于粗略估算：中文 ~1.5 token/字，英文 ~1 token/4 字符。

        Args:
            text: 输入文本。

        Returns:
            估算的 token 数。
        """
        char_count = len(text)
        ascii_count = sum(1 for c in text if c.isascii())
        non_ascii_count = char_count - ascii_count
        return int(non_ascii_count * 1.5 + ascii_count / 4)

    def calculate_cost(self, usage: Usage) -> float:
        """根据用量和提供商定价计算 USD 费用。

        Args:
            usage: Token 用量统计。

        Returns:
            费用（美元）。
        """
        input_cost = (usage.prompt_tokens / 1_000_000) * self._input_price
        output_cost = (usage.completion_tokens / 1_000_000) * self._output_price
        return round(input_cost + output_cost, 6)

    def close(self) -> None:
        """释放 httpx 连接资源。"""
        self._client.close()


# ──────────────────────────────────────────────
#  带重试的调用
# ──────────────────────────────────────────────


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict],
    max_retries: int = MAX_RETRIES,
    **kwargs,
) -> LLMResponse:
    """带指数退避重试的 LLM 调用。

    Args:
        provider: LLMProvider 实例。
        messages: OpenAI 格式消息列表。
        max_retries: 最大重试次数（默认 3）。
        **kwargs: 传递给 chat() 的额外参数。

    Returns:
        LLMResponse: 模型回复及用量统计。

    Raises:
        RuntimeError: 所有重试均失败时抛出。
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return provider.chat(messages, **kwargs)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(
                    "第 {} 次调用失败（{}），{:.0f}s 后重试…",
                    attempt,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error("重试 {} 次后仍失败: {}", max_retries, e)

    raise RuntimeError(f"LLM 调用失败，已重试 {max_retries} 次") from last_exc


# ──────────────────────────────────────────────
#  便捷函数
# ──────────────────────────────────────────────


def quick_chat(
    prompt: str,
    system_prompt: Optional[str] = None,
    provider_name: Optional[str] = None,
    **kwargs,
) -> str:
    """一句话调用 LLM，直接返回文本结果。

    Args:
        prompt: 用户输入。
        system_prompt: 可选的系统提示词。
        provider_name: 提供商名称（默认使用 LLM_PROVIDER）。
        **kwargs: 传递给 chat() 的额外参数。

    Returns:
        str: 模型回复文本。
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    provider = _build_provider(provider_name)
    try:
        response = chat_with_retry(provider, messages, **kwargs)
        return response.content
    finally:
        if hasattr(provider, "close"):
            provider.close()


def estimate_tokens(text: str) -> int:
    """快速估算文本 token 数（使用默认提供商的估算方法）。

    Args:
        text: 输入文本。

    Returns:
        估算的 token 数量。
    """
    default = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    return OpenAICompatibleProvider(default).count_tokens(text)


# ──────────────────────────────────────────────
#  内部工厂
# ──────────────────────────────────────────────


def create_provider(provider_name: Optional[str] = None) -> OpenAICompatibleProvider:
    """创建 LLM 提供商客户端实例（公开别名）。

    Args:
        provider_name: 提供商名称，默认读取 LLM_PROVIDER 环境变量。

    Returns:
        OpenAICompatibleProvider: LLM 客户端实例。
    """
    return _build_provider(provider_name)


def _build_provider(provider_name: Optional[str] = None) -> OpenAICompatibleProvider:
    """根据提供商名称创建 LLMProvider 实例。

    Args:
        provider_name: 提供商名称，默认读取 LLM_PROVIDER 环境变量。

    Returns:
        OpenAICompatibleProvider: LLM 客户端实例。

    Raises:
        ValueError: 不支持的提供商名称。
    """
    name = provider_name or os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    name = name.strip().lower()

    if name not in PROVIDER_CONFIG:
        raise ValueError(
            f"不支持的 LLM 提供商: {name}，可选: {', '.join(PROVIDER_CONFIG)}"
        )

    logger.debug("初始化 LLM 提供商: {}", name)
    return OpenAICompatibleProvider(name)


# ──────────────────────────────────────────────
#  Cost 查询
# ──────────────────────────────────────────────


def get_provider_pricing(provider_name: Optional[str] = None) -> dict:
    """获取指定提供商的定价信息。

    Args:
        provider_name: 提供商名称，默认读取 LLM_PROVIDER。

    Returns:
        dict: 包含 input_price、output_price、unit 的定价字典。
    """
    name = provider_name or os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    config = PROVIDER_CONFIG[name.strip().lower()]
    return {
        "input_price": config["input_price"],
        "output_price": config["output_price"],
        "unit": "per 1M tokens",
    }


# ──────────────────────────────────────────────
#  Test / Demo
# ──────────────────────────────────────────────


if __name__ == "__main__":
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="INFO: {message}",
        level="INFO",
        colorize=False,
    )

    print("=== LLM 客户端测试 ===")
    provider_name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    print(f"提供商: {provider_name}")

    provider = _build_provider(provider_name)
    logger.info("创建 LLM 客户端: provider={}, model={}", provider_name, provider.model)

    try:
        resp = chat_with_retry(
            provider,
            messages=[
                {"role": "user", "content": "用一句话解释什么是 AI Agent？"},
            ],
        )
        cost = provider.calculate_cost(resp.usage)
        logger.info(
            "Token 用量: {} (prompt) + {} (completion) = {}, 估算成本: ${:.6f}",
            resp.usage.prompt_tokens,
            resp.usage.completion_tokens,
            resp.usage.total_tokens,
            cost,
        )
        print(f"\n回复: {resp.content}")
    finally:
        provider.close()
