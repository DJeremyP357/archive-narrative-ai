"""
WebGalleryAgent — HTML 档案叙事网站生成 Agent

在 SmartOrchestrator 架构中作为输出层工具模块，
委托到 utils/html_builder.py 的 build_archive_website()。
"""

# 本模块作为输出层工具模块，委托到 utils/html_builder.py

import os
import json
from typing import Any, Dict, List, Optional
from datetime import datetime

from core.base_agent import BaseAgent, TaskResult


class WebGalleryAgent(BaseAgent):
    """档案数字叙事 HTML 网站生成"""

    def __init__(self):
        super().__init__(
            name="WebGalleryAgent",
            description="生成单页式 HTML 档案数字叙事展示",
        )
        self.output_dir = "outputs/web"

    async def execute(self, task_input: Dict[str, Any]) -> TaskResult:
        """兼容 V1 DAG 调用入口"""
        try:
            data = task_input.get("data", {}) or {}
            images = task_input.get("gallery_images", []) or []
            theme = task_input.get("theme", "custom")
            output_dir = task_input.get("output_dir", self.output_dir)
            os.makedirs(output_dir, exist_ok=True)

            html_path = self.run(data, gallery_images=images, theme=theme, output_dir=output_dir)
            return TaskResult(
                success=True,
                data={
                    "html_path": html_path,
                    "preview_url": f"file://{html_path}",
                },
                metadata={"agent": self.name, "theme": theme},
            )
        except Exception as e:
            return TaskResult(
                success=False,
                error=str(e),
                metadata={"agent": self.name},
            )

    def run(
        self,
        archive_data: Dict[str, Any],
        gallery_images: Optional[List[Any]] = None,
        theme: str = "custom",
        output_dir: Optional[str] = None,
    ) -> str:
        """
        生成单页 HTML 网站并写入磁盘

        Args:
            archive_data: 结构化档案数据（含 archive_title, overview, timeline, figures, spirit 等）
            gallery_images: 本地图片路径或 dict 列表
            theme: 专题类型（预定义专题键名或 custom）
            output_dir: 输出目录

        Returns:
            写入的 index.html 绝对路径
        """
        from utils.html_builder import build_archive_website  # 延迟导入

        out = output_dir or self.output_dir
        os.makedirs(out, exist_ok=True)

        html = build_archive_website(
            archive_data,
            gallery_images=gallery_images or [],
            theme=theme,
        )
        html_path = os.path.abspath(os.path.join(out, "index.html"))
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        return html_path
