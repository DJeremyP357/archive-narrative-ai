import html, json, os, re
from datetime import datetime
from typing import Any, Dict, List
from core.base_agent import BaseAgent, TaskResult

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

def _load_template(name: str) -> str:
    path = os.path.join(_TEMPLATES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class Exhibition3DAgent(BaseAgent):
    """开放大厅式 Three.js 档案展厅 (内联 PointerLockControls)"""

    def __init__(self):
        super().__init__(name="Exhibition3DAgent", description="Three.js 3D 展厅")
        self.output_dir = "outputs/3d_exhibition"

    async def run(self, task_input): return await self.execute(task_input)

    async def execute(self, task_input):
        try:
            initial = task_input.get("initial_input", {}) or {}
            deps = task_input.get("dependencies", {}) or {}
            self.output_dir = initial.get("output_dir", os.path.join("outputs", initial.get("archive_type", "custom")))
            os.makedirs(self.output_dir, exist_ok=True)
            ad = self._resolve_archive_data(initial, deps)
            images = self._resolve_images(deps, ad)
            exhibits = self._build_exhibits(ad, images)
            rooms = self._build_rooms(exhibits)
            html_text = self._build_html(ad, rooms, exhibits)
            html_path = os.path.join(self.output_dir, "exhibition_3d.html")
            with open(html_path, "w", encoding="utf-8") as f: f.write(html_text)
            meta = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "html_path": html_path,
                    "exhibit_count": len(exhibits), "room_count": len(rooms)}
            with open(os.path.join(self.output_dir, "exhibition_3d_metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return TaskResult(success=True, data={"html_path": html_path, "metadata": meta}, metadata={"agent": self.name})
        except Exception as e:
            import traceback; traceback.print_exc()
            return TaskResult(success=False, error=f"{str(e)}\n{traceback.format_exc()}", metadata={"agent": self.name})

    def _resolve_archive_data(self, initial, deps):
        aw = deps.get("ArchiveAnalysisAgent", {})
        analysis = aw.get("data") if isinstance(aw, dict) else {}
        if not isinstance(analysis, dict): analysis = {}
        ad = analysis.get("archive_data") if isinstance(analysis.get("archive_data"), dict) else None
        if not ad: ad = analysis if analysis.get("archive_title") else {}
        name = initial.get("archive_name") or initial.get("title") or ""
        title = ad.get("archive_title") or ""
        # 用户指定的档案名称优先级最高（LLM 常返回泛化标题）
        if name:
            title = name
        elif title in ("档案数字叙事", "档案数字展厅", "档案", ""):
            title = "档案数字展厅"
        subtitle = ad.get("subtitle") or initial.get("subtitle") or ""
        if not subtitle:
            subtitle = f"走近{name}" if name else "沉浸式档案空间"
        return {
            "archive_title": title or "档案数字展厅",
            "subtitle": subtitle,
            "overview": ad.get("overview") or analysis.get("overview") or "",
            "timeline": ad.get("timeline") if isinstance(ad.get("timeline"), list) else [],
            "figures": ad.get("figures") if isinstance(ad.get("figures"), list) else [],
            "spirit": ad.get("spirit") if isinstance(ad.get("spirit"), dict) else {},
            "downloaded_images": analysis.get("downloaded_images") if isinstance(analysis.get("downloaded_images"), list) else [],
        }

    def _resolve_images(self, deps, ad):
        imgs = list(ad.get("downloaded_images", []))
        cw = deps.get("WebCrawlerAgent", {})
        cr = cw.get("data") if isinstance(cw, dict) else {}
        if isinstance(cr, dict): imgs.extend(cr.get("downloaded_images", []))
        valid, seen = [], set()
        for img in imgs:
            if not isinstance(img, dict): continue
            rel = img.get("relative_path") or img.get("local_path") or ""
            if not rel or rel in seen: continue
            seen.add(rel); valid.append(img)
        return valid

    def _build_exhibits(self, ad, images):
        exhibits, used_imgs = [], set()
        
        def _chinese_ngrams(text, min_len=2, max_len=4):
            """提取中文n-gram关键词"""
            text = re.sub(r'[^\u4e00-\u9fff\w]', '', text)
            ngrams = set()
            for n in range(min_len, min(max_len + 1, len(text) + 1)):
                for i in range(len(text) - n + 1):
                    ngrams.add(text[i:i+n])
            return ngrams

        # 收集所有主要人物名称，用于图片排斥过滤（避免张冠李戴）
        all_figure_names = []
        for fig in (ad.get("figures", []) or []):
            if isinstance(fig, dict) and fig.get("name"):
                all_figure_names.append(fig.get("name").strip())

        def find_best_image(keywords, exclude=set(), reject_names=None, min_score=0):
            """根据关键词找到最匹配的图片（双管齐下：上下文+VL描述+中文n-gram匹配）
            reject_names: 排斥名称列表，若图片描述中包含排斥名称则直接拒绝（避免人物错配）
            min_score: 最低匹配分数，低于此值视为不匹配（避免低置信度硬匹配）
            """
            if not images: return ""
            keywords = keywords.lower() if keywords else ""
            best_match, best_score = None, -1
            # 提取关键词n-gram
            kw_ngrams = _chinese_ngrams(keywords)
            # 提取排斥名称n-gram
            reject_ngrams = set()
            if reject_names:
                for rn in reject_names:
                    if rn and rn != keywords.strip():
                        reject_ngrams.update(_chinese_ngrams(rn.lower()))
            for j, img in enumerate(images):
                if j in exclude or j in used_imgs: continue
                pic = img.get("relative_path") or img.get("local_path") or ""
                if not pic: continue
                # 计算匹配分数
                score = 0
                # 方法2：VL视觉模型描述
                img_text = (img.get("description", "") + " " + img.get("alt", "") + " " + img.get("title", "")).lower()
                img_ngrams = _chinese_ngrams(img_text)
                # n-gram交集匹配
                overlap = kw_ngrams & img_ngrams
                for ng in overlap:
                    score += len(ng)  # 长n-gram权重更高
                # 方法1：网页上下文匹配（权重更高，因为上下文直接说明图片与什么内容相关）
                img_context = (img.get("context", "") or "").lower()
                if img_context:
                    ctx_ngrams = _chinese_ngrams(img_context)
                    ctx_overlap = kw_ngrams & ctx_ngrams
                    for ng in ctx_overlap:
                        score += len(ng) * 2  # 上下文匹配权重加倍
                # 路径匹配
                for ng in kw_ngrams:
                    if len(ng) >= 2 and ng in pic.lower():
                        score += len(ng)
                # 排斥过滤：若图片描述中包含其他主要人物名称，直接拒绝
                if reject_ngrams and img_ngrams:
                    reject_overlap = reject_ngrams & img_ngrams
                    if reject_overlap:
                        # 如果明确包含排斥名称（如南仁东），分数归零
                        for rng in reject_overlap:
                            if len(rng) >= 2:
                                score = -999
                                break
                if score > best_score:
                    best_score = score
                    best_match = j
            # 必须满足最低分数门槛，否则宁可空缺也不要硬配
            if best_match is not None and best_score >= min_score:
                used_imgs.add(best_match)
                img = images[best_match]
                return img.get("relative_path") or img.get("local_path") or ""
            return ""
        
        archive_title = ad.get("archive_title", "")
        ov = ad.get("overview", "")
        if ov: 
            exhibits.append({"id": "overview", "type": "archive_document", "title": "档案总览", "date": "概述", "description": self._clip(ov, 280), "image": find_best_image(archive_title, min_score=2), "room": "序厅"})
        for i, t in enumerate(ad.get("timeline", []) or []):
            if not isinstance(t, dict): continue
            keywords = t.get("event", "") + " " + t.get("description", "")
            exhibits.append({"id": f"tl-{i}", "type": "event_display", "title": t.get("event") or t.get("title", f"节点{i+1}"), "date": str(t.get("date") or t.get("time") or ""), "description": self._clip(t.get("description") or t.get("desc") or "", 280), "image": t.get("image") or find_best_image(keywords, min_score=2), "room": "时间线展区"})
        for i, f in enumerate(ad.get("figures", []) or []):
            if not isinstance(f, dict): continue
            fig_name = f.get("name", "").strip()
            keywords = fig_name + " " + f.get("role", "")
            # 人物图片：排斥其他人物名称，最低匹配分设为3（要求较明确的匹配）
            other_names = [n for n in all_figure_names if n != fig_name]
            upstream_img = f.get("image")
            if upstream_img:
                # 将上游图片路径规范化：提取文件名并加上 images/ 前缀
                img_filename = os.path.basename(upstream_img.replace("\\", "/"))
                assigned_img = f"images/{img_filename}" if img_filename else ""
                # 将上游已分配的图片标记为已占用，防止后续人物重复匹配
                for j, img in enumerate(images):
                    pic = img.get("relative_path") or img.get("local_path") or img.get("src") or ""
                    if pic == upstream_img:
                        used_imgs.add(j)
                        break
            else:
                assigned_img = find_best_image(keywords, reject_names=other_names, min_score=3)
            exhibits.append({"id": f"fig-{i}", "type": "person_portrait", "title": fig_name or f"人物{i+1}", "date": f.get("role", "人物"), "description": self._clip(f.get("bio") or f.get("description") or "", 260), "image": assigned_img, "room": "人物档案区"})
        sp = ad.get("spirit") or {}
        if isinstance(sp, dict) and sp.get("content"):
            exhibits.append({"id": "spirit", "type": "archive_document", "title": sp.get("title", "核心价值"), "date": "精神传承", "description": self._clip(sp.get("content", ""), 300), "image": find_best_image(sp.get("title", ""), min_score=2), "room": "精神总结区"})
        # 剩余图片作为独立影像展品
        for i, img in enumerate(images):
            if i in used_imgs: continue
            pic = img.get("relative_path") or img.get("local_path") or ""
            if not pic: continue
            ver = img.get("verification", {})
            exhibits.append({"id": f"img-{i}", "type": "archive_photo", "title": img.get("description") or img.get("alt") or f"影像{i+1}", "date": "影像档案", "description": ver.get("description") or img.get("description") or "档案影像", "image": pic, "room": "影像档案区"})
            used_imgs.add(i)
        if not exhibits:
            exhibits = [{"id": "fb", "type": "archive_document", "title": ad.get("archive_title", "展厅"), "date": "ARCHIVE", "description": "暂无展品数据", "image": "", "room": "序厅"}]
        return exhibits[:32]

    def _build_rooms(self, exhibits):
        # 开放式大厅：只有一个大厅，所有展品都在其中
        return [{"name": "主展厅", "position": [0, 0, 0], "size": [60, 24, 40], "type": "hall", "exhibits": exhibits}]

    def _build_html(self, ad, rooms, exhibits):
        title = html.escape(ad.get("archive_title", "档案数字展厅"), quote=True)
        subtitle = html.escape(ad.get("subtitle", "沉浸式档案空间"), quote=True)
        E = json.dumps(exhibits, ensure_ascii=False).replace("<", "\\u003c")

        css = _load_template("exhibition_3d.css")

        js_preamble = (
            "window.onerror=function(msg,url,line){document.getElementById('loading').innerHTML='<div style=color:#e74c3c;padding:40px;font-size:16px>展厅加载出错: '+msg+' (行'+line+')</div>';return false};"
            "window.addEventListener('unhandledrejection',function(e){document.getElementById('loading').innerHTML='<div style=color:#e74c3c;padding:40px;font-size:16px>Promise错误: '+(e.reason||e)+'</div>'});"
            "var exhibitsData=" + E + ";"
        )

        js_template = _load_template("exhibition_3d.js")
        # 替换动态内容占位符
        js_template = js_template.replace("/* PREAMBLE_PLACEHOLDER */", js_preamble)
        js_template = js_template.replace(
            "/* TITLE_BAND_PLACEHOLDER */",
            "var titleBand=new THREE.Mesh(new THREE.PlaneGeometry(56,2.5),new THREE.MeshBasicMaterial({color:0x8c1d18,side:THREE.DoubleSide}));titleBand.position.set(0,8.5,-19.96);group.add(titleBand);"
        )
        js_template = js_template.replace(
            "/* GOLD_BAND_PLACEHOLDER */",
            "var goldBand=new THREE.Mesh(new THREE.PlaneGeometry(56,.15),new THREE.MeshBasicMaterial({color:0xb78a2f,side:THREE.DoubleSide}));goldBand.position.set(0,7.15,-19.95);group.add(goldBand);"
        )
        js_template = js_template.replace(
            "/* TITLE_MESH_PLACEHOLDER */",
            "var titleTex=mkTex('" + title + "','" + subtitle + "',1024,256);var titleMesh=new THREE.Mesh(new THREE.PlaneGeometry(18,3.5),new THREE.MeshBasicMaterial({map:titleTex,transparent:true}));titleMesh.position.set(0,8.2,-19.9);group.add(titleMesh);"
        )
        js_template = js_template.replace(
            "/* SUB_MESH_PLACEHOLDER */",
            "var subTex=mkTex('" + subtitle + "','',1024,128);var subMesh=new THREE.Mesh(new THREE.PlaneGeometry(12,1.2),new THREE.MeshBasicMaterial({map:subTex,transparent:true}));subMesh.position.set(0,6.5,-19.88);group.add(subMesh);"
        )
        js_main = js_template

        return (
            '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1.0">\n'
            '<title>' + title + ' · 虚拟档案展厅</title>\n<style>' + css + '</style>\n</head>\n<body>\n'
            '<div id="loading"><div class="ring"></div><p>正在构建元宇宙档案展厅</p><div class="sub">加载 Three.js 引擎与 3D 资产中...</div></div>\n'
            '<div id="hint"><h2>' + title + ' · 档案展厅</h2><p>点击屏幕进入沉浸式档案空间<br>使用 <b style="color:#8c1d18">W A S D</b> 或 <b style="color:#8c1d18">方向键</b> 移动<br>移动鼠标控制视角转向<br>墙面直接展示档案概要 · 走近展柜查看详情</p><div class="btn">点击进入展厅</div></div>\n'
            '<div id="header"><h1>' + title + ' · 档案展厅</h1><p>' + subtitle + '</p></div>\n'
            '<div id="crosshair"></div>\n'
            '<div id="ctls"><kbd>W</kbd> <kbd>A</kbd> <kbd>S</kbd> <kbd>D</kbd> 移动 · 鼠标转向 · <kbd>ESC</kbd> 释放鼠标</div>\n'

            '<div id="tooltip"></div>\n'
            '<div id="modal"><h3 id="modal-title"></h3><div class="date" id="modal-date"></div><img id="modal-img" alt=""><p id="modal-desc"></p><button type="button" onclick="closeModal(event)">关闭</button></div>\n'
            '<div id="cv"></div>\n'
            '<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>\n'
            '<script>\n' + js_preamble + '\n' + js_main + '\n</script>\n'
            '</body>\n</html>'
        )

    @staticmethod
    def _clip(t, n):
        s = str(t or "").strip()
        return s[:n] + ("..." if len(s) > n else "")
