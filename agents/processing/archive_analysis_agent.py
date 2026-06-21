import json
import re
from typing import Any, Dict, List, Optional
from datetime import datetime

from core.base_agent import BaseAgent, TaskResult
from core.llm_client import LLMClient, LLMProvider, MultiLLMRouter
from config.settings import settings

class ArchiveAnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="ArchiveAnalysisAgent",
            description="档案内容分析Agent，进行实体抽取、时间线构建、关联分析"
        )
        self.llm_router = MultiLLMRouter()
        if settings.QWEN_API_KEY:
            self.llm_router.register_client(LLMProvider.QWEN, LLMClient(LLMProvider.QWEN))
    
    async def execute(self, task_input: Dict[str, Any]) -> TaskResult:
        archive_data = task_input.get("initial_input", {})
        parsed_files = task_input.get("dependencies", {}).get("DocumentParserAgent", {}).get("data", {}).get("parsed_files", [])
        
        if not parsed_files:
            parsed_files = archive_data.get("files", [])
        
        analysis_results = {
            "entity_extraction": {},
            "timeline": [],
            "relationships": [],
            "themes": [],
            "sentiment": {},
            "archive_type": "unknown"
        }
        
        try:
            # 1. 档案类型识别
            archive_type = await self._identify_archive_type(parsed_files)
            analysis_results["archive_type"] = archive_type
            
            # 2. 实体抽取
            entities = await self._extract_entities(parsed_files)
            analysis_results["entity_extraction"] = entities
            
            # 3. 时间线构建
            timeline = await self._build_timeline(parsed_files)
            analysis_results["timeline"] = timeline
            
            # 4. 关联分析
            relationships = await self._analyze_relationships(entities, timeline)
            analysis_results["relationships"] = relationships
            
            # 5. 主题分析
            themes = await self._analyze_themes(parsed_files)
            analysis_results["themes"] = themes
            
            # 6. 情感分析
            sentiment = await self._analyze_sentiment(parsed_files)
            analysis_results["sentiment"] = sentiment
            
            return TaskResult(
                success=True,
                data=analysis_results,
                metadata={"agent": self.name, "analysis_timestamp": datetime.now().isoformat()}
            )
            
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                data=analysis_results,
                metadata={"agent": self.name}
            )
    
    async def _identify_archive_type(self, parsed_files: List[Dict]) -> Dict[str, Any]:
        """识别档案类型和专题"""
        all_text = ""
        for file in parsed_files:
            if "content" in file:
                all_text += file["content"] + "\n"
            elif "slides" in file:
                for slide in file["slides"]:
                    all_text += slide.get("content", "") + "\n"
            elif "transcription" in file:
                all_text += file["transcription"] + "\n"
        
        if not all_text:
            return {"type": "unknown", "confidence": 0}
        
        prompt = f"""分析以下档案内容，判断其属于哪种档案类型：

可选类型：
1. 人物档案 - 历史人物、名人传记、家族谱系
2. 事件档案 - 历史事件、社会运动、重大活动
3. 地方档案 - 城市/乡村/社区的历史变迁
4. 机构档案 - 学校/企业/组织的创建与发展
5. 文献档案 - 手稿、信函、官方文件
6. 影像档案 - 照片集、纪录片
7. 非遗档案 - 非物质文化遗产、传统技艺
8. 技术档案 - 工程技术、科研记录
9. 自定义 - 用户指定的其他类型

档案内容片段：
{all_text[:2000]}

请输出JSON格式：
{{
    "type": "类型名称",
    "confidence": 0.95,
    "reasoning": "判断理由",
    "era": "年代/时期",
    "region": "地区"
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个档案分类专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            # 提取JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        
        return {"type": "general", "confidence": 0.5}
    
    async def _extract_entities(self, parsed_files: List[Dict]) -> Dict[str, List[Dict]]:
        """抽取档案中的实体"""
        all_text = self._extract_all_text(parsed_files)
        
        if not all_text:
            return {}
        
        prompt = f"""从以下档案内容中抽取关键实体，输出JSON格式：

档案内容：
{all_text[:3000]}

需要抽取的实体类型：
- persons: 人物（姓名、职务、角色）
- organizations: 组织机构
- locations: 地点
- events: 事件
- dates: 日期/时间
- objects: 物品/文物
- concepts: 概念/术语

