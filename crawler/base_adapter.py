"""
爬虫适配器基类 & 标准化数据结构
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from crawler.session_manager import SessionManager


@dataclass
class CrawlTarget:
    """标准化爬取目标 — 所有适配器统一消费此结构。"""
    name: str
    url: str
    method: str = "direct"                     # 适配器路由键
    semantic_query: str = ""                   # 搜索查询文本
    relevance_keywords: List[str] = field(default_factory=list)
    extra_headers: Dict[str, str] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)  # 原始 target dict

    @classmethod
    def from_dict(cls, d: Dict) -> "CrawlTarget":
        return cls(
            name=d.get("name", ""),
            url=d.get("url", ""),
            method=d.get("method", "direct"),
            semantic_query=d.get("semantic_query", ""),
            relevance_keywords=d.get("relevance_keywords", []),
            extra_headers=d.get("extra_headers", {}),
            raw=d,
        )


@dataclass
class CrawlResult:
    """标准化爬取结果 — 所有适配器统一产出此结构。"""
    name: str = ""
    url: str = ""
    success: bool = False
    title: str = ""
    text: str = ""
    text_length: int = 0
    paragraph_count: int = 0
    images: List[Dict] = field(default_factory=list)
    videos: List[Dict] = field(default_factory=list)
    links: List[Dict] = field(default_factory=list)
    status: int = 0
    sub_articles: List[Dict] = field(default_factory=list)
    error: str = ""
    method: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "url": self.url,
            "success": self.success,
            "title": self.title,
            "text": self.text,
            "text_length": self.text_length,
            "paragraph_count": self.paragraph_count,
            "images": self.images,
            "videos": self.videos,
            "links": self.links,
            "status": self.status,
            "sub_articles": self.sub_articles,
            "error": self.error,
            "method": self.method,
        }


class BaseCrawlerAdapter(ABC):
    """爬虫适配器抽象基类。

    每个适配器负责一种平台/搜索方式，实现 can_handle() 和 crawl()。
    """

    def __init__(self, session_mgr: SessionManager):
        self.session_mgr = session_mgr

    @abstractmethod
    async def can_handle(self, target: CrawlTarget) -> bool:
        """判断此适配器是否应处理该目标。"""

    @abstractmethod
    async def crawl(
        self, target: CrawlTarget,
        log_func: Optional[Callable[[str, str], None]] = None,
    ) -> CrawlResult:
        """执行具体爬取并返回标准化结果。"""

    async def close(self):
        """可选的资源清理。"""
        pass
