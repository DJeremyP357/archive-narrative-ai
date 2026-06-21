import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional
from urllib.parse import urlencode, urlparse

import aiohttp

from config.settings import settings


class LLMProvider(str, Enum):
    DEEPSEEK = "deepseek"
    QWEN = "qwen"


class LLMClient:
    """国产大语言模型统一客户端 — 全部真实API调用"""

    def __init__(self, provider: str = LLMProvider.QWEN):
        self.provider = provider
        self.session: Optional[aiohttp.ClientSession] = None
        self._wenxin_token: Optional[str] = None
        self._wenxin_token_expiry: float = 0

    @property
    def api_key(self) -> Optional[str]:
        keys = {
            LLMProvider.DEEPSEEK: settings.DEEPSEEK_API_KEY,
            LLMProvider.QWEN: settings.QWEN_API_KEY,
        }
        return keys.get(self.provider)

    @property
    def base_url(self) -> str:
        urls = {
            LLMProvider.DEEPSEEK: settings.DEEPSEEK_BASE_URL,
            LLMProvider.QWEN: settings.QWEN_BASE_URL,
        }
        return urls.get(self.provider, "")

    @property
    def default_model(self) -> str:
        models = {
            LLMProvider.DEEPSEEK: settings.DEEPSEEK_MODEL or "deepseek-chat",
            LLMProvider.QWEN: settings.QWEN_MODEL or "qwen-plus",
        }
        return models.get(self.provider, "default")

    def is_openai_compatible(self) -> bool:
        return self.provider in (LLMProvider.DEEPSEEK, LLMProvider.QWEN)

    # ==================== 主入口 ====================

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        if self.is_openai_compatible():
            return await self._openai_compatible_chat(
                messages, model, temperature, max_tokens, stream, tools
            )
        raise ValueError(f"Unsupported provider: {self.provider}")

    # ==================== OpenAI兼容协议实现 ====================
    # 覆盖: DeepSeek / Qwen

    async def _openai_compatible_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        stream: bool,
        tools: Optional[List[Dict]],
    ) -> Dict[str, Any]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/chat/completions"
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(
                    f"[{self.provider}] API Error {response.status}: {error_text[:500]}"
                )
            return await response.json()

    # (旧 Provider 方法已移除，只保留 Qwen/DeepSeek OpenAI 兼容协议)

    # ==================== 流式输出 ====================

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        session = await self._get_session()

        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(
                    f"[{self.provider}] Stream Error {response.status}: {error_text[:500]}"
                )
            async for line in response.content:
                line = line.decode().strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue

    # ==================== 工具方法 ====================

    async def simple_chat(self, prompt: str, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        result = await self.chat_completion(messages)
        return (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

    # ==================== 会话 ====================

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
            timeout = aiohttp.ClientTimeout(total=120)
            self.session = aiohttp.ClientSession(
                connector=connector, timeout=timeout
            )
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class MultiLLMRouter:
    """多LLM路由 — 支持主备切换、负载均衡、自动故障转移、按Agent类型选择模型"""

    def __init__(self):
        self.clients: Dict[LLMProvider, LLMClient] = {}
        self.fallback_order: List[LLMProvider] = [
            LLMProvider.QWEN,
        ]
        self._provider_health: Dict[LLMProvider, bool] = {}
        
        # Agent 类型到模型的映射（5 个模型各司其职，全部走 DashScope）
        # 配置要求：.env 中 QWEN_API_KEY 必须存在，其他模型名以 QWEN_MODEL_* 前缀区分
        # 不再用 DEEPSEEK 兜底（用户要求"不要 DeepSeek"）
        self.agent_model_mapping: Dict[str, Dict[str, str]] = {
            # 🧠 中央调度 — qwen3.7-plus
            "PlannerAgent":         {"provider": "qwen", "model": settings.QWEN_MODEL_PLANNER or "qwen3.7-plus"},
            "SmartOrchestrator":    {"provider": "qwen", "model": settings.QWEN_MODEL_PLANNER or "qwen3.7-plus"},

            # 👁️ 图像识别 — qwen3-vl-235b-a22b-instruct
            "ImageVerifier":        {"provider": "qwen", "model": settings.QWEN_MODEL_VL or "qwen3-vl-235b-a22b-instruct"},
            "VisionClient":         {"provider": "qwen", "model": settings.QWEN_MODEL_VL or "qwen3-vl-235b-a22b-instruct"},
            "WebCrawlerAgent":      {"provider": "qwen", "model": settings.QWEN_MODEL_VL or "qwen3-vl-235b-a22b-instruct"},

            # 🎬 全模态 — 解析用户上传的图片/音频/视频档案
            "DocumentParserAgent":  {"provider": "qwen", "model": settings.QWEN_MODEL_OMNI or "qwen3-omni-flash"},
            "SmartInputAgent":      {"provider": "qwen", "model": settings.QWEN_MODEL_OMNI or "qwen3-omni-flash"},

            # ✍️ 大语言 — 长文档分析 + 叙事文案 (qwen3-max)
            "ArchiveAnalysisAgent": {"provider": "qwen", "model": settings.QWEN_MODEL_LLM or "qwen3-max"},
            "SmartAnalysisAgent":   {"provider": "qwen", "model": settings.QWEN_MODEL_LLM or "qwen3-max"},

            # 💻 代码生成 — 全栈统一用 qwen3.7-plus
            "WebGalleryAgent":      {"provider": "qwen", "model": settings.QWEN_MODEL_PLANNER or "qwen3.7-plus"},
            "Exhibition3DAgent":    {"provider": "qwen", "model": settings.QWEN_MODEL_PLANNER or "qwen3.7-plus"},
            "SmartOutputAgent":     {"provider": "qwen", "model": settings.QWEN_MODEL_PLANNER or "qwen3.7-plus"},

            # 默认 — qwen3-max
            "default":              {"provider": "qwen", "model": settings.QWEN_MODEL_LLM or "qwen3-max"},
        }

    def register_client(self, provider: LLMProvider, client: LLMClient):
        self.clients[provider] = client
        self._provider_health[provider] = True

    def get_available_providers(self) -> List[Dict[str, Any]]:
        result = []
        for provider in self.fallback_order:
            available = (
                provider in self.clients
                and self._provider_health.get(provider, False)
                and self.clients[provider].api_key is not None
            )
            result.append(
                {
                    "name": provider.value,
                    "model": self.clients[provider].default_model
                    if provider in self.clients
                    else "N/A",
                    "available": available,
                }
            )
        return result

    def get_model_for_agent(self, agent_name: str) -> Dict[str, str]:
        """根据 Agent 类型返回推荐的模型配置"""
        return self.agent_model_mapping.get(agent_name, self.agent_model_mapping["default"])
    
    async def chat_with_fallback(
        self,
        messages: List[Dict[str, str]],
        preferred_provider: Optional[str] = None,
        agent_name: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        智能路由聊天请求
        
        Args:
            messages: 对话消息列表
            preferred_provider: 优先使用的提供商（可选）
            agent_name: Agent 名称，用于自动选择最佳模型（可选）
            **kwargs: 其他参数（temperature, max_tokens 等）
        """
        # 如果指定了 Agent 名称，自动选择最佳模型
        if agent_name and not preferred_provider:
            model_config = self.get_model_for_agent(agent_name)
            pref_name = model_config["provider"]
            # 将字符串转换为 LLMProvider 枚举，以匹配 clients 字典的键
            try:
                preferred_provider = LLMProvider(pref_name)
            except ValueError:
                preferred_provider = None
            if "model" not in kwargs:
                kwargs["model"] = model_config["model"]
        
        providers: List[LLMProvider] = []
        if preferred_provider and preferred_provider in self.clients:
            providers.append(preferred_provider)
        for p in self.fallback_order:
            if p not in self.clients:
                continue
            if not self._provider_health.get(p, True):
                continue
            if p not in providers:
                providers.append(p)

        last_error = None
        for provider in providers:
            client = self.clients[provider]
            try:
                result = await client.chat_completion(messages, **kwargs)
                self._provider_health[provider] = True
                return result
            except Exception as e:
                self._provider_health[provider] = False
                last_error = e
                continue

        raise Exception(
            f"所有LLM提供商均不可用。最后错误: {last_error}"
        )

    async def close_all(self):
        for client in self.clients.values():
            await client.close()