"""
集中式 HTTP 会话管理

替代分散在 web_crawler_agent.py 6 处的 aiohttp.ClientSession 创建。
支持 Cookie 持久化、代理轮换、统一请求头。
"""

import os
from typing import Dict, Optional

import aiohttp


class SessionManager:
    """统一管理 aiohttp 会话、请求头和 Cookie。

    用法:
        mgr = SessionManager()
        session = await mgr.get_session()
        async with session.get(url, headers=mgr.get_headers()) as resp: ...
        await mgr.close()
    """

    def __init__(
        self,
        connector_limit: int = 5,
        cookie_file: Optional[str] = None,
        proxy_url: Optional[str] = None,
    ):
        self._connector_limit = connector_limit
        self._cookie_file = cookie_file
        self._proxy_url = proxy_url or os.getenv("CRAWL_PROXY_URL")
        self._session: Optional[aiohttp.ClientSession] = None

        self._default_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self._connector_limit, ttl_dns_cache=300,
            )
            cookie_jar = aiohttp.CookieJar()
            if self._cookie_file and os.path.exists(self._cookie_file):
                try:
                    cookie_jar.load(self._cookie_file)
                except Exception:
                    pass

            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=30),
                headers=self._default_headers,
                cookie_jar=cookie_jar,
            )
        return self._session

    def get_headers(self, extra: Dict = None, referer: str = None) -> Dict:
        """获取带可选 Referer 和额外字段的请求头。"""
        headers = dict(self._default_headers)
        if referer:
            headers["Referer"] = referer
        if extra:
            headers.update(extra)
        return headers

    async def close(self):
        if self._session and not self._session.closed:
            if self._cookie_file:
                try:
                    self._session.cookie_jar.save(self._cookie_file)
                except Exception:
                    pass
            await self._session.close()
            self._session = None
