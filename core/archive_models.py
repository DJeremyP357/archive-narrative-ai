"""
统一档案数据模型

定义系统中所有核心对象的强类型结构，替代之前松散的 dict 字段传递。
每个对象都包含来源追溯字段，支撑证据链。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================================
# 来源与证据
# ============================================================================

@dataclass
class SourceMaterial:
    """一份原始材料（网页、文档、图片等）"""
    url: str = ""                           # 来源 URL
    title: str = ""                         # 材料标题
    source_type: str = "web"                # web | document | image | user_upload
    domain: str = ""                        # 域名
    credibility: int = 3                    # 可信度 1-5 (1=最高)
    crawl_timestamp: str = ""               # 爬取时间
    text_snippet: str = ""                  # 原文片段（用于引用）


@dataclass
class EvidenceItem:
    """一条可追溯的证据"""
    claim: str = ""                         # 陈述（从材料中提取的事实）
    source: Optional[SourceMaterial] = None # 来源
    evidence_type: str = "text"             # text | image | reference
    confidence: str = "medium"              # high | medium | low


# ============================================================================
# 媒体资产
# ============================================================================

@dataclass
class MediaAsset:
    """一张图片或其他媒体文件"""
    local_path: str = ""                    # 本地相对路径
    remote_url: str = ""                    # 原始 URL
    alt_text: str = ""                      # alt 文本
    description: str = ""                   # VL 模型描述
    context: str = ""                       # 在原文章中的上下文
    width: int = 0
    height: int = 0
    file_size: int = 0
    era: str = ""                           # VL 判断的年代
    content_type: str = "other"             # portrait | document | scene | object
    category: str = "gallery"               # figures | timeline | gallery | overview
    quality_score: float = 5.0
    source: Optional[SourceMaterial] = None # 来源
    verified: bool = False                  # VL 验证是否通过


# ============================================================================
# 档案实体
# ============================================================================

@dataclass
class ArchiveEntity:
    """档案核心对象：人物/事件/地点/机构/物件"""
    entity_type: str = ""                   # person | event | location | organization | object
    name: str = ""
    role: str = ""                          # 角色/身份
    description: str = ""
    bio: str = ""                           # 详细传记
    contribution: str = ""                  # 贡献/意义
    image: Optional[str] = None             # 关联图片路径
    sources: List[SourceMaterial] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """时间线节点"""
    date: str = ""
    event: str = ""
    location: str = ""
    description: str = ""
    image: Optional[str] = None
    sources: List[SourceMaterial] = field(default_factory=list)


# ============================================================================
# 叙事与展陈设计
# ============================================================================

@dataclass
class NarrativeDesign:
    """叙事设计方案"""
    archive_title: str = ""
    subtitle: str = ""
    hook: str = ""                          # 开篇钩子（吸引读者）
    narrative_arc: str = ""                 # 叙事弧线描述
    key_themes: List[str] = field(default_factory=list)
    emotional_tone: str = ""                # 情感基调
    target_audience: str = "general"


@dataclass
class VisualScheme:
    """视觉设计方案"""
    style_name: str = "classic_archive"     # 风格名称
    primary_color: str = "#8B4513"
    secondary_color: str = "#D2B48C"
    background: str = "#FAF8F5"
    accent: str = "#C41E3A"
    font_family: str = "serif"
    layout_type: str = "exhibition"         # exhibition | timeline | portrait | gallery


# ============================================================================
# 项目整体
# ============================================================================

@dataclass
class ArchiveProject:
    """一个完整的档案数字叙事项目"""
    project_id: str = ""
    theme: str = "custom"
    title: str = ""
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 原始材料
    sources: List[SourceMaterial] = field(default_factory=list)

    # 结构化档案数据
    overview: str = ""
    timeline: List[TimelineEvent] = field(default_factory=list)
    figures: List[ArchiveEntity] = field(default_factory=list)
    locations: List[ArchiveEntity] = field(default_factory=list)
    objects: List[ArchiveEntity] = field(default_factory=list)
    key_stats: Dict[str, Any] = field(default_factory=dict)
    spirit: Dict[str, Any] = field(default_factory=dict)

    # 媒体
    images: List[MediaAsset] = field(default_factory=list)

    # 设计与叙事
    narrative: Optional[NarrativeDesign] = None
    visual: Optional[VisualScheme] = None

    # 输出
    html_path: str = ""
    exhibition_3d_path: str = ""
    output_dir: str = ""

    def to_dict(self) -> Dict:
        """导出为字典（供 HTML/3D 生成器消费）"""
        return {
            "archive_title": self.title,
            "subtitle": self.narrative.subtitle if self.narrative else "",
            "overview": self.overview,
            "timeline": [
                {"date": t.date, "event": t.event, "location": t.location,
                 "description": t.description, "image": t.image}
                for t in self.timeline
            ],
            "figures": [
                {"name": f.name, "role": f.role, "bio": f.bio,
                 "contribution": f.contribution, "image": f.image}
                for f in self.figures
            ],
            "spirit": self.spirit,
            "key_stats": self.key_stats,
            "gallery": [
                {"src": img.local_path, "caption": img.description,
                 "alt": img.alt_text, "era": img.era,
                 "source_url": img.remote_url}
                for img in self.images
            ],
            "sources": [
                {"title": s.title, "url": s.url, "credibility": s.credibility}
                for s in self.sources
            ],
            "route_summary": self.narrative.narrative_arc if self.narrative else "",
        }
