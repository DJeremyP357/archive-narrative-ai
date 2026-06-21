import json
import re
from typing import Any, Dict, List, Optional

from core.llm_client import MultiLLMRouter
from core.react_agent import ReActAgent


# V2 Agent 目录 — 仅保留项目精简后实际使用的 8 个 Agent
AGENT_CATALOG = {
    "DocumentParserAgent": {
        "description": "解析用户提供的档案文件（文本、图片、视频、音频）",
        "capabilities": ["文本提取", "OCR 图片识别", "音频转写", "视频关键帧提取", "文件格式识别"],
        "input": "文件路径列表",
        "output": "结构化档案内容",
    },
    "WebCrawlerAgent": {
        "description": "从互联网爬取相关档案数据（文本、图片）",
        "capabilities": ["百度搜索", "网页内容提取", "图片下载", "老照片过滤", "VL 视觉模型二次筛选"],
        "input": "搜索关键词和目标",
        "output": "爬取的文本和图片数据",
    },
    "ArchiveAnalysisAgent": {
        "description": "深度分析档案内容，提取实体、时间线、主题、关系",
        "capabilities": ["档案类型识别", "实体提取", "时间线构建", "主题分析", "关系分析", "情感分析"],
        "input": "结构化档案内容",
        "output": "分析结果（实体、时间线、主题、关系）",
    },
    "WebGalleryAgent": {
        "description": "生成 HTML 档案展示网站",
        "capabilities": ["网站架构", "页面设计", "图片画廊", "时间线展示", "Reveal 动画", "响应式布局"],
        "input": "叙事设计方案",
        "output": "HTML 网站文件",
    },
    "Exhibition3DAgent": {
        "description": "生成 3D 虚拟展厅（A-Frame / Three.js）",
        "capabilities": ["VR 场景构建", "展品布局", "交互设计", "导览脚本"],
        "input": "叙事设计方案",
        "output": "3D 展厅 HTML",
    },
}


