"""
HTML 档案叙事网站生成器 v3

全新视觉系统，替代旧版随机配色方案。
- 5 套专业视觉风格（典藏纸本/黑金展陈/清冷学术/温润记忆/科技档案）
- 叙事结构：钩子 → 概述 → 时间线 → 人物 → 图库 → 来源
- 图片标注来源
- 响应式布局，档案展览质感
"""

import hashlib
from typing import Dict, List, Optional


# ============================================================================
# 视觉风格系统
# ============================================================================

STYLES = {
    "classic": {
        "name": "典藏纸本",
        "bg": "#faf6f0",
        "card": "#fffef9",
        "text": "#3d3226",
        "muted": "#8c7b6b",
        "primary": "#8B4513",
        "accent": "#c1783a",
        "hero_bg": "linear-gradient(135deg, #3d3226 0%, #5c4033 40%, #8B4513 100%)",
        "hero_text": "#faf6f0",
        "font": "'Noto Serif SC', 'Source Han Serif SC', Georgia, serif",
        "border": "#e8dccf",
        "tag_bg": "#f0e8d8",
    },
    "dark_gold": {
        "name": "黑金展陈",
        "bg": "#1a1a1a",
        "card": "#252525",
        "text": "#e8e0d0",
        "muted": "#998866",
        "primary": "#d4a854",
        "accent": "#c9a96e",
        "hero_bg": "linear-gradient(135deg, #0a0a0a 0%, #1a1a1a 50%, #2a2010 100%)",
        "hero_text": "#d4a854",
        "font": "'Noto Serif SC', Georgia, serif",
        "border": "#3a3028",
        "tag_bg": "#2a2518",
    },
    "academic": {
        "name": "清冷学术",
        "bg": "#f5f7fa",
        "card": "#ffffff",
        "text": "#2c3e50",
        "muted": "#7f8c8d",
        "primary": "#34495e",
        "accent": "#5b7fa5",
        "hero_bg": "linear-gradient(135deg, #1a2a3a 0%, #2c3e50 60%, #34495e 100%)",
        "hero_text": "#ecf0f1",
        "font": "'Noto Serif SC', 'Source Han Serif SC', serif",
        "border": "#dfe6e9",
        "tag_bg": "#eef1f5",
    },
    "warm_memory": {
        "name": "温润记忆",
        "bg": "#fdf8f3",
        "card": "#fffaf5",
        "text": "#4a3728",
        "muted": "#a08870",
        "primary": "#c07850",
        "accent": "#d4956b",
        "hero_bg": "linear-gradient(135deg, #5c3a28 0%, #8b5a3c 40%, #c07850 100%)",
        "hero_text": "#fdf8f3",
        "font": "'Noto Serif SC', Georgia, serif",
        "border": "#ecd9c6",
        "tag_bg": "#f5e6d8",
    },
    "tech_archive": {
        "name": "科技档案",
        "bg": "#f0f2f5",
        "card": "#ffffff",
        "text": "#1e293b",
        "muted": "#64748b",
        "primary": "#2563eb",
        "accent": "#3b82f6",
        "hero_bg": "linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #1e3a5f 100%)",
        "hero_text": "#f8fafc",
        "font": "'Noto Sans SC', 'Source Han Sans SC', sans-serif",
        "border": "#e2e8f0",
        "tag_bg": "#e8ecf1",
    },
}


def pick_style(theme: str = "", archive_type: str = "") -> Dict:
    """根据档案类型推荐视觉风格。"""
    # 预定义专题映射
    _type_style_map = {
        "red_archives": "classic",
        "intangible_heritage": "warm_memory",
        "folk_archives": "warm_memory",
        "game_archives": "tech_archive",
        "social_media": "tech_archive",
        "celebrity_archives": "classic",
    }
    style_name = _type_style_map.get(archive_type)
    if style_name and style_name in STYLES:
        return STYLES[style_name]
    # 默认：根据主题确定性哈希选一个稳定的风格
    digest = hashlib.md5((theme or "custom").encode("utf-8")).hexdigest()
    keys = list(STYLES.keys())
    return STYLES[keys[int(digest[:8], 16) % len(keys)]]


# ============================================================================
# HTML 组件
# ============================================================================

