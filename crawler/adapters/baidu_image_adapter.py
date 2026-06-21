"""
百度图片适配器 — Playwright 渲染百度图片搜索页，提取 objURL 原图地址

处理 method: "baidu_image_search"
"""

import asyncio
import random
import re
from typing import Callable
from urllib.parse import unquote

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.session_manager import SessionManager


class BaiduImageAdapter(BaseCrawlerAdapter):
    """百度图片搜索引擎适配器 — Playwright 渲染"""

    NAME = "BaiduImage"

    async def can_handle(self, target: CrawlTarget) -> bool:
        return target.method == "baidu_image_search"

    async def crawl(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name

        # ── Playwright 渲染百度图片搜索页 ──
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                page = await context.new_page()
                log_func("  Playwright 渲染百度图片搜索...", "CRAWL")
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(1.5, 3.0))

                # 滚动几次以加载更多图片
                for _ in range(3):
                    await page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(random.uniform(1.0, 2.0))

                html = await page.content()
                await browser.close()

            images = self._extract_baidu_images(html)
            log_func(f"  百度图片搜索: 提取 {len(images)} 张原图", "PARSE")

            return CrawlResult(
                name=name, url=url, success=True,
                title=f"百度图片: {name}",
                text=f"百度图片搜索: {name}\n共提取 {len(images)} 张原图",
                text_length=len(f"百度图片搜索: {name}"),
                images=images[:30], videos=[],
                status=200, method="baidu_image_search",
            )

        except ImportError:
            log_func("  Playwright 未安装，回退 aiohttp", "CRAWL")
            return await self._crawl_fallback(target, log_func)
        except Exception as e:
            log_func(f"  Playwright 失败: {e}，回退 aiohttp", "CRAWL")
            return await self._crawl_fallback(target, log_func)

    async def _crawl_fallback(
        self, target: CrawlTarget, log_func,
    ) -> CrawlResult:
        """aiohttp 回退（百度图片纯 HTML 几乎无有效数据）。"""
        import aiohttp
        session = await self.session_mgr.get_session()
        headers = self.session_mgr.get_headers()

        retries = 3
        html = ""
        for attempt in range(retries):
            try:
                async with session.get(
                    target.url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as resp:
                    html = await resp.text()
                break
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return CrawlResult(name=target.name, url=target.url,
                                       success=False, error="timeout")

        images = self._extract_baidu_images(html)
        log_func(f"  百度图片(aiohttp): 提取 {len(images)} 张原图", "PARSE")
        return CrawlResult(
            name=target.name, url=target.url,
            success=len(images) > 0,
            title=f"百度图片: {target.name}",
            text=f"百度图片搜索: {target.name}\n共提取 {len(images)} 张原图",
            text_length=len(f"百度图片搜索: {target.name}"),
            images=images[:30], videos=[],
            status=200, method="baidu_image_search",
        )

    @staticmethod
    def _extract_baidu_images(html: str) -> list:
        """从百度图片页提取原图地址及来源页（适配 2025+ 百度新结构）。

        优先级:
        1. data-objurl 属性 — 原图直链
        2. img src (it/u=...) — 缩略图，去掉 &amp; HTML 实体后可用

        同时提取 data-fromurl（图片来源网页URL）用于后续上下文获取。
        """
        from urllib.parse import unquote
        images = []
        seen = set()

        def _add(src: str, alt: str = "", from_url: str = ""):
            if not src or not src.startswith("http"):
                return
            # 还原 HTML 实体
            src = src.replace("&amp;", "&")
            src = unquote(src)
            low = src.lower()
            # 过滤百度 logo / UI 图
            if any(bad in low for bad in ["baidu.com/img/", "bdstatic.com",
                                           "logo", "favicon", "result@2"]):
                return
            if src not in seen:
                seen.add(src)
                img_data = {"src": src, "alt": alt[:100],
                            "source": "baidu_image"}
                # 保留来源页URL，后续可爬取获取上下文
                if from_url:
                    from_url = from_url.replace("&amp;", "&")
                    from_url = unquote(from_url)
                    if from_url.startswith("http"):
                        img_data["source_page_url"] = from_url
                images.append(img_data)

        # 策略 1: data-objurl（原图，优先级高）+ data-fromurl（来源页）
        for m in re.finditer(r'<img[^>]*data-objurl="(https?:[^"]+)"[^>]*>', html):
            obj_url = m.group(1)
            # 尝试提取来源页URL
            from_m = re.search(r'data-fromurl="([^"]*)"', m.group(0))
            from_url = from_m.group(1) if from_m else ""
            alt_m = re.search(r'alt="([^"]*)"', m.group(0))
            alt = alt_m.group(1) if alt_m else ""
            _add(obj_url, alt, from_url)

        # 也尝试从 data-imgurl 和 data-fromurl 分开的情况
        for m in re.finditer(r'data-objurl="(https?:[^"]+)"', html):
            src = m.group(1)
            if src in seen:
                continue
            # 查找同元素上的 data-fromurl
            start = max(0, m.start() - 500)
            end = min(len(html), m.end() + 500)
            chunk = html[start:end]
            from_m = re.search(r'data-fromurl="([^"]*)"', chunk)
            from_url = from_m.group(1) if from_m else ""
            _add(src, "", from_url)

        # 策略 2: <img src> 中的缩略图（次选，数量多）
        for m in re.finditer(r'<img[^>]+src="(https?://img\d?\.baidu\.com/[^"]+)"', html):
            _add(m.group(1))

        return images
