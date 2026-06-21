"""
千问视觉模型客户端 — 向后兼容薄包装

委托到 core.vision_service.VisionService 执行所有实际工作。
保留此文件是为了兼容已有调用方 (crawl_helpers.py、exhibition_3d_agent.py 等)。
"""

import asyncio
from typing import Any, Dict, List, Optional

from core.vision_service import VisionService


class VisionClient:
    """通义千问视觉模型客户端 — 委托到 VisionService。

    保留与旧版相同的公开 API 以兼容现有调用方。
    新增方法 (select_best_image_for_event 等) 保持不变。
    """

    def __init__(self, api_key: Optional[str] = None):
        self._svc = VisionService(api_key=api_key)

    # ── 委托方法 ──

    async def analyze_image(self, image_path: str, prompt: str = None) -> Dict[str, Any]:
        return await self._svc.analyze_image(image_path, prompt)

    async def batch_analyze(
        self, image_paths: List[str], max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        return await self._svc.batch_analyze(image_paths, max_concurrent)

    async def categorize_images(
        self, image_paths: List[str],
    ) -> Dict[str, List[str]]:
        return await self._svc.categorize_images(image_paths)

    async def close(self):
        await self._svc.close()

    # ── 兼容旧版辅助方法 ──

    @staticmethod
    def _encode_image(image_path: str) -> str:
        """兼容旧版调用：读取图片并 base64 编码（无缩放）。"""
        import base64
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _parse_analysis(content: str) -> Dict[str, Any]:
        """兼容旧版调用：解析 VL 模型响应（委托到统一实现）。"""
        from core.vision_service import parse_json_from_vl_response
        defaults = {
            "description": content[:200],
            "tags": [],
            "quality_score": 5,
            "suitable_for": ["gallery"],
            "has_people": False,
            "has_text": False,
            "has_landscape": False,
            "has_historical_content": False,
            "mood": "neutral",
            "authority_score": 5,
            "historical_score": 5,
            "era": "无法判断",
            "content_type": "other",
        }
        return parse_json_from_vl_response(content, defaults)

    async def select_best_image_for_event(
        self, event_description: str, image_analyses: List[Dict[str, Any]],
    ) -> Optional[str]:
        """为特定事件选择最合适的图片（保留原逻辑）。"""
        if not image_analyses:
            return None

        scored = []
        for analysis in image_analyses:
            if isinstance(analysis, Exception):
                continue
            if analysis.get("error"):
                continue
            score = analysis.get("quality_score", 5)
            desc = analysis.get("description", "")

            event_words = set(event_description.lower().split())
            desc_words = set(desc.lower().split())
            overlap = len(event_words & desc_words)
            score += overlap * 2

            scored.append((score, analysis.get("path", ""), analysis))

        scored.sort(reverse=True)
        return scored[0][1] if scored else None
