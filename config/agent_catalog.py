"""
Agent 目录 — V2 精简版（项目实际使用的 8 个 Agent）

用于：编排调度、API 路由说明、作业文档、诊断工具。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class AgentLayer(str, Enum):
    ORCHESTRATOR = "orchestrator"
    INPUT = "input"
    PROCESSING = "processing"
    OUTPUT = "output"


class AgentKind(str, Enum):
    """Agent 实现形态"""
    REACT = "react"       # LLM + 工具循环（ReActAgent）
    TOOL = "tool"         # 纯能力模块（爬虫/解析/生成），无 LLM 决策
    LEGACY = "legacy"     # 向后兼容别名（等同于 TOOL）


@dataclass
class AgentSpec:
    name: str
    layer: AgentLayer
    kind: AgentKind
    module: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    preferred_llm: Optional[str] = None
    fallback_llms: List[str] = field(default_factory=list)
    media_apis: List[str] = field(default_factory=list)
    smart_wrapper: Optional[str] = None
    wired_in_v2: bool = True


# ---------------------------------------------------------------------------
# V2 编排层
# ---------------------------------------------------------------------------
AGENT_SPECS: dict[str, AgentSpec] = {
    "PlannerAgent": AgentSpec(
        name="PlannerAgent",
        layer=AgentLayer.ORCHESTRATOR,
        kind=AgentKind.REACT,
        module="agents.orchestrator.planner_agent",
        description="根据用户需求动态规划多 Agent 工作流（用 qwen3-max）",
        preferred_llm="qwen",
        fallback_llms=[],
        wired_in_v2=True,
    ),
    "SmartOrchestrator": AgentSpec(
        name="SmartOrchestrator",
        layer=AgentLayer.ORCHESTRATOR,
        kind=AgentKind.REACT,
        module="core.smart_orchestrator",
        description="V2 主编排器：规划 + 调度 + 数据流转",
        preferred_llm="qwen",
        fallback_llms=[],
        wired_in_v2=True,
    ),
    # ---------------------------------------------------------------------------
    # 输入层（2 专用 + 1 Smart 门面）
    # ---------------------------------------------------------------------------
    "DocumentParserAgent": AgentSpec(
        name="DocumentParserAgent",
        layer=AgentLayer.INPUT,
        kind=AgentKind.TOOL,
        module="agents.input.document_parser_agent",
        description="解析用户档案：txt/md/pdf/docx/图片/音视频（全模态 qwen3-omni-flash）",
        capabilities=["文本提取", "OCR", "元数据"],
        preferred_llm="qwen",
        smart_wrapper="SmartInputAgent",
        wired_in_v2=True,
    ),
    "WebCrawlerAgent": AgentSpec(
        name="WebCrawlerAgent",
        layer=AgentLayer.INPUT,
        kind=AgentKind.TOOL,
        module="agents.input.web_crawler_agent",
        description="aiohttp/Playwright 多源爬取；百度百科/搜索/图片",
        capabilities=["网页正文", "图片URL", "百度搜索", "百度图片", "图片质量过滤", "VL 视觉过滤"],
        preferred_llm="qwen",
        smart_wrapper="SmartInputAgent",
        wired_in_v2=True,
    ),
    "SmartInputAgent": AgentSpec(
        name="SmartInputAgent",
        layer=AgentLayer.INPUT,
        kind=AgentKind.REACT,
        module="agents.input.smart_input_agent",
        description="智能输入门面：自主选 parse_document / crawl_web（全模态）",
        preferred_llm="qwen",
        fallback_llms=[],
        wired_in_v2=True,
    ),
    # ---------------------------------------------------------------------------
    # 处理层
    # ---------------------------------------------------------------------------
    "ArchiveAnalysisAgent": AgentSpec(
        name="ArchiveAnalysisAgent",
        layer=AgentLayer.PROCESSING,
        kind=AgentKind.TOOL,
        module="agents.processing.archive_analysis_agent",
        description="档案类型识别、实体、时间线、主题（用 qwen-plus-latest）",
        preferred_llm="qwen",
        fallback_llms=[],
        smart_wrapper="SmartAnalysisAgent",
        wired_in_v2=True,
    ),
    "SmartAnalysisAgent": AgentSpec(
        name="SmartAnalysisAgent",
        layer=AgentLayer.PROCESSING,
        kind=AgentKind.REACT,
        module="agents.processing.smart_analysis_agent",
        description="智能分析门面：类型 / 实体 / 时间线 / 主题",
        preferred_llm="qwen",
        fallback_llms=[],
        wired_in_v2=True,
    ),
    # ---------------------------------------------------------------------------
    # 输出层（2 专用 + 1 Smart 门面）
    # ---------------------------------------------------------------------------
    "WebGalleryAgent": AgentSpec(
        name="WebGalleryAgent",
        layer=AgentLayer.OUTPUT,
        kind=AgentKind.TOOL,
        module="agents.output.web_gallery_agent",
        description="HTML 档案叙事网站生成",
        preferred_llm="qwen",
        fallback_llms=[],
        smart_wrapper="SmartOutputAgent",
        wired_in_v2=True,
    ),
    "Exhibition3DAgent": AgentSpec(
        name="Exhibition3DAgent",
        layer=AgentLayer.OUTPUT,
        kind=AgentKind.TOOL,
        module="agents.output.exhibition_3d_agent",
        description="A-Frame / Three.js 3D 虚拟展厅（用 qwen3.7-plus）",
        preferred_llm="qwen",
        fallback_llms=[],
        smart_wrapper="SmartOutputAgent",
        wired_in_v2=True,
    ),
    "SmartOutputAgent": AgentSpec(
        name="SmartOutputAgent",
        layer=AgentLayer.OUTPUT,
        kind=AgentKind.REACT,
        module="agents.output.smart_output_agent",
        description="智能输出门面：ReAct 选 generate_website / generate_3d_exhibition",
        preferred_llm="qwen",
        fallback_llms=[],
        wired_in_v2=True,
    ),
}

# 作业可选档案专题（与 settings.ARCHIVE_THEMES 对齐）
ARCHIVE_THEME_CHOICES = [
    "red_archives",
    "folk_archives",
    "intangible_heritage",
    "celebrity_archives",
    "social_media",
    "game_archives",
]

# V2 输出格式 → Agent 映射（仅保留 html / 3d 两种）
OUTPUT_FORMAT_TO_AGENT = {
    "html": "WebGalleryAgent",
    "3d_exhibition": "Exhibition3DAgent",
    "3d": "Exhibition3DAgent",
}


def list_agents_by_layer(layer: AgentLayer) -> List[AgentSpec]:
    return [s for s in AGENT_SPECS.values() if s.layer == layer]


def get_agent_spec(name: str) -> Optional[AgentSpec]:
    return AGENT_SPECS.get(name)