输出格式：
{{
    "persons": [{{"name": "姓名", "role": "角色", "description": "描述"}}],
    "organizations": [{{"name": "名称", "type": "类型"}}],
    "locations": [{{"name": "地点", "type": "地点类型"}}],
    "events": [{{"name": "事件名", "date": "日期", "description": "描述"}}],
    "dates": [{{"expression": "日期表达式", "normalized": "标准化日期"}}],
    "objects": [{{"name": "物品名", "description": "描述"}}],
    "concepts": [{{"term": "术语", "explanation": "解释"}}]
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个档案信息抽取专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        
        return {}
    
    async def _build_timeline(self, parsed_files: List[Dict]) -> List[Dict]:
        """构建时间线"""
        all_text = self._extract_all_text(parsed_files)
        
        prompt = f"""从以下档案内容中提取时间线信息，按时间顺序排列：

档案内容：
{all_text[:3000]}

输出JSON格式：
{{
    "timeline": [
        {{
            "date": "日期（尽量精确）",
            "date_uncertainty": "日期不确定性（确定/大致/未知）",
            "event": "事件描述",
            "significance": "重要性（高/中/低）",
            "related_entities": ["相关人物/组织"],
            "source": "来源"
        }}
    ]
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个历史时间线构建专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("timeline", [])
        except Exception:
            pass
        
        return []
    
    async def _analyze_relationships(self, entities: Dict, timeline: List[Dict]) -> List[Dict]:
        """分析实体间关系"""
        prompt = f"""基于以下实体和时间线，分析它们之间的关系：

实体：
{json.dumps(entities, ensure_ascii=False, indent=2)[:2000]}

时间线：
{json.dumps(timeline, ensure_ascii=False, indent=2)[:2000]}

输出关系网络（JSON格式）：
{{
    "relationships": [
        {{
            "source": "源实体",
            "target": "目标实体",
            "relation": "关系类型",
            "description": "关系描述",
            "evidence": "证据"
        }}
    ]
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个关系分析专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("relationships", [])
        except Exception:
            pass
        
        return []
    
    async def _analyze_themes(self, parsed_files: List[Dict]) -> List[Dict]:
        """分析档案主题"""
        all_text = self._extract_all_text(parsed_files)
        
        prompt = f"""分析以下档案内容的主要主题：

档案内容：
{all_text[:2000]}

输出JSON格式：
{{
    "themes": [
        {{
            "theme": "主题名称",
            "keywords": ["关键词"],
            "description": "主题描述",
            "importance": 0.9
        }}
    ]
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个主题分析专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("themes", [])
        except Exception:
            pass
        
        return []
    
    async def _analyze_sentiment(self, parsed_files: List[Dict]) -> Dict[str, Any]:
        """情感分析"""
        all_text = self._extract_all_text(parsed_files)
        
        prompt = f"""分析以下档案内容的情感倾向和氛围：

档案内容：
{all_text[:1500]}

输出JSON格式：
{{
    "overall_sentiment": "整体情感（积极/消极/中性/复杂）",
    "emotions": ["情感标签"],
    "tone": "基调",
    "intensity": 0.8,
    "narrative_voice": "叙事声音（第一人称/第三人称/客观）"
}}"""
        
        try:
            response = await self.llm_router.chat_with_fallback([
                {"role": "system", "content": "你是一个文本情感分析专家"},
                {"role": "user", "content": prompt}
            ])
            
            content = response["choices"][0]["message"]["content"]
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        
        return {}
    
    def _extract_all_text(self, parsed_files: List[Dict]) -> str:
        """从解析的文件中提取所有文本"""
        all_text = ""
        for file in parsed_files:
            if isinstance(file, dict):
                if "content" in file:
                    all_text += file["content"] + "\n"
                elif "slides" in file:
                    for slide in file["slides"]:
                        if isinstance(slide, dict):
                            all_text += slide.get("content", "") + "\n"
                elif "transcription" in file:
                    all_text += file["transcription"] + "\n"
                elif "analysis" in file and "description" in file["analysis"]:
                    all_text += file["analysis"]["description"] + "\n"
        return all_text
