"""
统一的千问视觉模型服务 (VisionService)

合并了分散在 ImageVerifier、VisionClient 和 crawl_helpers 中的三套独立 VL 调用逻辑，
提供唯一的 DashScope qwen3-vl-235b-a22b-instruct 客户端实现。

核心改进：
- 图片预处理缩放（Pillow）→ 避免超分辨率图片撑爆 API payload
- 指数退避重试 → 网络抖动不再永久拒绝图片
- 非贪婪 JSON 解析 + 括号平衡修复 → 应对 LLM 输出的格式变异
- verify_bytes() → 支持先验证再写盘，消除写盘→拒绝→删除的浪费 I/O
- 统一的垃圾域名/URL 规则 → 合并自 3 个来源，一处维护
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from config.settings import settings


# ============================================================================
# 统一的垃圾图片过滤规则（合并自 web_crawler_agent、image_downloader、crawl_helpers）
# ============================================================================

JUNK_IMAGE_URL_PATTERNS = (
    # ── 缩略图 / 占位图 ──
    "bing.net/th/id/", "mm.bing.net/th/", "tse", "thumbnail", "thumb",
    # ── UI 元素 ──
    "logo", "subscribe", "lazy.", "lazy-", "wx_lazy", "avatar", "sprite", "favicon",
    "emotion/icon_", "划线引导", "res.wx.qq.com/",  # 微信 UI/表情/引导图
    # ── 百度缩略图参数 ──
    "maxl_1", "maxl_2", "maxl_3", "maxl_21",
    "/smart/", "bkimg-process",
    # ── 百度百科前端资源（非正文图片） ──
    "baikebcs.bdimg.com/baike-react/common/",
    "baikebcs.bdimg.com/front-end/",
    "ss0.bdstatic.com/",
    "bdstatic.com/img/",
    "bdstatic.com/r/www/cache/",
    "bjh/user/",
    "bjh/portrait/",
    "size=f242,162",
    "size=f352,234",
    # ── 内联数据 / SVG ──
    "data:image/svg",
    # ── 图库水印域名 ──
    "pinterest.com/pin/",
    # ── 图标 ──
    "icon", "avatar",
)

JUNK_IMAGE_DOMAINS = (
    "pinterest.com", "shutterstock.com", "alamy.com", "gettyimages.com",
    "istockphoto.com", "123rf.com", "dreamstime.com", "depositphotos.com",
    "adobe.stock", "freepik.com", "pexels.com",
)

# 无效宽高比（横幅广告、透明占位条等）
MAX_ASPECT_RATIO = 4.0
MIN_ASPECT_RATIO = 0.25


def is_good_image_url(src: str, alt: str = "") -> bool:
    """统一的图片 URL 质量过滤（替代分散在多处的 _good_image_url / _is_blocked_url）。"""
    if not src or not src.startswith("http"):
        return False
    low = src.lower()
    if any(p in low for p in JUNK_IMAGE_URL_PATTERNS):
        return False
    try:
        domain = urlparse(src).netloc.lower()
    except Exception:
        return False
    if any(d in domain for d in JUNK_IMAGE_DOMAINS):
        return False
    if (not alt or len(alt.strip()) < 2) and any(
        flag in low for flag in ["bkimg-process", "smart/", "baikebcs"]
    ):
        return False
    return True


# ============================================================================
# VL Prompt 模板
# ============================================================================

PROMPT_VERIFY = """你是档案馆图片筛选专家。请判断这张图片是否适合放入「{theme}」档案叙事网站。

判定标准：
1. 主题相关性：图片内容与「{kw_str}」有关联即可通过（不要求完美匹配）
2. 只要不是以下情况，都应该通过：
   - 纯色块/空白图片
   - 搜索引擎导航按钮/logo
   - 广告横幅/弹窗
   - 明显的现代无关自拍/生活照
