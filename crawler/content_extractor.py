"""
统一内容提取器

消除 web_crawler_agent.py 中 4 套重复的文本/图片/链接/视频提取逻辑，
提供唯一的实现，所有适配器共用。
"""

from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.vision_service import JUNK_IMAGE_DOMAINS, JUNK_IMAGE_URL_PATTERNS

# ── 页面类型 → CSS 选择器优先级 ──

PAGE_SELECTORS = {
    "article": [
        "article", "main",
        ".article", ".content", ".post", ".entry", ".detail", ".text",
        "#content", "#article", "#main",
        ".article-content", ".post-content", ".entry-content",
        ".news-content", ".text-content", ".detail-content",
        ".rich_media_content", ".con", ".main-content", "[class*=content]",
    ],
    "baike": [
        ".J-lemma-content", ".lemmaSummary_bIGx9",
        ".paraTitle_y81E9", ".para_XuDGQ", ".paragraph_QzE7P",
        ".mainContent_bmlot", ".J-summary",
        "article", "main", ".content", "#content",
    ],
    "serp": [
        "article", "main", ".content", ".article", ".entry", ".post",
        "#content", ".main-content",
    ],
}

# 通用 HTML 标签 fallback 选择器
TAG_SELECTORS = ["p", "h2", "h3", "h4", "li", "span", "div"]

# 需要剥离的噪音标签
SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe"}


# ── 公开工具函数 ──