def _escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_hero(title: str, subtitle: str, stats: List[tuple], style: Dict) -> str:
    """首页 Hero 区域 — 展览入口感"""
    # 移除统计项，只保留标题和副标题
    return f'''<section class="hero" style="background:{style['hero_bg']};color:{style['hero_text']}">
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <div class="hero-badge">档案数字叙事</div>
    <h1 class="hero-title">{_escape(title)}</h1>
    {f'<p class="hero-subtitle">{_escape(subtitle)}</p>' if subtitle else ''}
  </div>
</section>'''


def _build_overview(overview: str, key_stats: Dict, style: Dict, archive_type: str = "", route_summary: str = "") -> str:
    # 移除统计项，改为一句话关键词摘要
    summary_html = ""
    if route_summary:
        summary_html = f'<p class="route-summary" style="text-align:center;color:{style["muted"]};font-size:1.1em;margin-bottom:2rem;font-style:italic">{_escape(route_summary)}</p>'

    return f'''<section class="section" id="overview" style="background:{style['bg']}">
  <div class="container">
    <h2 class="section-title" style="color:{style['primary']}">概述</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    {summary_html}
    <div class="prose" style="color:{style['text']}">{_escape(overview)}</div>
  </div>
</section>'''


def _build_timeline(events: List[Dict], style: Dict) -> str:
    if not events:
        return ""
    items = ""
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        date = ev.get("date", ev.get("time", ""))
        event = ev.get("event", ev.get("title", ""))
        location = ev.get("location", "")
        desc = ev.get("description", "")
        img = ev.get("image", "")
        side = "left" if i % 2 == 0 else "right"

        img_html = ""
        if img:
            img_html = f'<div class="tl-image"><img src="{_escape(img)}" alt="{_escape(event)}" loading="lazy"></div>'

        items += f'''<div class="timeline-item {side}">
    <div class="tl-marker" style="background:{style['accent']}"></div>
    <div class="tl-card" style="background:{style['card']};border:1px solid {style['border']}">
      {img_html}
      <div class="tl-date" style="color:{style['accent']}">{_escape(str(date))}</div>
      <h3 class="tl-event" style="color:{style['text']}">{_escape(event)}</h3>
      {f'<div class="tl-location" style="color:{style["muted"]}">📍 {_escape(location)}</div>' if location else ''}
      {f'<p class="tl-desc" style="color:{style["muted"]}">{_escape(desc)}</p>' if desc else ''}
    </div>
  </div>'''

    return f'''<section class="section" id="timeline" style="background:{style['bg']}">
  <div class="container">
    <h2 class="section-title" style="color:{style['primary']}">时间线</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    <div class="timeline">{items}</div>
  </div>
</section>'''


def _build_figures(figures: List[Dict], style: Dict) -> str:
    if not figures:
        return ""
    cards = ""
    for f in figures:
        if not isinstance(f, dict):
            continue
        name = f.get("name", "")
        role = f.get("role", "")
        bio = f.get("bio", f.get("description", ""))
        contribution = f.get("contribution", "")
        img = f.get("image", "")
        img_html = f'<div class="figure-avatar"><img src="{_escape(img)}" alt="{_escape(name)}" loading="lazy"></div>' if img else '<div class="figure-avatar placeholder">👤</div>'
        cards += f'''<div class="figure-card" style="background:{style['card']};border:1px solid {style['border']}">
    {img_html}
    <h3 class="figure-name" style="color:{style['text']}">{_escape(name)}</h3>
    <div class="figure-role" style="color:{style['accent']}">{_escape(role)}</div>
    {f'<p class="figure-bio" style="color:{style["muted"]}">{_escape(bio[:200])}</p>' if bio else ''}
    {f'<p class="figure-contribution" style="color:{style["muted"]}">🎖 {_escape(contribution[:120])}</p>' if contribution else ''}
  </div>'''

    return f'''<section class="section" id="figures" style="background:{style['bg']}">
  <div class="container">
    <h2 class="section-title" style="color:{style['primary']}">人物</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    <div class="figure-grid">{cards}</div>
  </div>
</section>'''


