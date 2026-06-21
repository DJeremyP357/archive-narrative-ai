"""
爬虫模块 — Multi-Platform Web Crawler (Adapter Pattern)

借鉴 NewsCrawler 的适配器架构，每个平台/搜索方式对应一个独立适配器。
CrawlOrchestrator 作为主入口，根据目标类型分派到合适的适配器。

用法:
    from crawler import CrawlOrchestrator, SessionManager

    orch = CrawlOrchestrator()
    results = await orch.crawl_targets(targets, log_callback=print)
    await orch.close()
"""

from crawler.crawl_orchestrator import CrawlOrchestrator
from crawler.session_manager import SessionManager
from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.content_extractor import (
    clean_soup, extract_text, extract_images,
    extract_links, extract_videos, good_image_url,
)

__all__ = [
    "CrawlOrchestrator",
    "SessionManager",
    "BaseCrawlerAdapter",
    "CrawlTarget",
    "CrawlResult",
    "clean_soup",
    "extract_text",
    "extract_images",
    "extract_links",
    "extract_videos",
    "good_image_url",
]
