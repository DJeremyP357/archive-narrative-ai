import json
import re
from typing import Any, Dict, List, Optional

from core.llm_client import MultiLLMRouter
from core.react_agent import ReActAgent
from core.tool_registry import ToolParameter

from agents.output.web_gallery_agent import WebGalleryAgent
from agents.output.exhibition_3d_agent import Exhibition3DAgent


class SmartOutputAgent(ReActAgent):
    """智能输出 Agent — HTML 网站 + 3D 虚拟展厅"""

    def __init__(self, llm_router: MultiLLMRouter):
        super().__init__(
            name="SmartOutputAgent",
            description="智能输出 Agent — HTML 网站 / 3D 展厅",
            llm_router=llm_router,
            tool_categories=["output"],
            max_iterations=8,
        )
        self._web = WebGalleryAgent()
        self._3d = Exhibition3DAgent()
        self._register_tools()

    def _register_tools(self):
        registry = self.tool_registry

        registry.register(
            name="generate_website",
            description="生成 HTML 档案展示网站（米白底+棕褐点缀+Reveal 动画+噪点纹理）",
            parameters=[
                ToolParameter(name="narrative_data", type="string", description="叙事设计数据 JSON"),
                ToolParameter(name="output_dir", type="string", description="输出目录路径", required=False),
            ],
            handler=self._tool_generate_website,
            category="output",
        )

        registry.register(
            name="generate_3d_exhibition",
            description="生成 3D 虚拟展厅（A-Frame/Three.js）",
            parameters=[
                ToolParameter(name="narrative_data", type="string", description="叙事设计数据 JSON"),
                ToolParameter(name="output_dir", type="string", description="输出目录路径", required=False),
            ],
            handler=self._tool_generate_3d,
            category="output",
        )

    async def _tool_generate_website(self, narrative_data: str, output_dir: str = "outputs") -> str:
        data = self._parse_narrative_data(narrative_data)
        result = await self._web.execute({
            "data": data,
            "gallery_images": data.get("downloaded_images", []) if isinstance(data, dict) else [],
            "theme": data.get("archive_type", "custom") if isinstance(data, dict) else "custom",
            "output_dir": output_dir,
        })
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    async def _tool_generate_3d(self, narrative_data: str, output_dir: str = "outputs") -> str:
        data = self._parse_narrative_data(narrative_data)
        if isinstance(data, dict):
            data["output_dir"] = output_dir
        result = await self._3d.execute({
            "initial_input": data,
            "dependencies": {},
        })
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    def _parse_narrative_data(self, data_str: str) -> Dict:
        if isinstance(data_str, dict):
            return data_str
        if not isinstance(data_str, str):
            return {"content": data_str}
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*?\}", data_str)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {
                "archive_title": "档案数字叙事",
                "overview": data_str[:1000],
                "narrative_design": data_str,
                "timeline": [],
                "figures": [],
                "key_stats": {},
            }

    async def answer_query(self, question: str) -> str:
        return (
            "SmartOutputAgent: 我可以生成 HTML 档案展示网站或 3D 虚拟展厅。"
            "请提供叙事数据（narrative_data JSON 字符串）。"
        )
