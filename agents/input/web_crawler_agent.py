"""
WebCrawlerAgent — 多平台新闻爬虫（委托到 CrawlOrchestrator）

保留 BaseAgent 接口兼容性，所有实际爬取工作委托到 crawler 包的适配器。
"""

from typing import Any, Callable, Dict, List, Optional

import aiohttp

from core.base_agent import BaseAgent, TaskResult
from crawler.crawl_orchestrator import CrawlOrchestrator


class WebCrawlerAgent(BaseAgent):
    """多平台爬虫 Agent — 委托到 CrawlOrchestrator 适配器系统。

    支持的爬取方式：
    - direct: 直接 URL 抓取（aiohttp → Playwright 回退）
    - baidu_search: 百度搜索引擎（Playwright 渲染 SERP → 深度爬取）
    - baidu_image_search: 百度图片搜索（objURL 原图提取）
    - bing_search / bing_image_search / bing_video_search: Bing 搜索
    - bilibili_search: B站视频搜索
    """

    def __init__(self):
        super().__init__(
            name="WebCrawlerAgent",
            description="多平台新闻爬虫，使用 Playwright、aiohttp 等采集档案相关数据",
        )
        self._orch = CrawlOrchestrator()
        self.session: Optional[aiohttp.ClientSession] = None

    async def execute(self, task_input: Dict[str, Any]) -> TaskResult:
        """BaseAgent 兼容入口 — 委托到 crawl_targets()。"""
        crawl_tasks = []
        if isinstance(task_input, list):
            crawl_tasks = task_input
        elif isinstance(task_input, dict):
            crawl_tasks = (task_input.get("crawl_tasks")
                           or task_input.get("targets") or [])
            if not crawl_tasks:
                url = task_input.get("url")
                if url:
                    crawl_tasks = [{
                        "url": url,
                        "method": task_input.get("method", "requests"),
                        "keywords": task_input.get("keywords", []),
                        "depth": task_input.get("depth", 1),
                        "name": task_input.get("name", url),
                    }]

        results = await self._orch.crawl_targets(crawl_tasks)

        return TaskResult(
            success=True,
            data={
                "crawl_results": results,
                "total_tasks": len(crawl_tasks),
                "success_count": sum(1 for r in results if r.get("success")),
            },
            metadata={"agent": self.name},
        )

    async def crawl_targets(
        self,
        targets: List[Dict],
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[Dict]:
        """主入口 — 多源并发爬取（与旧版签名完全兼容）。

        Args:
            targets: 爬取目标列表，每个 dict 含 name/url/method/relevance_keywords
            log_callback: 可选日志回调 (msg, level)

        Returns:
            标准化结果列表
        """
        return await self._orch.crawl_targets(targets, log_callback)

    def get_status(self) -> Dict:
        base = super().get_status()
        base["orchestrator"] = "CrawlOrchestrator (multi-adapter)"
        base["adapter_count"] = len(self._orch.adapters)
        return base

    async def close(self):
        await self._orch.close()
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