def clean_soup(html: str) -> BeautifulSoup:
    """解析 HTML 并移除噪音标签。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(SKIP_TAGS):
        tag.decompose()
    return soup


def extract_text(
    soup: BeautifulSoup, page_type: str = "article", min_len: int = 12,
) -> List[str]:
    """统一文本提取。

    Args:
        soup: 已清理的 BeautifulSoup 对象
        page_type: "article" | "baike" | "serp"，决定选择器优先级
        min_len: 段落最短字符数

    Returns:
        文本段落列表
    """
    selectors = PAGE_SELECTORS.get(page_type, PAGE_SELECTORS["article"])
    parts: List[str] = []

    # 第一层：CSS 选择器
    for sel in selectors:
        for el in soup.select(sel):
            txt = el.get_text(separator=" ", strip=True)
            if len(txt) > min_len:
                parts.append(txt)
        if len(parts) >= 5:
            break

    # 第二层：标签级 fallback
    if len(parts) < 5:
        for tag_name in TAG_SELECTORS:
            for el in soup.find_all(tag_name):
                txt = el.get_text(separator=" ", strip=True)
                if len(txt) > min_len:
                    parts.append(txt)
            if len(parts) >= 5:
                break

    # 最终兜底：body 全文
    if not parts:
        txt = soup.get_text(separator=" ", strip=True)
        if len(txt) > 50:
            parts = [txt]

    return parts


def extract_images(
    soup: BeautifulSoup, base_url: str,
    filter_fn: Optional[Callable[[str, str], bool]] = None,
) -> List[Dict]:
    """统一图片提取。

    Args:
        soup: 已清理的 BeautifulSoup 对象
        base_url: 用于解析相对路径
        filter_fn: 可选过滤函数 (src, alt) -> bool

    Returns:
        [{"src": str, "alt": str}, ...]
    """
    images: List[Dict] = []
    seen: set = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt", "")
        if not src or src.startswith("data:"):
            continue
        full = urljoin(base_url, src)
        if full in seen:
            continue
        if filter_fn and not filter_fn(full, alt):
            continue
        seen.add(full)
        images.append({
            "src": full,
            "alt": alt[:100],
            "title": img.get("title", ""),
        })
    return images


def extract_images_with_context(
    soup: BeautifulSoup, base_url: str,
    article_text: str = "",
    filter_fn: Optional[Callable[[str, str], bool]] = None,
    max_context_chars: int = 200,
) -> List[Dict]:
    """带上下文的图片提取 — 为每张图片捕获周围文字。

    与 extract_images 不同，此函数尝试为每张图片找到其上下文中
    的文字（前一段、后一段、图片 alt 属性），打包为 context 字段。
    这个 context 会在 VL 验证时传给模型，使其能基于图文关系做出
    更准确的判断和标注。

    Args:
        soup: 已清理的 BeautifulSoup 对象
        base_url: 用于解析相对路径
        article_text: 整篇文章的文本（用于 fallback 匹配）
        filter_fn: 可选过滤函数
        max_context_chars: 上下文最大字符数

    Returns:
        图片列表，每个含 src/alt/context 字段
    """
    images: List[Dict] = []
    seen: set = set()
    paragraphs = [p.get_text(separator=" ", strip=True)
                  for p in soup.find_all(["p", "h2", "h3", "h4", "li", "figcaption"])
                  if len(p.get_text(strip=True)) > 10]

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = img.get("alt", "")
        title = img.get("title", "")

        if not src or src.startswith("data:"):
            continue
        full = urljoin(base_url, src)
        if full in seen:
            continue
        if filter_fn and not filter_fn(full, alt):
            continue
        seen.add(full)

        # ── 构建上下文 ──
        context_parts = []
        # 1. alt/title 文本
        if alt and len(alt.strip()) > 2:
            context_parts.append(f"[图片说明] {alt[:max_context_chars]}")
        if title and title != alt:
            context_parts.append(f"[标题] {title[:max_context_chars]}")

        # 2. 父元素中的文字（figure/div 等容器）
        parent = img.parent
        for _ in range(3):  # 向上查 3 层
            if parent is None:
                break
            parent_text = parent.get_text(separator=" ", strip=True)
            if len(parent_text) > 20:
                # 去掉 alt 重复部分
                if alt:
                    parent_text = parent_text.replace(alt, "", 1).strip()
                if len(parent_text) > 10:
                    context_parts.append(f"[附近文字] {parent_text[:max_context_chars]}")
                break
            parent = parent.parent

        # 3. 在段落列表中定位最近的段落
        if paragraphs:
            img_pos = str(soup).find(src) if src else -1
            if img_pos < 0:
                img_pos = str(soup).find(alt[:30]) if alt else -1
            if img_pos >= 0:
                closest_para = ""
                closest_dist = float("inf")
                for p in paragraphs:
                    p_pos = str(soup).find(p[:40])
                    if p_pos >= 0:
                        dist = abs(p_pos - img_pos)
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_para = p
                if closest_para and len(closest_para) > 10:
                    context_parts.append(f"[上下文] {closest_para[:max_context_chars]}")

        # 4. fallback: 从文章文本中搜索 alt 关键词匹配
        if not context_parts and alt and article_text:
            alt_words = alt[:50]
            idx = article_text.find(alt_words)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(article_text), idx + len(alt_words) + 140)
                ctx = article_text[start:end].replace(alt_words, f"「{alt_words}」")
                context_parts.append(f"[文章上下文] {ctx[:max_context_chars]}")

        context = " | ".join(context_parts) if context_parts else alt or ""

        images.append({
            "src": full,
            "alt": alt[:100],
            "title": title[:100],
            "context": context[:max_context_chars + 100],
        })

    return images


def extract_links(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """统一链接提取。"""
    links: List[Dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(strip=True)
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        full = urljoin(base_url, href)
        if len(txt) > 2:
            links.append({"url": full, "text": txt[:100]})
    return links


def extract_videos(
    soup: BeautifulSoup, base_url: str,
    keywords: Optional[List[str]] = None,
) -> List[Dict]:
    """统一视频提取（<video> + <iframe> + <embed>）。"""
    videos: List[Dict] = []
    keywords = keywords or []

    for vid in soup.find_all("video"):
        src = vid.get("src") or vid.get("data-src") or ""
        if src:
            videos.append({
                "src": urljoin(base_url, src),
                "title": vid.get("title", ""),
                "type": "html5",
            })
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or ""
        if src and any(k in src.lower() for k in
                       ["youtube", "bilibili", "youku", "v.qq.com"]):
            title = iframe.get("title", "")
            if keywords and title:
                if not any(kw.lower() in title.lower() for kw in keywords):
                    continue
            videos.append({
                "src": urljoin(base_url, src),
                "title": title,
                "type": "iframe",
            })

    return videos


def good_image_url(src: str, alt: str = "") -> bool:
    """统一的图片 URL 质量过滤（委托到 vision_service）。"""
    from core.vision_service import is_good_image_url
    return is_good_image_url(src, alt)
