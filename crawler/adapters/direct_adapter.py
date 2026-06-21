"""
直接页面适配器 — 处理百科、普通网页、文章页面

组合了旧版 _crawl_page_fallback、_crawl_article、_crawl_article_with_playwright 的逻辑。
优先 aiohttp 请求，JS 重页面自动回退 Playwright。
"""

import asyncio
import random
from typing import Callable, Dict, List
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.content_extractor import (
    clean_soup, extract_text, extract_images, extract_images_with_context,
    extract_links, good_image_url,
)
from crawler.session_manager import SessionManager


class DirectAdapter(BaseCrawlerAdapter):
    """兜底适配器 — 直接 URL 抓取，覆盖百科、文章页、普通网页。

    can_handle() 始终返回 True（作为 fallback），但如果有更具体的适配器，
    它们会先匹配。这里处理：
    - baike.baidu.com/item/* (百科词条直接用 Playwright 渲染)
    - 直接 HTTP 请求 → 正文提取 → 必要时 Playwright 回退
    """

    NAME = "Direct"

    async def can_handle(self, target: CrawlTarget) -> bool:
        return target.method in ("direct", "requests", "playwright", "selenium")

    async def crawl(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name
        keywords = target.relevance_keywords

        # ── 百科 / 微信公众号文章 → Playwright 渲染 ──
        is_article = (
            "baike.baidu.com/item/" in url
            or "mp.weixin.qq.com/s/" in url
            or "mp.weixin.qq.com/s?" in url
        )
        if is_article:
            return await self._crawl_with_playwright(target, log_func)

        # ── 常规 aiohttp 请求 ──
        session = await self.session_mgr.get_session()
        headers = self.session_mgr.get_headers(
            extra=target.extra_headers,
        )

        # 百度/搜狗跳转需要 Referer
        if "baidu.com" in url:
            headers["Referer"] = "https://www.baidu.com/"
        elif "weixin.sogou.com" in url:
            headers["Referer"] = "https://weixin.sogou.com/"

        max_retries = 3
        html = ""
        status = 0
        last_error = ""

        for attempt in range(max_retries):
            try:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=25)) as resp:
                    status = resp.status
                    html = await resp.text()
                    log_func(f"  HTTP {status} | {len(html):,} 字节", "CRAWL")
                    break
            except asyncio.TimeoutError:
                last_error = "timeout"
                if attempt < max_retries - 1:
                    log_func(f"  超时，重试 {attempt + 1}/{max_retries - 1}", "CRAWL")
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = str(e)[:200]
                if attempt < max_retries - 1:
                    log_func(f"  失败，重试 {attempt + 1}/{max_retries - 1}", "CRAWL")
                    await asyncio.sleep(2 ** attempt)

        if status == 0:
            return CrawlResult(name=name, url=url, success=False, error=last_error)

        if status != 200:
            return CrawlResult(name=name, url=url, success=False,
                               error=f"HTTP {status}", status=status)

        # ── 正文提取 ──
        log_func("  解析...", "PARSE")
        soup = clean_soup(html)
        title = soup.title.get_text(strip=True) if soup.title else ""
        log_func(f"  标题: {title[:80]}", "PARSE")

        page_type = "baike" if "baike.baidu.com" in url else "article"
        text_parts = extract_text(soup, page_type=page_type)
        full_text = "\n".join(text_parts[:300])
        log_func(f"  文本: {len(full_text):,} 字符 / {len(text_parts)} 段", "PARSE")

        images = extract_images_with_context(
            soup, url, article_text=full_text, filter_fn=good_image_url)
        log_func(f"  图片: {len(images)} 张 (含上下文)", "PARSE")

        links = extract_links(soup, url)
        log_func(f"  链接: {len(links)} 个", "PARSE")

        # ── Playwright 回退（aiohttp 拿到空壳时） ──
        likely_js_shell = len(full_text) < 500 and len(html) > 3000
        if likely_js_shell or title in ("搜狗搜索", "百度安全验证", ""):
            log_func(f"  aiohttp 仅 {len(full_text)} 字，尝试 Playwright 回退...", "PARSE")
            try:
                pw_result = await self._crawl_with_playwright(target, log_func)
                if pw_result.success and pw_result.text_length > len(full_text):
                    return pw_result
            except Exception as e:
                log_func(f"  Playwright 回退失败: {e}", "PARSE")

        return CrawlResult(
            name=name, url=url, success=True,
            title=title, text=full_text[:80000],
            text_length=len(full_text),
            paragraph_count=len(text_parts),
            images=images[:30], videos=[], links=links[:50],
            status=status, method="direct",
        )

    # ── Playwright 渲染 ──

    async def _crawl_with_playwright(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name
        query = target.semantic_query

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox", "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                )
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                page = await ctx.new_page()
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    window.chrome = {runtime: {}};
                """)
                log_func("  Playwright 渲染中...", "CRAWL")

                await page.goto(url, wait_until="networkidle", timeout=25000)
                await asyncio.sleep(random.uniform(0.5, 1.5))

                title = await page.title()
                html = await page.content()
                await browser.close()

            soup = clean_soup(html)
            page_type = "baike" if "baike.baidu.com" in url else "article"
            text_parts = extract_text(soup, page_type=page_type)
            full_text = "\n".join(text_parts[:300])

            log_func(f"  标题: {title[:80]} | 文本: {len(full_text):,} 字符", "DONE")

            images = extract_images_with_context(
                soup, url, article_text=full_text, filter_fn=good_image_url)
            log_func(f"  图片: {len(images)} 张 (含上下文)", "DONE")

            return CrawlResult(
                name=name, url=url,
                success=len(full_text) > 50,
                title=title or query,
                text=full_text[:80000],
                text_length=len(full_text),
                paragraph_count=len(text_parts),
                images=images[:30], videos=[], links=[],
                status=200, method="playwright",
            )
        except ImportError:
            log_func("  Playwright 未安装", "CRAWL")
            return CrawlResult(name=name, url=url, success=False,
                               error="Playwright not installed")
        except Exception as e:
            return CrawlResult(name=name, url=url, success=False,
                               error=str(e)[:200])
