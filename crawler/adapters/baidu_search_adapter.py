"""
百度搜索适配器 — Playwright 渲染 SERP → 提取结果链接 → 深度爬取文章

处理 method: "baidu_search" / "search"
"""

import asyncio
import random
from typing import Callable, List
from urllib.parse import urljoin

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.content_extractor import extract_images, good_image_url
from crawler.session_manager import SessionManager


class BaiduSearchAdapter(BaseCrawlerAdapter):
    """百度搜索引擎适配器"""

    NAME = "BaiduSearch"

    async def can_handle(self, target: CrawlTarget) -> bool:
        return target.method in ("baidu_search", "search") and "baidu.com/s?" in target.url

    async def crawl(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        url = target.url
        name = target.name
        query = target.semantic_query
        keywords = target.relevance_keywords

        article_urls: List[str] = []
        snippet_texts: List[str] = []
        serp_title = ""

        # ── Playwright 渲染百度 SERP ──
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
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                page = await context.new_page()

                # 反检测脚本
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = {runtime: {}};
                """)

                log_func("  Playwright 渲染百度 SERP...", "CRAWL")
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(1.5, 3.0))

                serp_title = await page.title()
                html = await page.content()

                # 提取搜索结果链接
                links_data = await page.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll(
                        '.result h3 a, .c-container h3 a, #content_left h3 a'
                    ).forEach(function(a) {
                        const title = (a.innerText || '').trim();
                        if (title && title.length > 3) {
                            let realUrl = '';
                            const container = a.closest('.result, .c-container');
                            if (container) {
                                const showUrl = container.querySelector(
                                    '.c-showurl, .c-color-gray, .c-abstract .c-showurl'
                                );
                                if (showUrl) realUrl = (showUrl.innerText || '').trim();
                            }
                            results.push({url: a.href, title: title, showUrl: realUrl});
                        }
                    });
                    if (!results.length) {
                        document.querySelectorAll('.c-result h3 a').forEach(function(a) {
                            const title = (a.innerText || '').trim();
                            if (title && title.length > 3)
                                results.push({url: a.href, title: title, showUrl: ''});
                        });
                    }
                    return results;
                }""")

                for item in links_data[:10]:
                    u = item.get("url", "")
                    title = item.get("title", "")
                    if not u or not u.startswith("http"):
                        continue
                    if self._is_noisy_result(u, title, keywords):
                        continue
                    article_urls.append(u)
                    snippet_texts.append(title)

                log_func(f"  百度提取 {len(article_urls)} 篇候选文章", "PARSE")
                await browser.close()

        except ImportError:
            log_func("  Playwright 未安装，回退常规请求", "CRAWL")
            return CrawlResult(name=name, url=url, success=False,
                               error="Playwright not installed")
        except Exception as e:
            log_func(f"  Playwright 失败: {e}", "CRAWL")
            return CrawlResult(name=name, url=url, success=False,
                               error=str(e)[:200])

        # ── 深度爬取文章 ── (使用 DirectAdapter 的 Playwright 渲染)
        from crawler.adapters.direct_adapter import DirectAdapter
        direct = DirectAdapter(self.session_mgr)
        all_text = f"搜索: {query or name}\n标题: {serp_title}\n"
        all_images: List[dict] = []
        all_links: List[dict] = []
        seen_img = set()
        sub_articles: List[dict] = []

        if article_urls:
            max_articles = 8 if "tn=news" in url else 5  # 资讯搜索爬取更多文章
            article_slice = article_urls[:max_articles]
            log_func(f"  深度爬取 {len(article_slice)} 篇真实文章（并发3）...", "CRAWL")

            sem = asyncio.Semaphore(3)

            async def _fetch_article(idx: int, art_url: str):
                async with sem:
                    try:
                        art_target = CrawlTarget(
                            name=f"{name}-第{idx}篇", url=art_url,
                            method="direct",
                            relevance_keywords=keywords,
                        )
                        art = await direct.crawl(art_target, log_func)
                        return (idx, art)
                    except Exception as e:
                        log_func(f"    第{idx}篇失败: {e}", "CRAWL")
                        return (idx, None)

            fetch_tasks = [_fetch_article(i + 1, u) for i, u in enumerate(article_slice)]
            fetch_results = await asyncio.gather(*fetch_tasks)

            for idx, art in sorted(fetch_results, key=lambda x: x[0]):
                if art is None:
                    continue
                if art.success and art.text_length > 50:
                    art_dict = art.to_dict()
                    sub_articles.append(art_dict)
                    all_text += f"\n\n--- 文章{idx}: {art.title} ---\n{art.text[:15000]}"
                    for img in art.images:
                        s = img.get("src", "")
                        if s and s not in seen_img:
                            seen_img.add(s)
                            all_images.append(img)
                    all_links.append({
                        "url": article_slice[idx - 1], "text": art.title,
                        "source": "serp_deep",
                    })
                else:
                    log_func(f"    第{idx}篇: text={art.text_length}chars err={art.error}", "CRAWL")

        if not sub_articles and snippet_texts:
            all_text += "\n\n搜索摘要:\n" + "\n".join(snippet_texts[:10])
            all_text += "\n\n注意：搜索引擎防爬限制，仅获取到摘要。"
            log_func("  ⚠ 仅获取搜索摘要，未爬取到完整文章", "CRAWL")

        log_func(f"  总文本: {len(all_text):,} 字符 | 文章: {len(sub_articles)} 篇", "DONE")

        return CrawlResult(
            name=name, url=url,
            success=len(sub_articles) > 0 or len(snippet_texts) > 0,
            title=serp_title or query,
            text=all_text[:80000],
            text_length=len(all_text),
            paragraph_count=len(sub_articles),
            images=all_images[:30], videos=[], links=all_links[:50],
            status=200, sub_articles=sub_articles, method="playwright",
        )

    @staticmethod
    def _is_noisy_result(url: str, title: str = "", keywords: list = None) -> bool:
        low = f"{url} {title}".lower()
        noisy_domains = [
            "image.baidu.com", "news.baidu.com", "tieba.baidu.com", "zhidao.baidu.com",
            "haokan.baidu.com", "video.baidu.com", "baijiahao.baidu.com/s?",
            "car.autohome.com.cn", "price.pcauto.com.cn", "dealer.autohome.com.cn",
        ]
        noisy_words = ["视频搜索", "图片搜索", "热搜榜", "报价", "价格及图片", "参数配置", "经销商"]
        if any(d in low for d in noisy_domains):
            return True
        if any(w in title for w in noisy_words):
            return True
        keywords = [k for k in (keywords or []) if isinstance(k, str) and len(k) > 1]
        if keywords and not any(k.lower() in low for k in keywords[:6]):
            return True
        return False

    # _crawl_article 和 _crawl_article_pw 已废弃 — 深度爬取现在委托到 DirectAdapter.crawl()
    # DirectAdapter 自动处理 aiohttp → Playwright 回退，且能处理百度跳转链接的 Cookie 重定向
