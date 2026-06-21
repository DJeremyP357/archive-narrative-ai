import json
from typing import Any, Dict, List, Optional

from core.llm_client import MultiLLMRouter
from core.react_agent import ReActAgent
from core.tool_registry import ToolParameter

from agents.processing.archive_analysis_agent import ArchiveAnalysisAgent


class SmartAnalysisAgent(ReActAgent):
    """V2 智能分析 Agent — ReAct 调度 ArchiveAnalysisAgent 的子能力

    工具集：
      - identify_archive_type  识别档案类型
      - extract_entities       提取实体
      - build_timeline         构建时间线
      - analyze_themes         主题情感
      - full_analysis          一键全量分析
    """

    def __init__(self, llm_router: MultiLLMRouter):
        super().__init__(
            name="SmartAnalysisAgent",
            description="智能分析Agent — 自主决定如何深度分析档案内容（类型+实体+时间线+主题）",
            llm_router=llm_router,
            tool_categories=["analysis"],
            max_iterations=10,
        )
        self._analysis = ArchiveAnalysisAgent()
        self._analysis_cache: Dict[str, Dict] = {}
        self._register_tools()

    def _register_tools(self):
        registry = self.tool_registry

        registry.register(
            name="identify_archive_type",
            description="识别档案类型（红色档案/民生档案/非遗档案/名人档案等）",
            parameters=[
                ToolParameter(name="content", type="string", description="档案文本内容"),
            ],
            handler=self._tool_identify_type,
            category="analysis",
        )

        registry.register(
            name="extract_entities",
            description="从档案内容中提取关键实体（人物、地点、组织、事件）",
            parameters=[
                ToolParameter(name="content", type="string", description="档案文本内容"),
            ],
            handler=self._tool_extract_entities,
            category="analysis",
        )

        registry.register(
            name="build_timeline",
            description="从档案内容中构建时间线",
            parameters=[
                ToolParameter(name="content", type="string", description="档案文本内容"),
            ],
            handler=self._tool_build_timeline,
            category="analysis",
        )

        registry.register(
            name="analyze_themes",
            description="分析档案的主题和情感",
            parameters=[
                ToolParameter(name="content", type="string", description="档案文本内容"),
            ],
            handler=self._tool_analyze_themes,
            category="analysis",
        )

        registry.register(
            name="full_analysis",
            description="对档案内容进行完整深度分析（类型+实体+时间线+主题+关系）",
            parameters=[
                ToolParameter(name="content", type="string", description="档案文本内容"),
            ],
            handler=self._tool_full_analysis,
            category="analysis",
        )

    async def _run_analysis_once(self, content: str) -> Dict:
        key = f"{len(content)}:{hash(content) & 0xFFFFFFFF}"
        if key not in self._analysis_cache:
            result = await self._analysis.execute({
                "initial_input": {"files": [{"content": content}]},
                "dependencies": {},
            })
            self._analysis_cache[key] = result.to_dict()
        return self._analysis_cache[key]

    async def _tool_identify_type(self, content: str) -> str:
        data = await self._run_analysis_once(content)
        archive_type = data.get("data", {}).get("archive_type", {})
        return json.dumps(archive_type, ensure_ascii=False, default=str)

    async def _tool_extract_entities(self, content: str) -> str:
        data = await self._run_analysis_once(content)
        entities = data.get("data", {}).get("entity_extraction", {})
        return json.dumps(entities, ensure_ascii=False, default=str)

    async def _tool_build_timeline(self, content: str) -> str:
        data = await self._run_analysis_once(content)
        timeline = data.get("data", {}).get("timeline", {})
        return json.dumps(timeline, ensure_ascii=False, default=str)

    async def _tool_analyze_themes(self, content: str) -> str:
        data = await self._run_analysis_once(content)
        themes = data.get("data", {}).get("themes", {})
        return json.dumps(themes, ensure_ascii=False, default=str)

    async def _tool_full_analysis(self, content: str) -> str:
        data = await self._run_analysis_once(content)
        return json.dumps(data, ensure_ascii=False, default=str)

    async def answer_query(self, question: str) -> str:
        return "SmartAnalysisAgent: 我可以帮你分析档案内容。请提供档案数据。"
