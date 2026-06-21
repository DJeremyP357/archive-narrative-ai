"""
应用启动引导 — 统一创建 LLM 路由、注册全部 API、提供诊断信息。

所有入口（run_narrative / api）应通过此处获取共享资源
避免每个 Agent 各自 new MultiLLMRouter() 导致「不知道 API 有没有用上」。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.agent_catalog import AGENT_SPECS, AgentKind, get_agent_spec
from config.settings import settings
from core.llm_client import LLMClient, LLMProvider, MultiLLMRouter


# 环境变量 → LLM 提供商
_LLM_ENV_MAP = [
    (LLMProvider.QWEN, "QWEN_API_KEY"),
]

_MEDIA_ENV_MAP = {
    "image_gen_tongyi": ("TONGYI_WANXIANG_API_KEY", "通义万相"),
    "image_gen_wenxin": ("WENXIN_YIGE_API_KEY", "文心一格"),
    "image_gen_cogview": ("COGVIEW_API_KEY", "CogView"),
    "image_gen_kling": ("KLING_API_KEY", "可灵生图"),
    "tts_baidu": ("BAIDU_TTS_API_KEY", "百度TTS"),
    "tts_ali": ("ALI_TTS_ACCESS_ID", "阿里云TTS"),
    "tts_xunfei": ("XUNFEI_TTS_API_KEY", "讯飞TTS"),
    "tts_tencent": ("TENCENT_TTS_SECRET_ID", "腾讯TTS"),
    "video_qwen": ("QWEN_VIDEO_API_KEY", "通义万相视频"),
    "video_kling": ("KLING_VIDEO_API_KEY", "可灵视频"),
    "video_jimeng": ("JIMENG_API_KEY", "即梦视频"),
}


@dataclass
class AppContext:
    """一次运行会话的共享上下文"""
    llm_router: MultiLLMRouter
    registered_llm_providers: List[str] = field(default_factory=list)
    output_dir: str = "outputs"
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def create_llm_router(register_all_from_env: bool = True) -> MultiLLMRouter:
    """
    创建全局 LLM 路由并注册 .env 中已配置的提供商。
    未配置 Key 的提供商不会注册，chat_with_fallback 会自动跳过。
    """
    router = MultiLLMRouter()
    if not register_all_from_env:
        return router

    for provider, env_key in _LLM_ENV_MAP:
        if os.getenv(env_key) or getattr(settings, env_key, None):
            client = LLMClient(provider)
            if client.api_key:
                router.register_client(provider, client)
    return router


def get_media_api_status() -> List[Dict[str, Any]]:
    rows = []
    for key, (env_name, label) in _MEDIA_ENV_MAP.items():
        val = os.getenv(env_name) or getattr(settings, env_name, None)
        rows.append({
            "id": key,
            "label": label,
            "env_var": env_name,
            "configured": bool(val),
        })
    return rows


def build_diagnostics(router: Optional[MultiLLMRouter] = None) -> Dict[str, Any]:
    """生成系统诊断报告（作业演示 / 自查用）"""
    router = router or create_llm_router()
    llm_status = router.get_available_providers()

    agents = []
    # Smart 包装器对内不可见 — 仅展示用户面 Agent
    _hidden = {"SmartInputAgent", "SmartAnalysisAgent", "SmartOutputAgent", "SmartOrchestrator"}
    for name, spec in AGENT_SPECS.items():
        if name in _hidden:
            continue
        uses_llm = spec.kind in (AgentKind.REACT, AgentKind.LEGACY)
        pref = spec.preferred_llm
        pref_available = False
        if pref and uses_llm:
            pref_available = any(
                p["name"] == pref and p["available"] for p in llm_status
            )
        agents.append({
            "name": name,
            "layer": spec.layer.value,
            "kind": spec.kind.value,
            "preferred_llm": pref,
            "preferred_llm_ready": pref_available if uses_llm else None,
            "media_apis": spec.media_apis,
            "smart_wrapper": spec.smart_wrapper,
            "wired_in_v2": spec.wired_in_v2,
            "uses_llm_api": uses_llm,
        })

    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "llm_providers": llm_status,
        "media_apis": get_media_api_status(),
        "agents": agents,
        "agent_count": len(agents),
        "execution_modes": {
            "smart": "SmartOrchestrator -> Planner + 专用调度(WebCrawler/分析/HTML/3D)",
        },
        "homework_tip": (
            "python run_narrative.py --theme custom --title '档案主题' --keywords 关键词 --crawl；"
            "诊断: python scripts/check_apis.py"
        ),
    }


def create_app_context(output_dir: str = "outputs") -> AppContext:
    router = create_llm_router()
    registered = [
        p["name"]
        for p in router.get_available_providers()
        if p.get("available")
    ]
    os.makedirs(output_dir, exist_ok=True)
    diag = build_diagnostics(router)
    return AppContext(
        llm_router=router,
        registered_llm_providers=registered,
        output_dir=output_dir,
        diagnostics=diag,
    )


async def shutdown_app_context(ctx: AppContext):
    await ctx.llm_router.close_all()