class PlannerAgent(ReActAgent):
    def __init__(self, llm_router: MultiLLMRouter):
        super().__init__(
            name="PlannerAgent",
            description="智能规划Agent — 根据用户需求动态决定调用哪些 Agent、以什么顺序执行",
            llm_router=llm_router,
            max_iterations=10,
        )

    async def answer_query(self, question: str) -> str:
        return await self._plan_workflow(question)

    async def plan(
        self, user_request: str, available_data: Dict = None
    ) -> Dict[str, Any]:
        catalog_str = json.dumps(AGENT_CATALOG, ensure_ascii=False, indent=2)
        data_str = ""
        if available_data:
            data_str = f"\n当前已有数据：\n{json.dumps(available_data, ensure_ascii=False, default=str)[:3000]}\n"

        prompt = f"""你是一个智能工作流规划器。用户提出了以下需求：

「{user_request}」

可用 Agent 列表（V2 仅保留这些）：
{catalog_str}
{data_str}
请规划工作流，输出 JSON 格式：
{{
    "analysis": "分析用户需求，判断需要哪些能力",
    "workflow": [
        {{
            "step": 1,
            "agent": "Agent 名称",
            "task": "该 Agent 需要完成的具体任务描述",
            "input_from": ["上游 Agent 名称"],
            "output_key": "输出数据的键名（必须使用下表中的规范键名）"
        }}
    ],
    "output_formats": ["最终输出的格式列表，可选 html 或 3d"],
    "estimated_iterations": 估计总步骤数
}}

【重要】output_key 规范键名对照表（必须严格遵守）：
- WebCrawlerAgent → output_key: "crawled_data"
- DocumentParserAgent → output_key: "parsed_files"
- ArchiveAnalysisAgent → output_key: "analysis_result"
- SmartAnalysisAgent → output_key: "analysis_result"
- WebGalleryAgent → output_key: "website"
- Exhibition3DAgent → output_key: "exhibition_3d"
- SmartOutputAgent → output_key: "smart_output"

规则：
1. 如果用户提供了文件，第一步必须是 DocumentParserAgent
2. 如果当前已有数据中的 enable_crawl 为 false，严禁加入 WebCrawlerAgent
3. 如果 enable_crawl 不为 false 且需要网络材料，可以加入 WebCrawlerAgent
4. ArchiveAnalysisAgent 是必经的中间分析步骤
5. 输出 Agent 必须严格根据当前已有数据中的 output_formats 选择：包含 html 才加入 WebGalleryAgent，包含 3d 才加入 Exhibition3DAgent
6. 数据通过 output_key 在 Agent 间流转（input_from 使用上游 Agent 的名称，不是 output_key）
7. 尽量并行执行无依赖的步骤
8. 重要：只能使用上面"可用 Agent 列表"中列出的 Agent 名称，严禁编造不存在的 Agent
9. 重要：output_key 必须严格使用上面"规范键名对照表"中的值"""

        try:
            response = await self.llm_router.chat_with_fallback(
                [
                    {"role": "system", "content": "你是工作流规划专家，只输出 JSON"},
                    {"role": "user", "content": prompt},
                ],
                agent_name="PlannerAgent"  # 使用 qwen3-max 最强模型进行规划
            )
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                plan = json.loads(json_match.group())
                return plan
        except Exception as e:
            pass

        return self._fallback_plan(user_request, available_data)

    def _fallback_plan(
        self, user_request: str, available_data: Dict = None
    ) -> Dict[str, Any]:
        workflow = []
        has_files = available_data and available_data.get("files")
        enable_crawl = not available_data or available_data.get("enable_crawl", True) is not False
        formats = available_data.get("output_formats", ["html"]) if available_data else ["html"]
        if isinstance(formats, str):
            formats = [formats]

        if has_files:
            workflow.append({
                "step": 1,
                "agent": "DocumentParserAgent",
                "task": "解析用户提供的档案文件",
                "input_from": [],
                "output_key": "parsed_files",
            })
        if enable_crawl:
            workflow.append({
                "step": len(workflow) + 1,
                "agent": "WebCrawlerAgent",
                "task": f"爬取与「{user_request[:50]}」相关的档案数据",
                "input_from": [],
                "output_key": "crawled_data",
            })

        workflow.append({
            "step": len(workflow) + 1,
            "agent": "ArchiveAnalysisAgent",
            "task": "深度分析档案内容",
            "input_from": [w["agent"] for w in workflow],
            "output_key": "analysis_result",
        })

        if "html" in formats:
            workflow.append({
                "step": len(workflow) + 1,
                "agent": "WebGalleryAgent",
                "task": "生成 HTML 档案展示网站",
                "input_from": ["ArchiveAnalysisAgent"],
                "output_key": "website",
            })
        if "3d" in formats or "3d_exhibition" in formats:
            workflow.append({
                "step": len(workflow) + 1,
                "agent": "Exhibition3DAgent",
                "task": "生成 3D 虚拟展厅",
                "input_from": ["ArchiveAnalysisAgent"],
                "output_key": "exhibition_3d",
            })

        return {
            "analysis": f"用户需求：{user_request[:100]}",
            "workflow": workflow,
            "output_formats": formats,
            "estimated_iterations": len(workflow),
        }

    async def replan(
        self,
        original_plan: Dict,
        failed_step: Dict,
        error: str,
        completed_results: Dict,
    ) -> Dict[str, Any]:
        prompt = f"""原计划执行失败，需要重新规划。

原计划：{json.dumps(original_plan, ensure_ascii=False)}
失败的步骤：{json.dumps(failed_step, ensure_ascii=False)}
错误信息：{error}
已完成的步骤结果：{json.dumps(completed_results, ensure_ascii=False, default=str)[:2000]}

请调整工作流，跳过或替换失败的步骤，输出调整后的 JSON 计划。
只能使用：WebCrawlerAgent / DocumentParserAgent / ArchiveAnalysisAgent / WebGalleryAgent / Exhibition3DAgent / SmartOutputAgent。"""

        try:
            response = await self.llm_router.chat_with_fallback(
                [
                    {"role": "system", "content": "你是工作流规划专家，只输出 JSON"},
                    {"role": "user", "content": prompt},
                ],
                agent_name="PlannerAgent"
            )
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass

        return original_plan