3. 以下情况应该通过：
   - 人物照片（哪怕是现代拍摄的相关人物）
   - 历史照片（黑白/泛黄/老照片质感）
   - 档案文件照片（手稿、证件、文件、题词）
   - 建筑/场景（相关地点、纪念馆、博物馆）
   - 标志/徽章/纪念物
   - 书籍/报刊/文献照片
   - 即使是现代翻拍的历史物件也应通过
4. 只要图片质量不是极差（严重模糊、完全无法辨认主体），就应通过
5. 评分维度（1-10）：
   - quality_score：图片清晰度
   - historical_score：历史关联度（现代翻拍的历史场景也可给6-7分）

只用 JSON 回答：
{{"relevant": true/false, "score": 0.0-1.0, "quality_score": 1-10, "historical_score": 1-10, "description": "图片内容30字中文描述", "reason": "简短理由", "era": "大致年代", "content_type": "portrait/document/scene/object/other"}}

{context_section}"""


PROMPT_ANALYZE = """你是档案馆图片分析专家。请仔细分析这张图片并返回纯JSON（不要markdown代码块，不要任何解释）：
{{
  "description": "图片内容的简短中文描述（30字内）",
  "has_people": true或false,
  "has_text": true或false,
  "has_landscape": true或false,
  "has_historical_content": true或false,
  "suitable_for": ["figures"或"timeline"或"overview"或"gallery"],
  "quality_score": 1-10的数字,
  "authority_score": 1-10的数字,
  "historical_score": 1-10的数字,
  "tags": ["标签1","标签2"],
  "mood": "氛围描述",
  "era": "大致年代（如1930s/1950s/现代/无法判断）",
  "content_type": "portrait/document/scene/object/badge/other"
}}
suitable_for说明: figures=人物肖像/集体照, timeline=历史场景/建筑/风景,
overview=文档/手稿/证件/图表, gallery=器物/标志/纪念物/装饰
authority_score说明: 博物馆/档案馆馆藏=9-10, 大学/研究机构=7-8,
新闻媒体=5-6, 个人博客=2-4, 未知来源=1
historical_score说明: 原始档案原件=9-10, 同时代照片=7-8,
后期复制品=4-6, 现代重拍/插图=1-3"""


# ============================================================================
# JSON 解析工具
# ============================================================================

def parse_json_from_vl_response(content: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 VL 模型响应中稳健提取 JSON。
    策略：非贪婪匹配 → 括号平衡修复 → 关键词 fallback。
    """
    defaults = dict(defaults)
    if not content:
        return dict(defaults)

    # 尝试 1：非贪婪匹配 JSON 对象（处理嵌套和多余文本）
    # 找到第一个 { 和匹配的 }
    start = content.find("{")
    if start >= 0:
        depth = 0
        end = start
        for i, ch in enumerate(content[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            json_str = content[start:end]
            try:
                parsed = json.loads(json_str)
                result = dict(defaults)
                result.update({k: v for k, v in parsed.items() if k in defaults or k not in ("",)})
                if isinstance(result.get("suitable_for"), str):
                    result["suitable_for"] = [result["suitable_for"]]
                return result
            except json.JSONDecodeError:
                pass

    # 尝试 2：修复常见 JSON 错误后重试
    if start >= 0 and end > start:
        json_str = content[start:end]
        # 补末尾引号
        fixed = re.sub(r'(?<=[^\\])"\s*$', '"', json_str.strip())
        # 中文引号替换
        fixed = fixed.replace("“", '"').replace("”", '"')
        # 移除尾部不完整字段
        last_quote = max(
            fixed.rfind('"}'),
            fixed.rfind('"],'),
            fixed.rfind('"],'),
        )
        if last_quote > 0:
            bracket_count = fixed.count("{") - fixed.count("}")
            fixed = fixed[: last_quote + 2] + "}" * max(0, bracket_count)
        try:
            parsed = json.loads(fixed)
            result = dict(defaults)
            result.update({k: v for k, v in parsed.items() if k in defaults or k not in ("",)})
            return result
        except json.JSONDecodeError:
            pass

    # 尝试 3：关键词 fallback（从 VisionClient._parse_analysis 继承）
    content_lower = content.lower()
    defaults["has_people"] = any(
        kw in content_lower for kw in ["人物", "人物肖像", "人像", "portrait", "person"]
    )
    defaults["has_text"] = any(
        kw in content_lower for kw in ["文字", "文本", "手稿", "document", "text", "书页"]
    )
    defaults["has_landscape"] = any(
        kw in content_lower for kw in ["风景", "场景", "建筑", "landscape", "building", "scene"]
    )
    defaults["has_historical_content"] = any(
        kw in content_lower for kw in ["历史", "老照片", "档案", "古籍", "historic", "vintage"]
    )
    defaults["suitable_for"] = []
    if defaults["has_people"]:
        defaults["suitable_for"].append("figures")
    if defaults["has_landscape"] or defaults["has_historical_content"]:
        defaults["suitable_for"].extend(["timeline", "gallery"])
    if defaults["has_text"]:
        defaults["suitable_for"].append("overview")
    if not defaults["suitable_for"]:
        defaults["suitable_for"].append("gallery")
    defaults["description"] = content[:200]

    return defaults


# ============================================================================
# VisionService — 统一 VL 客户端
# ============================================================================

class VisionService:
    """统一的千问视觉模型客户端。

    所有图片分析/验证/分类任务经由此类调用，替代分散的：
    - ImageVerifier (image_downloader.py)
    - VisionClient (vision_client.py)
    - analyze_and_categorize_images 内联 VL 调用 (crawl_helpers.py)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_image_dim: int = 1024,
    ):
        self.api_key = api_key or settings.QWEN_API_KEY
        self.base_url = (base_url or settings.QWEN_BASE_URL
                         or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = model or settings.QWEN_MODEL_VL or "qwen3-vl-235b-a22b-instruct"
        self.max_image_dim = max_image_dim
        self._session: Optional[aiohttp.ClientSession] = None

    # ── 图片编码 ──

    @staticmethod
    def _load_and_encode(image_path: str, max_dim: int = 1024) -> Tuple[str, str]:
        """读取图片、缩放（如需要）、base64 编码。

        Returns:
            (base64_string, mime_type) — 如 ("iVBOR...", "image/jpeg")
        """
        from PIL import Image

        ext = os.path.splitext(image_path)[1].lower()
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jpe": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif", ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "image/jpeg")
        img_format = mime.split("/")[-1]  # jpeg, png, gif, bmp, webp

        with Image.open(image_path) as img:
            # RGBA → RGB（JPEG 不支持透明通道）
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
                mime = "image/jpeg"
                img_format = "jpeg"

            # 缩放（保持宽高比）
            w, h = img.size
            if max(w, h) > max_dim:
                ratio = max_dim / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            buf = BytesIO()
            save_format = "JPEG" if img_format.lower() in ("jpeg", "jpg", "jpe") else img_format.upper()
            if save_format == "WEBP":
                save_format = "WEBP"
            img.save(buf, format=save_format, quality=85)
            data = base64.b64encode(buf.getvalue()).decode("utf-8")

        return data, mime

    @staticmethod
    def _encode_bytes(image_bytes: bytes, mime: str = "image/jpeg", max_dim: int = 1024) -> str:
        """对内存中的图片 bytes 缩放后 base64 编码。"""
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as img:
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
                mime = "image/jpeg"
            w, h = img.size
            if max(w, h) > max_dim:
                ratio = max_dim / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buf = BytesIO()
            fmt = mime.split("/")[-1].upper()
            if fmt in ("JPG", "JPEG", "JPE"):
                fmt = "JPEG"
            img.save(buf, format=fmt, quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")

    # ── API 通信 ──

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _build_payload(self, image_b64: str, mime: str, prompt: str,
                       max_tokens: int = 512) -> Dict:
        return {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }

    async def _call_api(self, payload: Dict) -> Dict:
        """单次 API 调用（无重试）。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        session = await self._get_session()
        url = f"{self.base_url}/chat/completions"
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                return {"error": f"VL API {resp.status}: {error_text[:300]}"}
            result = await resp.json()
            content = (result.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
            return {"content": content}

    async def _call_with_retry(self, payload: Dict, max_retries: int = 3) -> Dict:
        """带指数退避的 API 调用。"""
        last_error = None
        for attempt in range(max_retries):
            result = await self._call_api(payload)
            if "content" in result:
                return result
            last_error = result.get("error", "Unknown error")
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                await asyncio.sleep(delay)
        return {"content": "", "error": last_error}

    # ── 公开 API ──

    def _build_verify_prompt(
        self, keywords: List[str], theme: str = "", context: str = "",
    ) -> str:
        """构建验证 prompt，可选附加上下文信息。"""
        kw_str = "、".join(keywords[:8])
        context_section = ""
        if context:
            context_section = (
                f"\n\n【图片在原文中的上下文信息】\n{context[:300]}\n"
                f"请结合这些上下文信息判断图片是否适合放入档案叙事网站。"
                f"如果上下文明确说明图片与主题相关，应该放宽标准。"
            )
        return PROMPT_VERIFY.format(
            theme=theme or kw_str,
            kw_str=kw_str,
            context_section=context_section,
        )

    async def _verify_core(
        self, image_b64: str, mime: str,
        keywords: List[str], theme: str = "", context: str = "",
    ) -> Dict[str, Any]:
        """图片验证核心逻辑（verify_bytes / verify_image 共用）。"""
        try:
            prompt = self._build_verify_prompt(keywords, theme, context)
            payload = self._build_payload(image_b64, mime, prompt, max_tokens=300)
            result = await self._call_with_retry(payload)

            if result.get("error"):
                return {
                    "relevant": context != "",
                    "score": 0.5 if context else 0.0,
                    "reason": f"VL API 失败: {result['error'][:100]}",
                    "description": context[:80] if context else "",
                    "content_type": "other",
                }

            content = result.get("content", "")
            parsed = parse_json_from_vl_response(content, {
                "relevant": False, "score": 0.0,
                "quality_score": 5, "historical_score": 5,
                "description": "", "reason": "", "era": "", "content_type": "other",
            })

            score = float(parsed.get("score", 0.0) or 0.0)
            quality = float(parsed.get("quality_score", 5) or 5) / 10.0
            historical = float(parsed.get("historical_score", 5) or 5) / 10.0
            composite = score * 0.5 + quality * 0.25 + historical * 0.25
            parsed["composite_score"] = round(composite, 3)

            model_says_relevant = bool(parsed.get("relevant", False))
            if context and not model_says_relevant and composite >= 0.35:
                parsed["relevant"] = True
                parsed["reason"] = (parsed.get("reason", "") +
                                    " [上下文辅助通过]")
            else:
                parsed["relevant"] = model_says_relevant

            return parsed
        except Exception as e:
            return {
                "relevant": context != "",
                "score": 0.5 if context else 0.0,
                "reason": f"验证异常: {str(e)[:100]}",
                "description": context[:80] if context else "",
                "content_type": "other",
            }

    async def verify_bytes(
        self, image_bytes: bytes, mime: str,
        keywords: List[str], theme: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        """验证内存中图片是否与关键词/主题相关。

        Args:
            context: 图片在原文章中的上下文文字，用于辅助判断

        Returns:
            {"relevant": bool, "score": float, "description": str,
             "era": str, "content_type": str, "composite_score": float, ...}
        """
        if not self.api_key:
            return {
                "relevant": True, "score": 1.0,
                "reason": "未配置 API Key，跳过验证",
                "description": "", "content_type": "other",
            }

        image_b64 = self._encode_bytes(image_bytes, mime, self.max_image_dim)
        return await self._verify_core(image_b64, mime, keywords, theme, context)

    async def verify_image(
        self, image_path: str, keywords: List[str], theme: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        """验证图片文件是否与关键词/主题相关。

        Args:
            context: 图片在原文章中的上下文文字
        """
        if not self.api_key:
            return {
                "relevant": True, "score": 1.0,
                "reason": "未配置 API Key，跳过验证",
                "description": "", "content_type": "other",
            }

        if not os.path.exists(image_path):
            return {
                "relevant": False, "score": 0.0,
                "reason": f"图片不存在: {image_path}",
                "description": "", "content_type": "other",
            }

        image_b64, mime = self._load_and_encode(image_path, self.max_image_dim)
        return await self._verify_core(image_b64, mime, keywords, theme, context)

    async def analyze_image(self, image_path: str, prompt: str = None) -> Dict[str, Any]:
        """分析单张图片内容（替代 VisionClient.analyze_image）。

        Returns:
            {"description": str, "tags": [...], "quality_score": int,
             "has_people": bool, "has_text": bool, "has_landscape": bool,
             "has_historical_content": bool, "suitable_for": [...],
             "authority_score": int, "historical_score": int,
             "mood": str, "era": str, "content_type": str, "path": str}
        """
        if not self.api_key:
            return {"error": "未配置 API Key", "path": image_path}

        if not os.path.exists(image_path):
            return {"error": f"图片不存在: {image_path}", "path": image_path}

        try:
            image_b64, mime = self._load_and_encode(image_path, self.max_image_dim)
            payload = self._build_payload(
                image_b64, mime,
                prompt or PROMPT_ANALYZE,
                max_tokens=1024,
            )
            result = await self._call_with_retry(payload)

            if result.get("error"):
                return {"error": result["error"], "path": image_path}

            content = result.get("content", "")
            defaults = {
                "description": content[:200], "tags": [], "quality_score": 5,
                "suitable_for": ["gallery"], "has_people": False,
                "has_text": False, "has_landscape": False,
                "has_historical_content": False, "mood": "neutral",
                "authority_score": 5, "historical_score": 5,
                "era": "无法判断", "content_type": "other",
            }
            parsed = parse_json_from_vl_response(content, defaults)
            parsed["path"] = image_path
            return parsed

        except Exception as e:
            return {"error": f"分析异常: {str(e)[:200]}", "path": image_path}

    async def batch_analyze(
        self, image_paths: List[str], max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """批量分析图片（替代 VisionClient.batch_analyze）。"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _analyze_one(path: str) -> Dict[str, Any]:
            async with semaphore:
                return await self.analyze_image(path)

        tasks = [_analyze_one(p) for p in image_paths]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def categorize_images(
        self, image_paths: List[str],
    ) -> Dict[str, List[str]]:
        """将图片分类到不同用途（替代 VisionClient.categorize_images）。

        Returns: {"figures": [...], "timeline": [...], "gallery": [...], "overview": [...]}
        """
        analyses = await self.batch_analyze(image_paths)

        categories: Dict[str, List[str]] = {
            "figures": [], "timeline": [], "gallery": [], "overview": [],
        }

        for analysis in analyses:
            if isinstance(analysis, Exception):
                continue
            if analysis.get("error"):
                continue
            path = analysis.get("path", "")
            suitable = analysis.get("suitable_for", ["gallery"])
            has_people = analysis.get("has_people", False)
            has_text = analysis.get("has_text", False)
            has_landscape = analysis.get("has_landscape", False)
            has_historical = analysis.get("has_historical_content", False)
            quality = analysis.get("quality_score", 5)

            # 低质量图片直接跳过
            if quality < 3:
                continue

            if "figures" in suitable and has_people:
                categories["figures"].append(path)
            elif "overview" in suitable and has_text:
                categories["overview"].append(path)
            elif "timeline" in suitable and (has_landscape or has_historical):
                categories["timeline"].append(path)
            else:
                categories["gallery"].append(path)

        return categories

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
