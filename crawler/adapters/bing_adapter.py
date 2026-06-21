"""
Bing 适配器 — Bing 搜索、图片搜索、视频搜索

处理 method: "bing_search" / "bing_image_search" / "bing_video_search"
"""

import json
import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.session_manager import SessionManager


class BingAdapter(BaseCrawlerAdapter):
    """Bing 搜索引擎适配器"""

    NAME = "Bing"

    async def can_handle(self, target: CrawlTarget) -> bool:
        return target.method in ("bing_search", "bing_image_search",
                                 "bing_video_search")

    async def crawl(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name
        method = target.method

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

        if method == "bing_image_search":
            bing_images = self._extract_bing_images(soup, url)
            log_func(f"  Bing图片搜索: 提取 {len(bing_images)} 张原图", "PARSE")
            return CrawlResult(
                name=name, url=url, success=True,
                title=f"Bing图片: {name}",
                text=f"Bing图片搜索: {name}\n共提取 {len(bing_images)} 张原图",
                text_length=len(f"Bing图片搜索: {name}"),
                images=bing_images[:30], videos=[],
                status=200, method="bing_image_search",
            )

        if method == "bing_video_search":
            keywords = target.relevance_keywords
            bing_videos = self._extract_bing_videos(soup, url, keywords)
            log_func(f"  Bing视频搜索: 提取 {len(bing_videos)} 个", "PARSE")
            return CrawlResult(
                name=name, url=url, success=True,
                title=f"Bing视频: {name}",
                text=f"Bing视频搜索: {name}\n共提取 {len(bing_videos)} 个视频",
                text_length=len(f"Bing视频搜索: {name}"),
                images=[], videos=bing_videos[:10],
                status=200, method="bing_video_search",
            )

        # bing_search — 提取链接 + 深度爬取
        from crawler.content_extractor import extract_text, extract_images, \
            extract_links, good_image_url

        title = soup.title.get_text(strip=True) if soup.title else ""
        text_parts = extract_text(soup)
        full_text = "\n".join(text_parts[:300])

        images = extract_images(soup, url, filter_fn=good_image_url)
        links = extract_links(soup, url)

        # 提取搜索结果链接
        article_urls = self._extract_article_urls(links)
        sub_articles = []

        if article_urls:
            log_func(f"  追踪 {len(article_urls)} 篇真文章...", "CRAWL")
            for i, art_url in enumerate(article_urls[:4], 1):
                try:
                    import asyncio as _a
                    await _a.sleep(0.5)
                    async with session.get(
                        art_url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as resp:
                        if resp.status == 200:
                            art_html = await resp.text()
                            art_soup = BeautifulSoup(art_html, "html.parser")
                            for t in art_soup(["script", "style", "nav",
                                                "footer", "header"]):
                                t.decompose()
                            art_title = art_soup.title.get_text(strip=True) \
                                if art_soup.title else ""
                            art_parts = extract_text(art_soup)
                            art_text = "\n".join(art_parts[:200])
                            art_images = extract_images(
                                art_soup, art_url, filter_fn=good_image_url,
                            )
                            sub_articles.append({
                                "success": True, "url": art_url,
                                "title": art_title,
                                "text": art_text[:30000],
                                "text_length": len(art_text),
                                "images": art_images[:20],
                            })
                            full_text += f"\n\n--- 文章{i}: {art_title} ---\n{art_text[:15000]}"
                            for img in art_images:
                                images.append(img)
                except Exception as e:
                    log_func(f"    第{i}篇失败: {e}", "CRAWL")

        log_func(f"  总文本: {len(full_text):,} 字符", "DONE")

        return CrawlResult(
            name=name, url=url, success=True,
            title=title, text=full_text[:80000],
            text_length=len(full_text),
            paragraph_count=len(text_parts),
            images=images[:30], videos=[], links=links[:50],
            status=200, sub_articles=sub_articles, method="bing_search",
        )

    # ── Bing 专用提取 ──

    @staticmethod
    def _extract_bing_images(soup: BeautifulSoup, base_url: str) -> list:
        """提取 Bing 原图地址（跳过缩略图）。"""
        images = []
        seen = set()

        def _add(src: str, alt: str = "Bing原图"):
            if not src:
                return
            src = unquote(src)
            low = src.lower()
            if any(bad in low for bad in ["bing.net/th/id/", "mm.bing.net/th/",
                                           "tse", "thumbnail", "thumb"]):
                return
            if src.startswith("http") and src not in seen:
                seen.add(src)
                images.append({"src": src, "alt": alt[:100],
                               "source": "bing_original"})

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "murl=" in href:
                try:
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    _add(qs.get("murl", [""])[0],
                         a.get_text(strip=True)[:100])
                except Exception:
                    pass
            m_attr = a.get("m") or ""
            if "murl" in m_attr:
                try:
                    data = json.loads(m_attr.replace("&quot;", '"'))
                    _add(data.get("murl", ""), data.get("t", "Bing原图"))
                except Exception:
                    pass

        html = str(soup)
        for m in re.finditer(r'"murl"\s*:\s*"(https?:\\/\\/.*?)"', html):
            _add(m.group(1).replace('\\/', '/'))

        return images

    @staticmethod
    def _extract_bing_videos(
        soup: BeautifulSoup, base_url: str, keywords: list = None,
    ) -> list:
        videos = []
        seen = set()
        keywords = keywords or []

        def _is_relevant(title: str) -> bool:
            t = title.lower()
            return any(kw.lower() in t for kw in keywords)

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/videos/search" in href and "view=detail" in href:
                full = urljoin(base_url, href)
                title = a.get_text(strip=True)[:100]
                if _is_relevant(title) and full not in seen:
                    seen.add(full)
                    videos.append({"src": full, "title": title,
                                   "type": "bing_detail"})

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href.startswith("http") and any(
                x in href for x in ["youtube", "bilibili", "youku"]
            ):
                title = a.get_text(strip=True)[:100]
                if _is_relevant(title) and href not in seen:
                    seen.add(href)
                    embed_url = BingAdapter._convert_bilibili_embed(href)
                    videos.append({"src": embed_url, "title": title,
                                   "type": "external"})

        return videos

    @staticmethod
    def _extract_article_urls(links: list) -> list:
        priority_domains = [
            "xinhuanet.com", "people.com.cn", "chinadaily.com.cn",
            "news.cn", "gov.cn", "zhihu.com",
            "sohu.com", "sina.com.cn", "163.com", "qq.com",
            "wikimedia.org", "wikipedia.org",
        ]
        exclude_domains = [
            "bing.com", "microsoft.com", "go.microsoft.com",
            "jd.com", "tmall.com", "taobao.com",
        ]

        def _is_excluded(u: str) -> bool:
            return any(d in u for d in exclude_domains)

        def _is_priority(u: str) -> bool:
            return any(d in u for d in priority_domains)

        articles = []
        seen = set()

        # 优先域名排前面
        for link in links:
            lu = link.get("url", "")
            lt = link.get("text", "")
            if _is_excluded(lu) or len(lt) < 3:
                continue
            if lu.startswith("http") and _is_priority(lu) and lu not in seen:
                seen.add(lu)
                articles.append(lu)

        for link in links:
            lu = link.get("url", "")
            lt = link.get("text", "")
            if _is_excluded(lu) or len(lt) < 3:
                continue
            if lu.startswith("http") and lu not in seen:
                seen.add(lu)
                articles.append(lu)

        return articles[:4]

    @staticmethod
    def _convert_bilibili_embed(url: str) -> str:
        m = re.search(r'bilibili\.com/video/(BV[\w]+)', url)
        if m:
            return f"https://player.bilibili.com/player.html?bvid={m.group(1)}&page=1&high_quality=1"
        return url
