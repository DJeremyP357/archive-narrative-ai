"""查询工程 + 多源并发 + 来源评分 + 元数据聚合

架构：
  用户 query → 查询改写（双语并行+时间锚定+机构锚定）
            → 百度搜索/百科/图片分发
            → 结果聚合 + 置信度排序
            → 返回给下游
"""
import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.llm_client import MultiLLMRouter
from core.vision_service import (
    VisionService, JUNK_IMAGE_URL_PATTERNS, JUNK_IMAGE_DOMAINS, is_good_image_url,
)
from utils.image_downloader import ImageDownloader


# ---------------------------------------------------------------------------
# 查询工程引擎
# ---------------------------------------------------------------------------

# 通用权威档案域名后缀（任何主题都适用）
AUTHORITY_DOMAIN_SUFFIXES = (
    ".gov", ".gov.cn", ".govt.nz", ".gov.uk", ".gov.au",
    ".edu", ".edu.cn", ".edu.au", ".ac.uk", ".ac.nz",
    ".org", ".org.cn", ".org.nz", ".org.uk",
    "wikipedia.org", "wikimedia.org", "britannica.com",
    "archives.gov", "saac.gov.cn",
)

# 兼容旧引用 — 从 vision_service 导出
JUNK_DOMAINS = JUNK_IMAGE_DOMAINS


def _translate_to_english(text: str) -> str:
    """通用中英翻译：规则映射 + 快速转换。无映射词原样返回。"""
    _map = {
        "档案": "archives", "纪念馆": "memorial", "博物馆": "museum",
        "历史": "history", "革命": "revolution", "战争": "war",
        "非遗": "Intangible Cultural Heritage",
        "丝绸之路": "Silk Road", "老照片": "vintage photos",
        "人物": "figures", "传记": "biography",
        "手稿": "manuscript", "信函": "correspondence",
    }
    result = text
    for cn, en in sorted(_map.items(), key=lambda x: -len(x[0])):
        if cn in result:
            result = result.replace(cn, en)
    return result


