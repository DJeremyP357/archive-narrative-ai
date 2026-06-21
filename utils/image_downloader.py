"""
图片下载器与验证器

ImageDownloader — 批量下载图片，支持去重、尺寸校验、VL 验证
ImageVerifier — 委托到 core.vision_service.VisionService（向后兼容壳）
"""

import asyncio
import hashlib
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from config.settings import settings
from core.vision_service import VisionService, JUNK_IMAGE_URL_PATTERNS, is_good_image_url


# ============================================================================
# ImageVerifier — 委托到 VisionService 的薄壳
# ============================================================================

class ImageVerifier:
    """使用千问VL模型验证图片 — 委托到 VisionService。

    保留此类仅为向后兼容。新代码请直接使用 VisionService。
    """

    def __init__(self, api_key: str = None, threshold: float = 0.72):
        self._svc = VisionService(api_key=api_key)
        self.threshold = threshold

    async def verify_image(self, image_path: str, keywords: List[str],
                            theme: str = "", context: str = "") -> Dict:
        """验证图片是否与给定关键词/主题相关。"""
        return await self._svc.verify_image(image_path, keywords, theme, context=context)

    async def close(self):
        await self._svc.close()


# ============================================================================
# ImageDownloader — 图片批量下载
# ============================================================================

class ImageDownloader:
    VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    MIN_SIZE_BYTES = 12 * 1024
    MAX_SIZE_BYTES = 20 * 1024 * 1024
    MIN_WIDTH = 420
    MIN_HEIGHT = 260
    MIN_AREA = 180_000
    MAX_CONCURRENT = 8

    def __init__(
        self, output_dir: str, max_images: int = 30,
        verify_keywords: List[str] = None, theme: str = "",
    ):
        self.output_dir = output_dir
        self.max_images = max_images
        self.downloaded: List[Dict] = []
        self._content_hashes: set = set()
        self._hash_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._session: Optional[aiohttp.ClientSession] = None
        self._verify_keywords = verify_keywords or []
        self._theme = theme
        self._verifier = VisionService() if verify_keywords else None
        self._rejected: List[Dict] = []

    async def download_batch(self, image_urls: List) -> List[Dict]:
        os.makedirs(os.path.join(self.output_dir, "images"), exist_ok=True)

        candidates = []
        seen = set()
        for item in image_urls:
            if isinstance(item, dict):
                url = item.get("url") or item.get("src") or ""
                meta = dict(item)
            else:
                url = str(item)
                meta = {"url": url}
            if not url or url in seen:
                continue
            seen.add(url)
            meta["url"] = url
            candidates.append(meta)
        candidates.sort(key=lambda x: x.get("source_score", 0), reverse=True)
        unique_urls = candidates[:self.max_images * 4]

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

        try:
            tasks = [self._download_one(item) for item in unique_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, dict) and r.get("verified", True):
                    self.downloaded.append(r)
                    if len(self.downloaded) >= self.max_images:
                        break
                elif isinstance(r, dict) and not r.get("verified", True):
                    self._rejected.append(r)
        finally:
            if self._session and not self._session.closed:
                await self._session.close()
            if self._verifier:
                await self._verifier.close()

        return self.downloaded

    async def _download_one(self, item) -> Optional[Dict]:
        async with self._semaphore:
            try:
                meta = dict(item) if isinstance(item, dict) else {"url": str(item)}
                url = meta.get("url") or meta.get("src") or ""

                # ── URL 质量过滤（使用统一的 junk 规则） ──
                if not is_good_image_url(url, meta.get("alt", "")):
                    return {"url": url, "verified": False,
                            "reason": "blocked by junk pattern", **meta}

                ext = self._get_extension(url)
                if ext not in self.VALID_EXTENSIONS:
                    return None

                # ── 下载 ──
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        return None

                    content_type = resp.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        return None

                    data = await resp.read()
                    if len(data) < self.MIN_SIZE_BYTES or len(data) > self.MAX_SIZE_BYTES:
                        return {
                            "url": url, "verified": False,
                            "reason": f"bad file size: {len(data)}", **meta,
                        }

                # ── 尺寸校验 ──
                dimensions = self._get_image_dimensions(data)
                if not dimensions:
                    return None
                width, height = dimensions
                if width < self.MIN_WIDTH or height < self.MIN_HEIGHT or width * height < self.MIN_AREA:
                    return {
                        "url": url, "verified": False,
                        "reason": f"bad dimensions: {width}x{height}",
                        "width": width, "height": height, **meta,
                    }

                # ── 内容去重（SHA-256） ──
                content_hash = hashlib.sha256(data).hexdigest()
                async with self._hash_lock:
                    if content_hash in self._content_hashes:
                        return None
                    self._content_hashes.add(content_hash)

                # ── VL 验证：在写盘之前用 bytes 验证，附带上下文 ──
                # 有充分上下文的图片跳过 VL 验证（上下文已提供相关性保证）
                verification = None
                context = meta.get("context", meta.get("alt", ""))
                skip_vl = bool(context and len(context) >= 20)
                if self._verifier and self._verify_keywords and not skip_vl:
                    verification = await self._verifier.verify_bytes(
                        data, content_type, self._verify_keywords, self._theme,
                        context=context,
                    )
                    if not verification.get("relevant", False):
                        return {
                            "url": url, "verified": False,
                            "reason": f"VL rejected: {verification.get('reason', '')[:100]}",
                            "verification": verification,
                            "width": width, "height": height, "content_type": content_type,
                            **meta,
                        }

                # ── 验证通过 → 写盘 ──
                url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
                filename = f"{url_hash}{ext}"
                filepath = os.path.join(self.output_dir, "images", filename)

                with open(filepath, "wb") as f:
                    f.write(data)

                result = {
                    **meta,
                    "url": url,
                    "local_path": filepath,
                    "relative_path": f"images/{filename}",
                    "size_bytes": len(data),
                    "file_size": len(data),
                    "width": width,
                    "height": height,
                    "content_type": content_type,
                    "verified": True,
                }

                if verification:
                    result["verification"] = verification
                elif skip_vl and context:
                    result["verification"] = {"relevant": True, "reason": "跳过VL验证（有上下文保证）", "source": "context_skip"}

                return result

            except Exception:
                return None

    @classmethod
    def _is_blocked_url(cls, url: str) -> bool:
        """兼容旧接口，委托到统一规则。"""
        return not is_good_image_url(url)

    @staticmethod
    def _get_image_dimensions(data: bytes) -> Optional[tuple]:
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(data)) as img:
                return img.size
        except Exception:
            return None

    @staticmethod
    def _get_extension(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.lower()
        basename = os.path.splitext(path)[1]
        if basename in ImageDownloader.VALID_EXTENSIONS:
            return basename
        return ".jpg"

    def get_random_images(self, count: int) -> List[Dict]:
        import random
        pool = list(self.downloaded)
        random.shuffle(pool)
        return pool[:min(count, len(pool))]

    def get_rejected_count(self) -> int:
        return len(self._rejected)

    def image_html_tag(self, img: Dict, alt: str = "", width: str = "100%") -> str:
        return (
            f'<img src="{img["relative_path"]}" alt="{alt}" '
            f'loading="lazy" style="width:{width};border-radius:8px">'
        )


def create_image_html_gallery(images: List[Dict], cols: int = 3) -> str:
    if not images:
        return ""

    items = ""
    for img in images:
        alt_text = img.get("alt", img.get("description", "档案图片"))
        rel_path = img.get("relative_path", "")
        items += (
            f'<div class="gallery-item">'
            f'<img src="{rel_path}" alt="{alt_text}" loading="lazy">'
            f'</div>'
        )

    return f"""<div class="img-gallery" style="display:grid;grid-template-columns:repeat({cols},1fr);gap:15px;margin:20px 0">
{items}
</div>
<style>.gallery-item img{{width:100%;height:200px;object-fit:cover;border-radius:8px;transition:transform 0.3s}}
.gallery-item img:hover{{transform:scale(1.5)}}</style>"""
