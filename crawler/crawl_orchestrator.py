"""
爬虫编排器 — 替代 WebCrawlerAgent.crawl_targets()

根据 target.method 将每个爬取目标分派到对应的适配器。
SERP 类目标串行执行（防反爬），直接页面类并行执行。
"""

import asyncio
import random
from typing import Any, Callable, Dict, List, Optional

from crawler.base_adapter import BaseCrawlerAdapter, CrawlTarget, CrawlResult
from crawler.session_manager import SessionManager


class CrawlOrchestrator:
    """多适配器爬虫编排器。

    替代 WebCrawlerAgent.crawl_targets()，按优先级将目标分派到适配器。
    """

    def __init__(self, session_mgr: Optional[SessionManager] = None):
        self.session_mgr = session_mgr or SessionManager()
        self.adapters: List[BaseCrawlerAdapter] = []
        self._register_default_adapters()

    def _register_default_adapters(self):
        """注册默认适配器（优先级从高到低）。"""
        from crawler.adapters.baidu_image_adapter import BaiduImageAdapter
        from crawler.adapters.bilibili_adapter import BilibiliAdapter
        from crawler.adapters.bing_adapter import BingAdapter
        from crawler.adapters.baidu_search_adapter import BaiduSearchAdapter
        from crawler.adapters.direct_adapter import DirectAdapter

        self.adapters = [
            BaiduImageAdapter(self.session_mgr),
            BilibiliAdapter(self.session_mgr),
            BingAdapter(self.session_mgr),
            BaiduSearchAdapter(self.session_mgr),
            DirectAdapter(self.session_mgr),  # 兜底 — 总能 can_handle
        ]

    def register_adapter(self, adapter: BaseCrawlerAdapter):
        """注入自定义适配器（插入到优先级最高位置）。"""
        self.adapters.insert(0, adapter)

    # ── 主入口 ──

    async def crawl_targets(
        self,
        targets: List[Dict],
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[Dict]:
        """对每个 target 分派适配器并返回标准化结果列表。

        Args:
            targets: 爬取目标列表（与旧版 WebCrawlerAgent.crawl_targets 兼容）
            log_callback: 可选日志回调 (msg, level)

        Returns:
            与旧版兼容的 dict 列表（每个 dict 含 success/name/url/text/images 等）
        """

        def _log(msg: str, level: str = "INFO"):
            if log_callback:
                log_callback(msg, level)

        _log("=" * 62, "CRAWL")
        _log("  Multi-Adapter Crawl Orchestrator", "CRAWL")
        _log(f"  目标数量: {len(targets)} 个URL | 适配器: {len(self.adapters)} 个", "CRAWL")
        _log("=" * 62, "CRAWL")

        # 分组：按搜索类型分组并行，组内串行防反爬
        serp_groups: Dict[str, List[CrawlTarget]] = {}
        direct_targets = []
        for t in targets:
            method = t.get("method", "direct")
            if method in ("baidu_search", "bing_search", "search",
                          "baidu_image_search", "bing_image_search", "bing_video_search",
                          "bilibili_search"):
                # 按搜索引擎+类型分组，同组串行，不同组并行
                group_key = method
                serp_groups.setdefault(group_key, []).append(CrawlTarget.from_dict(t))
            else:
                direct_targets.append(CrawlTarget.from_dict(t))

        results: List[Dict] = []

        async def _crawl_serp_group(group_key: str, targets_in_group: List[CrawlTarget]):
            """同类型 SERP 串行爬取（防反爬），返回结果列表"""
            group_results = []
            for i, target in enumerate(targets_in_group):
                if i > 0:
                    delay = random.uniform(1.5, 3.0)
                    _log(f"  [{group_key}] 延迟 {delay:.1f}s（避免反爬）...", "CRAWL")
                    await asyncio.sleep(delay)
                r = await self._crawl_one(target, _log)
                group_results.append(r)
            return group_results

        # ── SERP 类：按类型分组并行，组内串行 ──
        if serp_groups:
            group_keys = list(serp_groups.keys())
            _log(f"  SERP 分 {len(group_keys)} 组并行: {', '.join(group_keys)}", "CRAWL")
            group_tasks = [_crawl_serp_group(k, serp_groups[k]) for k in group_keys]
            group_results_list = await asyncio.gather(*group_tasks, return_exceptions=True)
            for gr in group_results_list:
                if isinstance(gr, list):
                    for r in gr:
                        results.append(r.to_dict() if isinstance(r, CrawlResult) else r)
                elif isinstance(gr, Exception):
                    results.append({"name": "unknown", "url": "", "success": False, "error": str(gr)[:200]})

        # ── Direct 类：并行 ──
        if direct_targets:
            tasks = [self._crawl_one(t, _log) for t in direct_targets]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            for r in gathered:
                if isinstance(r, CrawlResult):
                    results.append(r.to_dict())
                elif isinstance(r, Exception):
                    results.append({
                        "name": "unknown", "url": "", "success": False,
                        "error": str(r)[:200],
                    })

        # 统计
        ok = sum(1 for r in results if r.get("success"))
        total_text = sum(r.get("text_length", 0) for r in results)
        total_images = sum(len(r.get("images", [])) for r in results)
        total_videos = sum(len(r.get("videos", [])) for r in results)
        total_links = sum(len(r.get("links", [])) for r in results)

        _log("", "INFO")
        _log(f"  爬取完成: {ok}/{len(results)} 成功", "DONE")
        _log(f"  总文本: {total_text:,} 字符", "DONE")
        _log(f"  总图片: {total_images} 张", "DONE")
        _log(f"  总视频: {total_videos} 个", "DONE")
        _log(f"  总链接: {total_links} 个", "DONE")
        _log("", "INFO")

        return results

    async def _crawl_one(
        self, target: CrawlTarget,
        log_func: Callable[[str, str], None],
    ) -> CrawlResult:
        """为单个目标找到合适的适配器并执行爬取。"""
        log_func(
            f"发起请求 [{target.method.upper()}]: {target.name}", "CRAWL")
        log_func(f"  URL: {target.url[:130]}", "CRAWL")

        for adapter in self.adapters:
            try:
                if await adapter.can_handle(target):
                    return await adapter.crawl(target, log_func)
            except Exception as e:
                log_func(f"  适配器 {adapter.__class__.__name__} 异常: {e}", "CRAWL")
                continue

        return CrawlResult(
            name=target.name, url=target.url,
            success=False, error="No adapter found",
        )

    async def close(self):
        await self.session_mgr.close()
        for adapter in self.adapters:
            try:
                await adapter.close()
            except Exception:
                pass