def _build_gallery(images: List, style: Dict) -> str:
    """图库 — 只使用本地图片，过滤外部URL"""
    if not images:
        return ""
    items = ""
    for img in images[:24]:
        if isinstance(img, str):
            src = img
            caption = ""
        elif isinstance(img, dict):
            # 优先取本地路径（relative_path），而非 src（src 通常是原始外部URL，已无法访问）
            src = img.get("path", img.get("relative_path", img.get("local_path", img.get("src", ""))))
            caption = img.get("caption", img.get("description", img.get("alt", "")))
        else:
            continue
        if not src:
            continue
        # 过滤外部URL，只保留本地图片
        if src.startswith("http://") or src.startswith("https://"):
            continue
        # 确保路径以 images/ 开头
        if not src.startswith("images/") and not src.startswith("./images/"):
            if "/" not in src and "\\" not in src:
                src = "images/" + src
        items += f'''<div class="gallery-item">
    <div class="gallery-img-wrap">
      <img src="{_escape(src)}" alt="{_escape(caption)}" loading="lazy">
    </div>
    {f'<p class="gallery-caption" style="color:{style["muted"]}">{_escape(caption[:80])}</p>' if caption else ''}
  </div>'''

    if not items:
        return ""
    return f'''<section class="section" id="gallery" style="background:{style['bg']}">
  <div class="container">
    <h2 class="section-title" style="color:{style['primary']}">影像档案</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    <div class="gallery-grid">{items}</div>
  </div>
</section>'''


def _build_sources(sources: List[Dict], style: Dict) -> str:
    """来源引用区域"""
    if not sources:
        return ""
    items = ""
    for s in sources[:20]:
        title = s.get("title", "")[:80]
        url = s.get("url", "")
        domain = s.get("domain", "")
        credibility = s.get("credibility", 3)
        display_score = max(1, min(5, 6 - int(credibility)))
        stars = "★" * display_score + "☆" * (5 - display_score)
        items += f'''<li class="source-item">
    <a href="{_escape(url)}" target="_blank" rel="noopener" style="color:{style['primary']}">{_escape(title)}</a>
    <span class="source-domain" style="color:{style['muted']}">{_escape(domain)}</span>
    <span class="source-credibility">{stars}</span>
  </li>'''

    return f'''<section class="section" id="sources" style="background:{style['card']}">
  <div class="container">
    <h2 class="section-title" style="color:{style['primary']}">资料来源</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    <p style="color:{style['muted']};font-size:0.9em;margin-bottom:1.5em">
      以下为本档案叙事所引用的信息来源，按可信度标注。
    </p>
    <ol class="source-list">{items}</ol>
  </div>
</section>'''


# ============================================================================
# CSS
# ============================================================================