def engineer_queries(
    archive_name: str,
    keywords: List[str] = None,
    time_anchors: List[str] = None,
    institution_domains: List[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """
    查询工程：将中文需求翻译成搜索引擎能理解的精准查询（通用版）。

    策略：
    1. 双语并行：英文查国际档案，中文查国内档案
    2. 时间锚定：年份能极大缩小搜索空间
    3. 机构锚定：权威域名自带权威性（由调用方传入）
    4. 关键词深挖：每个关键词单独搜索

    Args:
        archive_name: 档案主题名称
        keywords: 相关关键词列表
        time_anchors: 时间锚点列表（如["1938", "1987"]）
        institution_domains: 机构锚定列表，格式 [{"name": "机构名", "domain": "example.com"}, ...]

    Returns:
        [{"query_cn": "...", "query_en": "...", "engine": "bing|baidu"}]
    """
    keywords = keywords or []
    time_anchors = time_anchors or []
    institution_domains = institution_domains or []
    queries: List[Dict[str, str]] = []

    # 0. 过滤泛化关键词 — 原则：每个关键词单独搜索都应返回与主题直接相关的内容
    _generic_terms = {
        "名人档案", "红色档案", "历史档案", "人物档案", "专题档案",
        "档案", "名人", "红色", "历史", "人物", "专题", "事迹",
        "纪念", "展览", "展示", "介绍", "生平", "传记",
        "院士", "科学家", "教授", "专家", "学者", "英雄",
        "故事", "经历", "成就", "贡献", "精神", "事迹",
        "发展", "回顾", "总结", "概述", "简介",
    }
    keywords = [kw for kw in keywords if kw not in _generic_terms and kw != archive_name]
    if not keywords:
        keywords = [archive_name]

    # 1. 专有名词翻译（通用映射）
    en_name = _translate_to_english(archive_name)
    en_keywords = [_translate_to_english(kw) for kw in keywords]

    # 2. 核心精准查询 — 用引号精确匹配 + site限定，杜绝泛化结果
    # 原则：每个查询都必须让搜索引擎返回与该主题强相关的内容
    core_queries = [
        # 百科直链（最高优先级，结构化数据）
        f'"{archive_name}" site:baike.baidu.com',
        f'"{archive_name}" 百度百科',
        # 结构化简介（精确匹配姓名）
        f'"{archive_name}" 简介 资料',
        # 新闻报道（最新、图文并茂）
        f'"{archive_name}" 新闻报道',
        # 专题/深度文章
        f'"{archive_name}" 专题',
    ]
    for cq in core_queries:
        queries.append({
            "query_cn": cq,
            "query_en": f'"{en_name}" biography',
            "engine": "baidu",
            "purpose": f"核心精准-{cq[:30]}",
        })

    # 3. 关键词组合查询 — archive_name + 具体关键词（更聚焦）
    # 只取最具体的前2个关键词，每个生成2种组合
    for kw, en_kw in zip(keywords[:2], en_keywords[:2]):
        combo_queries = [
            f'"{archive_name}" "{kw}"',
            f'"{archive_name}" {kw} 研究',
        ]
        for cq in combo_queries:
            queries.append({
                "query_cn": cq,
                "query_en": f'"{en_name}" "{en_kw}"',
                "engine": "baidu",
                "purpose": f"关键词组合-{kw[:15]}",
            })

    # 4. 时间锚定查询（精确匹配年份）
    for year in time_anchors:
        queries.append({
            "query_cn": f'"{archive_name}" {year}',
            "query_en": f'"{en_name}" {year}',
            "engine": "baidu",
            "purpose": f"时间锚定-{year}",
        })

    # 5. 机构锚定查询
    for inst in institution_domains:
        domain = inst.get("domain", "")
        name = inst.get("name", "")
        if domain:
            queries.append({
                "query_cn": f'site:{domain} "{archive_name}"',
                "query_en": f'site:{domain} "{en_name}"',
                "engine": "baidu",
                "purpose": f"机构锚定-{name or domain}",
            })

    # 6. 图片查询 — 精确匹配 + 限定词，避免无关图片
    img_queries = [
        f'"{archive_name}" 照片 高清',
        f'"{archive_name}" 图片',
        f'"{archive_name}" 工作照',
        f'"{archive_name}" 历史照片',
    ]
    # 关键词组合图片查询（更具体）
    for kw in keywords[:2]:
        img_queries.append(f'"{archive_name}" "{kw}" 照片')
    for iq in img_queries:
        queries.append({
            "query_cn": iq,
            "query_en": f'"{en_name}" photo',
            "engine": "baidu_images",
            "purpose": f"图片搜索-{iq[:25]}",
        })

    return queries


def build_crawl_targets_from_queries(
    queries: List[Dict[str, str]],
    relevance_keywords: List[str] = None,
) -> List[Dict[str, Any]]:
    """
    将查询工程结果转化为 WebCrawlerAgent 可消费的 crawl_targets。

    每条 query 根据其 engine 字段映射到对应的 URL + method。
    新闻/图文类查询使用 baidu_search（深度爬取文章，图片自带上下文）。
    """
    from urllib.parse import quote

    targets: List[Dict[str, Any]] = []
    relevance_keywords = relevance_keywords or []

    for q in queries:
        engine = q.get("engine", "baidu")
        query_cn = q.get("query_cn", "")
        query_en = q.get("query_en", "")
        purpose = q.get("purpose", "")

        if engine == "baidu" and query_cn:
            # 新闻/图文类查询使用百度资讯搜索，获取图文并茂的新闻页面
            if "新闻" in purpose or "专题" in purpose or "纪念" in purpose:
                targets.append({
                    "name": f"百度资讯-{purpose}",
                    "url": f"https://www.baidu.com/s?wd={quote(query_cn)}&rtt=1&bsst=1&cl=2&tn=news",
                    "method": "baidu_search",
                    "semantic_query": query_cn,
                    "relevance_keywords": relevance_keywords,
                })
            else:
                targets.append({
                    "name": f"百度-{purpose}",
                    "url": f"https://www.baidu.com/s?wd={quote(query_cn)}",
                    "method": "baidu_search",
                    "semantic_query": query_cn,
                    "relevance_keywords": relevance_keywords,
                })

            # 自动追加百度百科直链（仅主查询，避免重复）
            if "主查询" in purpose or "百度百科" in purpose:
                baike_url = f"https://baike.baidu.com/item/{quote(query_cn.replace(' 百度百科', ''))}"
                targets.append({
                    "name": f"百度百科-{query_cn}",
                    "url": baike_url,
                    "method": "direct",
                    "semantic_query": query_cn,
                    "relevance_keywords": relevance_keywords,
                })

        if engine == "baidu_images" and query_cn:
            targets.append({
                "name": f"百度图片-{purpose}",
                "url": f"https://image.baidu.com/search/index?tn=baiduimage&word={quote(query_cn)}",
                "method": "baidu_image_search",
                "semantic_query": query_cn,
            })

    return targets


def collect_crawl_text(crawled: List[dict], max_chars: int = 80000) -> str:
    parts = []
    for r in crawled:
        if not r.get("success"):
            continue
        parts.append(f"\n\n=== 来源: {r['name']} ({r.get('url', '')}) ===\n")
        parts.append(f"标题: {r.get('title', '')}\n")
        parts.append(r.get("text", "")[:20000])
        for sub in r.get("sub_articles", []):
            if sub.get("success"):
                parts.append(
                    f"\n--- 追踪: {sub.get('title', '')} ({sub.get('url', '')}) ---\n"
                )
                parts.append(sub.get("text", "")[:15000])
    combined = "".join(parts)
    return combined[:max_chars]


AUTHORITY_DOMAINS = AUTHORITY_DOMAIN_SUFFIXES  # 兼容旧引用
# JUNK_DOMAINS 已在文件顶部从 core.vision_service 导入


def _score_source(url: str, alt: str = "", query: str = "", relevance_keywords: List[str] = None) -> float:
    """
    给图片候选源打分：权威域名、精准 query、档案语义、缩略图惩罚。

    评分维度（总分 1.0）：
    - 权威域名 +0.35（.gov/.edu/.org 等）
    - 档案机构 +0.20（museum/archive/memorial 等）
    - 历史相关性 +0.18（historical/vintage/老照片 等）
    - 主题关键词匹配 +0.22（由 relevance_keywords 动态传入）
    - 垃圾站惩罚 -0.50（图库/SEO农场/缩略图）
    - 尺寸惩罚 -0.30（URL 中含 thumb/icon/logo 等）
    """
    relevance_keywords = relevance_keywords or []
    low = f"{url} {alt} {query}".lower()
    score = 0.0

    # 正向加分
    if any(d in low for d in AUTHORITY_DOMAIN_SUFFIXES):
        score += 0.35
    if any(k in low for k in ["archive", "archives", "museum", "memorial", "档案", "纪念馆", "研究中心", "图书馆", "library", "cave", "grotto", "heritage", "collection", "exhibit", "catalog"]):
        score += 0.20
    if any(k in low for k in ["historical", "history", "vintage", "old photo", "老照片", "历史照片", "旧照", "黑白", "black and white", "sepia"]):
        score += 0.18
    # 动态主题关键词匹配（不再硬编码）
    if relevance_keywords:
        hits = sum(1 for kw in relevance_keywords if kw.lower() in low)
        if hits > 0:
            score += min(0.22, 0.22 * hits / max(len(relevance_keywords), 1))

    # 负向惩罚
    if any(d in low for d in JUNK_DOMAINS):
        score -= 0.50
    if any(k in low for k in ["thumbnail", "thumb", "logo", "icon", "avatar", "sprite", "favicon", "tse"]):
        score -= 0.30

    return max(0.0, min(1.0, score))


def collect_image_candidates(crawled: List[dict], relevance_keywords: List[str] = None) -> List[Dict[str, Any]]:
    """聚合图片候选并保留元数据：query、source_page、alt、source_score。"""
    seen = set()
    candidates: List[Dict[str, Any]] = []
    relevance_keywords = relevance_keywords or []

    def add(img: Dict[str, Any], parent: Dict[str, Any], sub: Dict[str, Any] = None):
        src = img.get("src", "") if isinstance(img, dict) else ""
        if not src or src in seen:
            return
        seen.add(src)
        page = (sub or parent).get("url", "")
        query = parent.get("semantic_query", "") or parent.get("name", "")
        alt = img.get("alt", "")
        context = img.get("context", "")  # 保留从 extract_images_with_context 来的上下文
        # 合并 parent 的 relevance_keywords
        parent_kw = parent.get("relevance_keywords", [])
        all_kw = list(set(relevance_keywords + parent_kw))
        candidates.append({
            "url": src,
            "src": src,
            "alt": alt,
            "title": img.get("title", ""),
            "context": context,
            "source": img.get("source") or parent.get("method", "unknown"),
            "source_page": page,
            "source_page_url": img.get("source_page_url", ""),  # 百度图片来源页URL
            "query": query,
            "source_score": _score_source(src, alt, query, relevance_keywords=all_kw),
        })

    for r in crawled:
        if not r.get("success"):
            continue
        for img in r.get("images", []):
            add(img, r)
        for sub in r.get("sub_articles", []):
            if sub.get("success"):
                for img in sub.get("images", []):
                    add(img, r, sub)

    candidates.sort(key=lambda x: x.get("source_score", 0), reverse=True)
    return candidates


async def enrich_image_contexts(
    candidates: List[Dict[str, Any]],
    max_pages: int = 8,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """为缺少上下文的图片补充上下文：爬取来源页提取图片周围文字。

    双管齐下之方法1：利用图片在原网页中的上下文确定图片与什么内容相关。
    百度图片搜索的图片通常缺少上下文，但可能带有 source_page_url，
    此函数爬取这些来源页，用 extract_images_with_context 提取上下文。
    """
    # 筛选缺少上下文但有来源页URL的图片
    need_context = []
    for c in candidates:
        if c.get("context"):
            continue  # 已有上下文，跳过
        source_url = c.get("source_page_url") or c.get("source_page", "")
        if not source_url or not source_url.startswith("http"):
            continue
        # 排除百度自身页面（没有有用上下文）
        if any(d in source_url for d in [
            "baidu.com/link?", "baidu.com/s?", "image.baidu.com",
            "bing.com/images", "google.com/img",
        ]):
            continue
        need_context.append(c)

    if not need_context:
        return candidates

    print(f"[Context] {len(need_context)} 张图片缺少上下文，尝试爬取来源页补充")
    fetched = 0

    try:
        import aiohttp
        from bs4 import BeautifulSoup

        sem = asyncio.Semaphore(4)

        async def _fetch_context(c):
            """爬取单个来源页提取上下文，返回是否成功"""
            nonlocal fetched
            if fetched >= max_pages:
                return False
            source_url = c.get("source_page_url") or c.get("source_page", "")
            async with sem:
                try:
                    async with session.get(source_url) as resp:
                        if resp.status != 200:
                            return False
                        html_text = await resp.text(errors="ignore")
                        if len(html_text) < 200:
                            return False

                    soup = BeautifulSoup(html_text, "html.parser")
                    images_with_ctx = extract_images_with_context(
                        soup, source_url, max_context_chars=300,
                    )

                    img_src = c.get("src", "")
                    for img in images_with_ctx:
                        if img.get("src") == img_src and img.get("context"):
                            c["context"] = img["context"]
                            return True

                    img_alt = c.get("alt", "").lower()
                    for img in images_with_ctx:
                        if img_alt and img_alt in (img.get("alt", "") or img.get("context", "")).lower():
                            c["context"] = img.get("context", "")
                            return True

                    return False
                except Exception:
                    return False

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"),
            },
        ) as session:
            tasks = [_fetch_context(c) for c in need_context[:max_pages * 2]]
            results = await asyncio.gather(*tasks)
            fetched = sum(1 for r in results if r)

    except ImportError:
        print("[Context] aiohttp 未安装，跳过上下文补充")

    if fetched > 0:
        print(f"[Context] 成功为 {fetched}/{len(need_context)} 张图片补充了上下文")

    return candidates


def collect_image_urls(crawled: List[dict], relevance_keywords: List[str] = None) -> List[str]:
    return [c["url"] for c in collect_image_candidates(crawled, relevance_keywords)]


def count_relevance(text: str, keywords: List[str]) -> int:
    """计算文本与关键词的相关性得分。

    策略：
    1. 完整关键词匹配（权重 3x）
    2. 关键词拆分后的子词匹配（权重 1x），避免短词过度匹配
    3. 同义词扩展（如 国产大飞机 ↔ C919）
    """
    if not text or not keywords:
        return 0
    text_lower = text.lower()
    score = 0
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        # 完整匹配（权重高）
        score += text_lower.count(kw.lower()) * 3
        # 拆分后的子词匹配（仅当关键词长度 > 2 且拆出有意义词时）
        parts = [p for p in kw.split() if len(p) > 2]
        for part in parts:
            part_lower = part.lower()
            if part_lower != kw.lower():
                score += text_lower.count(part_lower)
        # 数字/型号提取（如 C919 国产大飞机 → 也匹配 "C919"）
        import re as _re
        nums = _re.findall(r'[A-Z]*\d+[A-Z]*', kw, _re.I)
        for num in nums:
            if len(num) > 1:
                score += text_lower.count(num.lower()) * 2
    return score


_match_image_counter = 0

def match_image_for_label(
    label: str,
    downloaded: List[Dict],
    url_to_local: Dict[str, str],
    crawled_images: List[Dict],
) -> Optional[str]:
    """按关键词为人物/事件匹配本地图片路径，优先按关键词匹配，fallback 时轮询分配不同图片"""
    global _match_image_counter
    label_lower = label.lower()
    for img in crawled_images:
        if not isinstance(img, dict):
            continue
        alt = (img.get("alt") or "").lower()
        src = img.get("src", "")
        if label in alt or any(c in alt for c in label if len(c) > 1):
            rel = url_to_local.get(src)
            if rel:
                return rel
    # fallback: 轮询分配已下载的不同图片，避免全部指向同一张
    valid = [d for d in downloaded if isinstance(d, dict) and d.get("relative_path")]
    if valid:
        idx = _match_image_counter % len(valid)
        _match_image_counter += 1
        return valid[idx]["relative_path"]
    return None


def build_url_to_local(downloaded: List[Dict]) -> Dict[str, str]:
    return {d["url"]: d["relative_path"] for d in downloaded if isinstance(d, dict) and d.get("url")}


async def smart_match_images_with_vision(
    downloaded: List[Dict],
    archive_data: Dict,
    output_dir: str = "",
    enable_vision: bool = True,
) -> Dict[str, List[str]]:
    """
    使用千问视觉模型智能识别图片内容并分配到合适位置
    返回分类后的图片路径: {"figures": [], "timeline": [], "gallery": [], "overview": []}
    """
    # 获取所有已下载图片的本地路径
    image_paths = []
    for d in downloaded:
        rel = d.get("relative_path", "")
        if rel:
            full_path = os.path.join(output_dir, rel) if output_dir else rel
            if os.path.exists(full_path):
                image_paths.append(full_path)

    if not image_paths:
        return {"figures": [], "timeline": [], "gallery": [], "overview": []}

    # 如果启用视觉识别且图片数量不多（控制成本）
    if enable_vision and len(image_paths) <= 20:
        try:
            vision = VisionService()
            categories = await vision.categorize_images(image_paths)
            await vision.close()

            # 将完整路径转回相对路径
            result = {}
            for cat, paths in categories.items():
                result[cat] = []
                for p in paths:
                    # 找到对应的相对路径
                    for d in downloaded:
                        if d.get("relative_path") and p.endswith(d["relative_path"]):
                            result[cat].append(d["relative_path"])
                            break
            return result
        except Exception:
            # 视觉模型失败时回退到简单分类
            pass

    # 简单分类：有人物关键词的alt分配给figures，其余gallery
    figures = []
    gallery = []
    for d in downloaded:
        rel = d.get("relative_path", "")
        alt = d.get("alt", "").lower()
        if rel:
            if any(kw in alt for kw in ["人", "人物", "肖像", "profile", "portrait", "头像"]):
                figures.append(rel)
            else:
                gallery.append(rel)

    return {"figures": figures, "timeline": gallery, "gallery": gallery, "overview": []}


async def analyze_and_categorize_images(
    downloaded: List[Dict],
    archive_data: Dict,
    output_dir: str = "",
    enable_vision: bool = True,
) -> Dict[str, Any]:
    """
    高级图片分析与分类：使用千问视觉模型识别图片内容，
    判断每张图片适合放在网站的哪个位置
    
    返回包含分类结果和详细分析的字典
    """
    image_paths = []
    path_to_download = {}
    
    for d in downloaded:
        if not isinstance(d, dict):
            continue
        rel = d.get("relative_path", "")
        if rel:
            full_path = os.path.join(output_dir, rel) if output_dir else rel
            if os.path.exists(full_path):
                image_paths.append(full_path)
                path_to_download[full_path] = d

    if not image_paths:
        return {
            "categories": {"figures": [], "timeline": [], "gallery": [], "overview": []},
            "analyses": [],
            "method": "none"
        }

    analyses = []
    categories = {"figures": [], "timeline": [], "gallery": [], "overview": []}

    if enable_vision:
        vision_ok = 0
        vision_fail = 0
        try:
            vision = VisionService()
            batch_results = await vision.batch_analyze(image_paths, max_concurrent=5)

            for analysis in batch_results:
                if isinstance(analysis, Exception):
                    vision_fail += 1
                    continue

                full_path = analysis.get("path", "")
                d = path_to_download.get(full_path, {})
                rel_path = d.get("relative_path", "")
                if not rel_path:
                    vision_fail += 1
                    continue

                if analysis.get("error"):
                    vision_fail += 1
                    continue

                vision_ok += 1
                img_analysis = {
                    "path": rel_path,
                    "description": analysis.get("description", ""),
                    "tags": analysis.get("tags", []),
                    "quality_score": analysis.get("quality_score", 5),
                    "has_people": analysis.get("has_people", False),
                    "has_text": analysis.get("has_text", False),
                    "has_landscape": analysis.get("has_landscape", False),
                    "has_historical_content": analysis.get("has_historical_content", False),
                    "suitable_for": analysis.get("suitable_for", ["gallery"]),
                }
                analyses.append(img_analysis)

                # 一张图片可以同时属于多个类别，为下游匹配提供更大候选池
                if img_analysis["has_people"]:
                    categories["figures"].append(rel_path)
                    # 有人物的图片也可作为 gallery 展示
                    categories["gallery"].append(rel_path)
                if img_analysis["has_text"]:
                    categories["overview"].append(rel_path)
                if img_analysis["has_landscape"] or img_analysis["has_historical_content"]:
                    categories["timeline"].append(rel_path)
                    categories["gallery"].append(rel_path)
                # 如果以上都没有，归入 gallery；如果已有 gallery 也不重复
                if not (img_analysis["has_people"] or img_analysis["has_text"] or
                        img_analysis["has_landscape"] or img_analysis["has_historical_content"]):
                    categories["gallery"].append(rel_path)
                elif rel_path not in categories["gallery"]:
                    # 有其他特征但没进 gallery 的也补进去
                    categories["gallery"].append(rel_path)

            await vision.close()

            if vision_ok > 0:
                print(f"[Vision] 成功分析 {vision_ok}/{len(image_paths)} 张图片 (失败 {vision_fail})")
                return {"categories": categories, "analyses": analyses, "method": "vision"}

            print(f"[Vision] 全部 {len(image_paths)} 张图片分析失败，回退到本地规则")

        except Exception as e:
            print(f"[Vision] 视觉模型调用异常: {type(e).__name__}: {e}")

    for d in downloaded:
        if not isinstance(d, dict):
            continue
        rel = d.get("relative_path", "")
        if not rel:
            continue

        full_path = os.path.join(output_dir, rel) if output_dir else rel
        alt = d.get("alt", "").lower()
        url = d.get("url", "").lower()
        file_size = d.get("file_size", 0)

        if file_size and file_size < 2000:
            continue

        has_person = any(kw in alt or kw in url for kw in
                        ["人", "人物", "肖像", "profile", "portrait", "头像", "leader", "hero", "作者", "大师"])
        has_document = any(kw in alt or kw in url for kw in
                          ["文档", "document", "text", "手稿", "letter", "archive", "古籍", "书", "卷"])
        has_scene = any(kw in alt or kw in url for kw in
                       ["场景", "风景", "建筑", "building", "scene", "landscape", "map", "地图", "全景"])

        analyses.append({
            "path": rel, "description": alt, "tags": [],
            "quality_score": 5, "has_people": has_person,
            "has_text": has_document, "has_landscape": has_scene,
            "has_historical_content": has_scene, "suitable_for": ["gallery"],
        })

        # fallback 路径同样允许一张图属于多个类别
        if has_person:
            categories["figures"].append(rel)
            categories["gallery"].append(rel)
        if has_document:
            categories["overview"].append(rel)
        if has_scene:
            categories["timeline"].append(rel)
            categories["gallery"].append(rel)
        if not (has_person or has_document or has_scene):
            if os.path.exists(full_path) and os.path.getsize(full_path) > 3000:
                categories["gallery"].append(rel)
        elif rel not in categories["gallery"]:
            categories["gallery"].append(rel)

    return {"categories": categories, "analyses": analyses, "method": "fallback"}


async def analyze_archive_with_llm(
    router: MultiLLMRouter,
    crawled_text: str,
    relevance_keywords: List[str],
    archive_type: str = "custom",
    archive_name: str = "档案",
    min_relevance: int = 12,
) -> Tuple[dict, str]:
    """
    基于爬虫文本用 LLM 生成结构化档案 JSON（通用版本）。
    返回 (data_dict, source) source 为 crawled / llm / fallback
    """
    score = count_relevance(crawled_text, relevance_keywords)
    use_crawled = score >= min_relevance and len(crawled_text.strip()) > 200

    # 根据档案类型决定 time_span 的 prompt 描述
    is_person = archive_type == "person" or any(
        kw in archive_name for kw in ["人物", "传记", "生平"]
    )
    time_span_hint = (
        'time_span（生卒年，如"1922–1964"，必须从资料中提取真实生卒年份，不要用当前年份）'
        if is_person else
        'time_span（如"1958–至今"，反映资料覆盖的时间范围）'
    )

    if use_crawled:
        user_prompt = f"""你是一位资深档案研究专家。请**严格基于以下爬虫采集的真实资料**，
为「{archive_name}」撰写一份有深度的档案数字叙事。不要编造未出现的细节，
但要充分挖掘资料中的历史脉络、人物故事和技术细节。

爬虫资料：
{crawled_text[:60000]}

请输出完整 JSON（```json 包裹），字段要求：
- archive_title: "{archive_name}"
- archive_type: "{archive_name}"
- overview: 200-300字，用档案叙事风格，包含：起源背景、发展脉络、历史地位、核心价值。要有档案的厚重感和时间纵深感，像博物馆展墙上的前言。
- key_stats: 包含 {time_span_hint}、key_figures_count、milestone_events_count、generations（发展阶段数）
- timeline: 8-12个里程碑事件，每项 date/event/location/description（description 60-100字，要有具体细节，不要空洞概括）
- figures: 5-8个关键人物，每人 name/role/bio（80-120字）/contribution（具体贡献）
- spirit: title/content（150-200字，提炼精神内涵）/keywords（8个关键词）
- route_summary: 一句话概括发展历程（30字内）
确保 JSON 完整闭合。"""
    else:
        return _fallback_archive_data(archive_name), "no_data"

    messages = [
        {
            "role": "system",
            "content": (
                f"你是{archive_name}领域的档案研究专家，擅长撰写有历史纵深感的档案叙事。"
                f"只输出 ```json ... ``` 代码块，确保 JSON 合法闭合。"
            ),
        },
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await router.chat_with_fallback(
            messages, 
            agent_name="ArchiveAnalysisAgent",  # 自动使用 qwen-long 长文档模型
            temperature=0.5, 
            max_tokens=4096
        )
        content = response["choices"][0]["message"]["content"]
    except Exception as e:
        import traceback as _tb
        print(f"[WARN] analyze_archive_with_llm LLM 调用失败: {type(e).__name__}: {e}")
        _tb.print_exc()
        return _fallback_archive_data(archive_name), "fallback"

    data = parse_json_from_llm(content)
    if data:
        # 幻觉检测：产出标题必须包含用户指定的档案名
        title = data.get("archive_title", "")
        archive_type_check = data.get("archive_type", "")
        if archive_name and archive_name not in title and archive_name not in archive_type_check:
            return _fallback_archive_data(archive_name), "hallucination_rejected"
        return data, "crawled" if use_crawled else "llm"
    return _fallback_archive_data(archive_name), "fallback"


# 保留旧名称作为别名，兼容已有调用
analyze_long_march_with_llm = analyze_archive_with_llm


def parse_json_from_llm(llm_content: str) -> Optional[dict]:
    bt = "```"
    json_match = re.search(bt + r"json\s*\n(.*?)(?:\n\s*)?" + bt, llm_content, re.DOTALL)
    if not json_match:
        json_match = re.search(
            r'\{[\s\S]*"archive_title"[\s\S]*\}', llm_content
        )
    if not json_match:
        return None

    raw = json_match.group(1) if json_match.lastindex else json_match.group()
    raw = re.sub(r"(\d+)余次", r"\1", raw)
    raw = re.sub(r"(\d+)\+", r"\1", raw)
    raw = raw.replace("，", ",")

    for attempt in range(3):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 0:
                last_good = max(
                    raw.rfind("},\n  {"),
                    raw.rfind('],\n  "'),
                    raw.rfind('"\n}'),
                    raw.rfind('"\n  }'),
                )
                if last_good > 0:
                    bracket_count = raw.count("{") - raw.count("}")
                    raw = raw[:last_good] + "\n}" + "}" * max(0, bracket_count - 1)
                else:
                    break
            elif attempt == 1:
                raw = raw.replace("\u201c", '"').replace("\u201d", '"')
            else:
                break
    return None


def _fallback_archive_data(archive_name: str = "档案") -> dict:
    """通用 fallback 数据，当 LLM 分析失败时返回基本结构（改进质量）"""
    import datetime
    current_year = datetime.datetime.now().year
    
    return {
        "archive_title": archive_name,
        "archive_type": archive_name,
        "overview": (
            f"「{archive_name}」专题尚在建设中。当前网络爬取未获取到足够数据，"
            f"显示为基础框架。您可以通过以下方式丰富内容：\n"
            f"1) 上传本地档案文件（Word/PDF/图片）\n"
            f"2) 在搜索框中输入更具体的关键词（如人物名、地名、事件名）\n"
            f"3) 尝试英文关键词获取国际档案资料"
        ),
        "key_stats": {"data_completeness": "基础框架"},
        "timeline": [],
        "figures": [],
        "spirit": {
            "title": f"关于「{archive_name}」",
            "content": (
                f"每个档案背后都有一段值得被讲述的故事。"
                f"当前「{archive_name}」的资料仍在收集中，"
                f"邀请您贡献更多线索与资料，共同构建完整的数字叙事。"
            ),
            "keywords": [archive_name, "数字叙事", "档案"],
        },
        "route_summary": f"「{archive_name}」数字叙事 — 资料征集中",
    }


# 保留旧名称兼容
_fallback_long_march_data = _fallback_archive_data


async def download_crawl_images(
    crawled: List[dict],
    output_dir: str,
    max_images: int = 40,
    verify_keywords: Optional[List[str]] = None,
    theme: str = "",
) -> List[Dict]:
    """下载爬虫结果中的图片

    Args:
        crawled: 爬虫返回的页面列表
        output_dir: 图片保存目录
        max_images: 最大图片数
        verify_keywords: 相关性关键词，传了之后会调 qwen3-vl-max 逐张过滤
        theme: 主题描述，VL 验证时使用

    Returns:
        下载成功（且通过 VL 验证）的图片列表
    """
    candidates = collect_image_candidates(crawled, relevance_keywords=verify_keywords)
    if not candidates:
        return []
    downloader = ImageDownloader(
        output_dir,
        max_images=max_images,
        verify_keywords=verify_keywords,
        theme=theme,
    )
    return await downloader.download_batch(candidates)
