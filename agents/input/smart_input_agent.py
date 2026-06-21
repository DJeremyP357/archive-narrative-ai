import json
import os
from typing import Any, Dict, List, Optional

from core.llm_client import MultiLLMRouter
from core.react_agent import ReActAgent
from core.tool_registry import ToolParameter

from agents.input.document_parser_agent import DocumentParserAgent
from agents.input.web_crawler_agent import WebCrawlerAgent


class SmartInputAgent(ReActAgent):
    def __init__(self, llm_router: MultiLLMRouter):
        super().__init__(
            name="SmartInputAgent",
            description="智能输入Agent，自主决策：解析文件或网络爬取",
            llm_router=llm_router,
            tool_categories=["input"],
            max_iterations=10,
        )
        self._parser = DocumentParserAgent()
        self._crawler = WebCrawlerAgent()
        self._register_tools()

    def _register_tools(self):
        registry = self.tool_registry

        registry.register(
            name="parse_document",
            description="解析用户提供的档案文件（支持txt/md/csv/json/docx/pdf/图片/音频/视频）",
            parameters=[
                ToolParameter(name="file_paths", type="string", description="文件路径列表，JSON数组格式"),
            ],
            handler=self._tool_parse_document,
            category="input",
        )

        registry.register(
            name="crawl_web",
            description="从互联网爬取相关档案数据（文本、图片、视频）",
            parameters=[
                ToolParameter(name="keywords", type="string", description="搜索关键词"),
                ToolParameter(name="max_images", type="integer", description="最大图片数", required=False),
                ToolParameter(name="max_videos", type="integer", description="最大视频数", required=False),
            ],
            handler=self._tool_crawl_web,
            category="input",
        )

        registry.register(
            name="crawl_bilibili",
            description="从B站搜索和爬取视频资源",
            parameters=[
                ToolParameter(name="keyword", type="string", description="B站搜索关键词"),
                ToolParameter(name="max_results", type="integer", description="最大结果数", required=False),
            ],
            handler=self._tool_crawl_bilibili,
            category="input",
        )

        registry.register(
            name="read_local_files",
            description="读取本地目录中的所有文件",
            parameters=[
                ToolParameter(name="directory", type="string", description="目录路径"),
            ],
            handler=self._tool_read_local_files,
            category="input",
        )

    async def _tool_parse_document(self, file_paths: str) -> str:
        try:
            paths = json.loads(file_paths) if isinstance(file_paths, str) else file_paths
        except json.JSONDecodeError:
            paths = [file_paths]
        if isinstance(paths, str):
            paths = [paths]
        file_infos = [{"path": p, "type": "auto"} if isinstance(p, str) else p for p in paths]

        result = await self._parser.execute({"files": file_infos})
        return json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    async def _tool_crawl_web(self, keywords: str, max_images: int = 10, max_videos: int = 5) -> str:
        from urllib.parse import quote
        from utils.crawl_helpers import engineer_queries, build_crawl_targets_from_queries

        # 使用查询工程引擎生成多源搜索目标
        kw_list = keywords.split()
        queries = engineer_queries(
            archive_name=keywords,
            keywords=kw_list,
        )
        targets = build_crawl_targets_from_queries(queries, kw_list)

        crawled = await self._crawler.crawl_targets(targets)
        return json.dumps({
            "crawl_results": crawled,
            "count": len(crawled),
            "engines": list(set(t.get("method", "direct") for t in targets)),
            "queries_generated": len(queries),
        }, ensure_ascii=False, default=str)

    async def _tool_crawl_bilibili(self, keyword: str, max_results: int = 5) -> str:
        from urllib.parse import quote

        q = quote(keyword)
        targets = [
            {
                "name": f"B站-{keyword[:20]}",
                "url": f"https://search.bilibili.com/all?keyword={q}",
                "method": "bilibili_search",
                "relevance_keywords": keyword.split(),
            },
        ]
        crawled = await self._crawler.crawl_targets(targets)
        if crawled and crawled[0].get("videos"):
            crawled[0]["videos"] = crawled[0]["videos"][:max_results]
        return json.dumps({"crawl_results": crawled}, ensure_ascii=False, default=str)

    async def _tool_read_local_files(self, directory: str) -> str:
        if not os.path.isdir(directory):
            return json.dumps({"error": f"目录不存在: {directory}"}, ensure_ascii=False)

        files = []
        for root, dirs, filenames in os.walk(directory):
            for fname in filenames:
                fpath = os.path.join(root, fname)
                ext = os.path.splitext(fname)[1].lower()
                files.append({"path": fpath, "name": fname, "ext": ext})

        return json.dumps({"directory": directory, "files": files, "count": len(files)}, ensure_ascii=False)

    async def answer_query(self, question: str) -> str:
        return f"SmartInputAgent: 我可以帮你解析文件或爬取网络数据。请告诉我你需要什么。"