BASE_CSS = '''
/* ===== Reset & Base ===== */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth;font-size:16px}
body{font-family:var(--font);line-height:1.7;overflow-x:hidden}
.container{max-width:1100px;margin:0 auto;padding:0 1.5rem}
.section{padding:4rem 0}
.section-title{font-size:clamp(1.5rem,4vw,2.2rem);text-align:center;margin-bottom:0.5rem;font-weight:800;letter-spacing:0.05em}
.divider{width:60px;height:3px;margin:0 auto 2.5rem;border-radius:2px}

/* ===== Hero ===== */
.hero{position:relative;min-height:70vh;display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden}
.hero-overlay{position:absolute;inset:0;background:rgba(0,0,0,0.15)}
.hero-content{position:relative;z-index:1;max-width:800px;padding:2rem}
.hero-badge{display:inline-block;padding:0.3em 1.2em;border:1px solid rgba(255,255,255,0.4);border-radius:9999px;font-size:0.8rem;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:1.5rem;backdrop-filter:blur(4px)}
.hero-title{font-size:clamp(2rem,6vw,3.5rem);font-weight:900;letter-spacing:0.03em;line-height:1.2;margin-bottom:1rem}
.hero-subtitle{font-size:clamp(1rem,2.5vw,1.3rem);opacity:0.85;margin-bottom:2rem;max-width:600px;margin-left:auto;margin-right:auto}
.hero-stats{display:flex;gap:2rem;justify-content:center;flex-wrap:wrap}
.hero-stat{text-align:center}
.hero-stat-num{display:block;font-size:2rem;font-weight:900}
.hero-stat-label{font-size:0.85rem;opacity:0.7;letter-spacing:0.08em}

/* ===== Key Stats ===== */
.key-stats{display:flex;gap:1.5rem;justify-content:center;flex-wrap:wrap;margin-bottom:2rem}
.stat-item{background:var(--card);border:1px solid var(--border);padding:1rem 1.5rem;border-radius:8px;text-align:center;min-width:120px;font-size:0.9em}

/* ===== Prose ===== */
.prose{max-width:760px;margin:0 auto;font-size:1.05em;line-height:1.9}

/* ===== Timeline ===== */
.timeline{position:relative;max-width:900px;margin:0 auto}
.timeline::before{content:'';position:absolute;left:50%;top:0;bottom:0;width:2px;background:var(--border);transform:translateX(-50%)}
.timeline-item{position:relative;margin-bottom:3rem;width:50%}
.timeline-item.left{padding-right:2.5rem;text-align:right}
.timeline-item.right{margin-left:50%;padding-left:2.5rem;text-align:left}
.tl-marker{position:absolute;top:1.5rem;width:14px;height:14px;border-radius:50%;z-index:1}
.timeline-item.left .tl-marker{right:-7px}
.timeline-item.right .tl-marker{left:-7px}
.tl-card{padding:1.5rem;border-radius:10px;transition:transform 0.2s}
.tl-card:hover{transform:translateY(-2px)}
.tl-image img{width:100%;height:180px;object-fit:cover;border-radius:6px;margin-bottom:0.8rem}
.tl-date{font-weight:700;font-size:0.9em;margin-bottom:0.3rem}
.tl-event{font-size:1.1em;font-weight:700;margin-bottom:0.3rem}
.tl-location{font-size:0.85em;margin-bottom:0.4rem}
.tl-desc{font-size:0.9em;line-height:1.6}
@media(max-width:768px){
  .timeline::before{left:1.5rem}
  .timeline-item,.timeline-item.left,.timeline-item.right{width:100%;margin-left:0;padding-left:2.8rem;padding-right:0;text-align:left}
  .timeline-item .tl-marker{left:-7px!important}
}

/* ===== Figures ===== */
.figure-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.5rem;max-width:1000px;margin:0 auto}
.figure-card{padding:1.5rem;border-radius:12px;text-align:center;transition:transform 0.2s}
.figure-card:hover{transform:translateY(-3px)}
.figure-avatar{width:90px;height:90px;border-radius:50%;overflow:hidden;margin:0 auto 1rem}
.figure-avatar img{width:100%;height:100%;object-fit:cover}
.figure-avatar.placeholder{display:flex;align-items:center;justify-content:center;font-size:2.5rem;background:var(--tag-bg)}
.figure-name{font-size:1.1em;font-weight:700;margin-bottom:0.2rem}
.figure-role{font-size:0.85em;font-weight:600;margin-bottom:0.6rem}
.figure-bio{font-size:0.85em;line-height:1.6;margin-bottom:0.4rem}
.figure-contribution{font-size:0.8em;margin-top:0.4rem}

/* ===== Gallery ===== */
.gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1.2rem}
.gallery-img-wrap{position:relative;overflow:hidden;border-radius:8px;aspect-ratio:4/3}
.gallery-img-wrap img{width:100%;height:100%;object-fit:cover;transition:transform 0.4s}
.gallery-item:hover .gallery-img-wrap img{transform:scale(1.05)}
.gallery-overlay{position:absolute;bottom:0;left:0;right:0;padding:0.6rem;background:linear-gradient(transparent,rgba(0,0,0,0.7));display:flex;justify-content:space-between;align-items:flex-end;opacity:0;transition:opacity 0.3s}
.gallery-item:hover .gallery-overlay{opacity:1}
.img-era{color:#fff;font-size:0.75em;font-weight:600}
.img-source{color:rgba(255,255,255,0.75);font-size:0.7em}
.gallery-caption{margin-top:0.5rem;font-size:0.85em;line-height:1.4}

/* ===== Source List ===== */
.source-list{max-width:760px;margin:0 auto;list-style:none;counter-reset:source}
.source-item{padding:0.6rem 0;border-bottom:1px solid var(--border);font-size:0.9em;display:flex;align-items:baseline;gap:0.6em;flex-wrap:wrap}
.source-item::before{counter-increment:source;content:"[" counter(source) "]";color:var(--muted);font-size:0.8em;min-width:2em}
.source-domain{font-size:0.75em;padding:0.15em 0.5em;border-radius:4px;background:var(--tag-bg)}
.source-credibility{font-size:0.7em;margin-left:auto}

/* ===== Footer ===== */
.site-footer{text-align:center;padding:2.5rem 1rem;font-size:0.8em}
.site-footer p{opacity:0.6}

/* ===== Animations ===== */
@keyframes fadeInUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
.hero-content{animation:fadeInUp 0.8s ease-out}
.section{animation:fadeInUp 0.6s ease-out;animation-fill-mode:both}
#overview{animation-delay:0.1s}
#timeline{animation-delay:0.2s}
#figures{animation-delay:0.3s}
#gallery{animation-delay:0.4s}
#sources{animation-delay:0.5s}
'''


