"""
Bilibili 适配器 — B站视频搜索 + 嵌入链接转换

处理 method: "bilibili_search"
"""

import re
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.session_manager import SessionManager


class BilibiliAdapter(BaseCrawlerAdapter):
    """B站视频搜索适配器"""

    NAME = "Bilibili"

    async def can_handle(self, target: CrawlTarget) -> bool:
        return (target.method == "bilibili_search"
                or "search.bilibili.com" in target.url)

    async def crawl(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name
        keywords = target.relevance_keywords

        session = await self.session_mgr.get_session()
        headers = self.session_mgr.get_headers()

        import asyncio as _asyncio
        import aiohttp

        retries = 3
        html = ""
        for attempt in range(retries):
            try:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as resp:
                    html = await resp.text()
                break
            except Exception:
                if attempt < retries - 1:
                    await _asyncio.sleep(2 ** attempt)
                else:
                    return CrawlResult(name=name, url=url, success=False,
                                       error="timeout after retries")

        soup = BeautifulSoup(html, "html.parser")
        bili_videos = self._extract_bilibili_results(soup, url, keywords)
        log_func(f"  B站搜索: 提取 {len(bili_videos)} 个视频", "PARSE")

        # 从 B 站搜索结果收集图片（封面）
        images = []
        for v in bili_videos:
            if v.get("cover"):
                images.append({"src": v["cover"],
                               "alt": v.get("title", "")[:80]})

        return CrawlResult(
            name=name, url=url, success=True,
            title=f"B站: {name}",
            text=f"B站搜索: {name}\n共 {len(bili_videos)} 个视频链接",
            text_length=len(f"B站搜索: {name}\n共 {len(bili_videos)} 个"),
            images=images[:30], videos=bili_videos[:10],
            status=200, method="bilibili_search",
        )

    @staticmethod
    def _extract_bilibili_results(
        soup: BeautifulSoup, base_url: str,
        relevance_keywords: list = None,
    ) -> list:
        videos = []
        seen = set()
        keywords = relevance_keywords or []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "bilibili.com/video/" not in href:
                continue
            full = urljoin(base_url, href)
            if full in seen:
                continue
            title = a.get_text(strip=True)[:100]
            if keywords and not any(
                kw in title or kw in full for kw in keywords
            ):
                continue
            seen.add(full)
            embed = BilibiliAdapter._convert_bilibili_embed(full)
            cover = ""
            img = a.find("img")
            if img:
                cover = urljoin(base_url,
                                img.get("src") or img.get("data-src") or "")
            videos.append({
                "src": embed, "title": title,
                "type": "bilibili", "cover": cover,
            })

        return videos

    @staticmethod
    def _convert_bilibili_embed(url: str) -> str:
        """B站链接 → 嵌入播放器链接。"""
        # BV 号格式
        m = re.search(r'bilibili\.com/video/(BV[\w]+)', url)
        if m:
            return (
                f"https://player.bilibili.com/player.html"
                f"?bvid={m.group(1)}&page=1&high_quality=1"
            )
        # av 号格式
        m = re.search(r'bilibili\.com/video/av(\d+)', url)
        if m:
            return (
                f"https://player.bilibili.com/player.html"
                f"?aid={m.group(1)}&page=1&high_quality=1"
            )
        return url