# ============================================================================
# 主入口
# ============================================================================

def build_archive_website(
    data: Dict,
    gallery_images: List = None,
    theme: str = "",
    archive_type: str = "",
    sources: List[Dict] = None,
) -> str:
    """生成完整的单页档案叙事网站 HTML。

    Args:
        data: 结构化档案数据 (archive_title, overview, timeline, figures, spirit, key_stats)
        gallery_images: 图片列表
        theme: 档案主题名称
        archive_type: 档案类型（用于风格推荐）
        sources: 来源列表 [{"title","url","domain","credibility"}, ...]
    """
    gallery_images = gallery_images or []
    sources = sources or data.get("sources", [])

    title = data.get("archive_title", "档案数字叙事")
    subtitle = data.get("subtitle", "")
    overview = data.get("overview", "")
    timeline = data.get("timeline", [])
    figures = data.get("figures", [])
    spirit = data.get("spirit", {})
    key_stats = data.get("key_stats", {})

    # 选风格
    style = pick_style(theme, archive_type)

    # 生成各部分
    hero = _build_hero(title, subtitle, [], style)
    route_summary = data.get("route_summary", "")
    overview_section = _build_overview(overview, key_stats, style, archive_type, route_summary) if overview else ""
    timeline_section = _build_timeline(timeline, style)
    figures_section = _build_figures(figures, style)

    # spirit 部分
    spirit_section = ""
    if spirit.get("title") and (spirit.get("content") or spirit.get("keywords")):
        keywords_html = ""
        if spirit.get("keywords"):
            tags = "".join(
                f'<span class="spirit-tag" style="background:{style["tag_bg"]};color:{style["primary"]};padding:0.3em 0.8em;border-radius:9999px;font-size:0.85em;margin:0.3em">{_escape(kw)}</span>'
                for kw in spirit["keywords"][:10])
            keywords_html = f'<div class="spirit-tags" style="display:flex;flex-wrap:wrap;gap:0.4em;justify-content:center;margin-top:1em">{tags}</div>'
        spirit_section = f'''<section class="section" id="spirit" style="background:{style['card']}">
  <div class="container" style="text-align:center">
    <h2 class="section-title" style="color:{style['primary']}">{_escape(spirit.get("title", "核心价值"))}</h2>
    <div class="divider" style="background:{style['accent']}"></div>
    <div class="prose" style="color:{style['text']};max-width:700px;margin:0 auto">{_escape(spirit.get("content", ""))}</div>
    {keywords_html}
  </div>
</section>'''

    gallery_section = _build_gallery(gallery_images, style)
    sources_section = _build_sources(sources, style)

    # 组装
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_escape(title)} — 档案数字叙事</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
:root{{
  --font:{style['font']};
  --card:{style['card']};
  --border:{style['border']};
  --tag-bg:{style['tag_bg']};
  --muted:{style['muted']};
}}
{BASE_CSS}
</style>
</head>
<body style="background:{style['bg']};color:{style['text']};font-family:{style['font']}">

{hero}
{overview_section}
{timeline_section}
{figures_section}
{spirit_section}
{gallery_section}
{sources_section}

<footer class="site-footer" style="background:{style['card']};color:{style['muted']}">
  <div class="container">
    <p>{_escape(title)} · 档案数字叙事</p>
    <p>数据来源: {len(sources)} 个 | 图片: {len(gallery_images)} 张 | 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}</p>
  </div>
</footer>

</body>
</html>'''

    return html
