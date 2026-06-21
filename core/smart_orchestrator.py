import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.llm_client import MultiLLMRouter
from agents.orchestrator.planner_agent import PlannerAgent
from agents.input.smart_input_agent import SmartInputAgent
from agents.input.web_crawler_agent import WebCrawlerAgent
from agents.processing.smart_analysis_agent import SmartAnalysisAgent
from agents.output.smart_output_agent import SmartOutputAgent
from utils.crawl_helpers import (
    analyze_archive_with_llm,
    collect_crawl_text,
    collect_image_urls,
    collect_image_candidates,
    download_crawl_images,
    build_url_to_local,
    match_image_for_label,
    analyze_and_categorize_images,
    enrich_image_contexts,
    engineer_queries,
    build_crawl_targets_from_queries,
)

CHECKPOINT_DIR = "outputs/_checkpoints"


def _save_checkpoint(checkpoint_key: str, step: int, intermediate_results: Dict, plan: Dict):
    """保存检查点：每个Agent完成后调用"""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    # 只保存可序列化的数据
    safe_results = {}
    for k, v in intermediate_results.items():
        if k.startswith("_"):
            continue
        try:
            json.dumps(v, ensure_ascii=False, default=str)
            safe_results[k] = v
        except (TypeError, ValueError):
            safe_results[k] = str(v)[:500]
    checkpoint = {
        "step": step,
        "plan": plan,
        "intermediate_results": safe_results,
        "timestamp": datetime.now().isoformat(),
    }
    path = os.path.join(CHECKPOINT_DIR, f"{checkpoint_key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, default=str)
    return path


def _load_checkpoint(checkpoint_key: str) -> Optional[Dict]:
    """加载检查点"""
    path = os.path.join(CHECKPOINT_DIR, f"{checkpoint_key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _clear_checkpoint(checkpoint_key: str):
    """清除检查点"""
    path = os.path.join(CHECKPOINT_DIR, f"{checkpoint_key}.json")
    if os.path.exists(path):
        os.remove(path)
class SmartOrchestrator:
  def __init__(self, llm_router: MultiLLMRouter):
    self.llm_router = llm_router
    self.planner = PlannerAgent(llm_router)
    self.input_agent = SmartInputAgent(llm_router)
    self.web_crawler = WebCrawlerAgent()
    self.analysis_agent = SmartAnalysisAgent(llm_router)
    self.output_agent = SmartOutputAgent(llm_router)
    self._execution_log: List[Dict] = []

  async def execute(
    self, user_request: str, context: Dict = None, plan: Dict = None
  ) -> Dict[str, Any]:
    start_time = time.time()
    self._execution_log = []
    context = dict(context or {})

    # ── Checkpoint 恢复 ──
    checkpoint_key = context.get("checkpoint_key", "")
    resume_from_step = 0
    saved_intermediate = {}
    saved_plan = None

    if checkpoint_key:
      cp = _load_checkpoint(checkpoint_key)
      if cp:
        resume_from_step = cp.get("step", 0)
        saved_intermediate = cp.get("intermediate_results", {})
        saved_plan = cp.get("plan")
        self._log("orchestrator", "resuming",
          f"检测到检查点，从步骤{resume_from_step + 1}恢复（已完成{resume_from_step}步）")

    self._log("orchestrator", "planning", f"开始规划: {user_request[:100]}")

    if plan is None:
      if saved_plan and resume_from_step > 0:
        plan = saved_plan
        self._log("planner", "plan_restored", "从检查点恢复工作流计划")
      else:
        plan = await self.planner.plan(user_request, context)
    self._log("planner", "plan_created", json.dumps(plan, ensure_ascii=False)[:500])

    self._normalize_output_keys(plan)

    intermediate_results: Dict[str, Any] = {}
    intermediate_results.update(context)
    # 恢复之前保存的中间结果
    if saved_intermediate:
      intermediate_results.update(saved_intermediate)

    workflow = plan.get("workflow", [])
    self._apply_context_constraints(workflow, context)

    for step_info in workflow:
      step = step_info.get("step", 0)
      agent_name = step_info.get("agent", "")
      if agent_name not in self._valid_agent_names():
        self._log(agent_name, "skipped", f"未知Agent，跳过步骤{step}")
        continue

      # ── 跳过已完成的步骤 ──
      if step <= resume_from_step and saved_intermediate:
        output_key = step_info.get("output_key") or self._default_output_key(agent_name)
        if output_key in saved_intermediate or agent_name in saved_intermediate:
          self._log(agent_name, "skipped", f"步骤{step}已完成（从检查点恢复），跳过")
          continue

      task_desc = step_info.get("task", "")
      input_from = step_info.get("input_from", [])
      output_key = step_info.get("output_key") or self._default_output_key(agent_name)

      self._log(agent_name, "started", f"步骤{step}: {task_desc[:100]}")

      agent_context = {"_context": context}
      for dep in input_from:
        if dep in intermediate_results:
          agent_context[dep] = intermediate_results[dep]
        else:
          canonical_key = self._default_output_key(dep)
          if canonical_key in intermediate_results and canonical_key != dep:
            agent_context[dep] = intermediate_results[canonical_key]
      for key, val in intermediate_results.items():
        if not key.startswith("_"):
          agent_context[key] = val

      try:
        result = await self._execute_agent(agent_name, task_desc, agent_context)

        if result.get("success"):
          payload = result.get("data") or result.get("answer", {})
          intermediate_results[output_key or agent_name] = payload
          self._log(agent_name, "completed", f"步骤{step}完成")
        else:
          self._log(agent_name, "failed", result.get("error", "未知错误"))
          new_plan = await self.planner.replan(
            plan, step_info, result.get("error", ""), intermediate_results
          )
          existing_agents = {s.get("agent") for s in workflow}
          remaining = [
            s for s in new_plan.get("workflow", [])
            if s.get("step", 0) > step and s.get("agent") not in existing_agents
          ]
          workflow.extend(remaining)

      except Exception as e:
        self._log(agent_name, "error", str(e))
        intermediate_results[output_key or agent_name] = {"error": str(e)}

      # ── 每步完成后保存检查点 ──
      if checkpoint_key:
        _save_checkpoint(checkpoint_key, step, intermediate_results, plan)
        self._log("orchestrator", "checkpoint", f"步骤{step}检查点已保存")

    elapsed = time.time() - start_time
    self._log("orchestrator", "completed", f"全部执行完成，耗时{elapsed:.1f}秒")

    # 添加统一的 outputs 字段（去重）
    outputs = []
    _seen_paths = set()

    def _output_url(path: str) -> str:
      normalized = path.replace(chr(92), "/")
      if "outputs/" in normalized:
        normalized = normalized.split("outputs/", 1)[1]
      return f"/outputs/{normalized}"

    def extract_outputs(obj):
      if not obj or not isinstance(obj, dict):
        return
      val = obj.get("html_path")
      if val and val not in _seen_paths:
        _seen_paths.add(val)
        norm = str(val).replace(chr(92), "/").lower()
        out_type = "3D 展厅" if ("exhibition_3d" in norm or "3d" in norm) else "HTML 网站"
        outputs.append({"type": out_type, "path": val, "url": _output_url(val)})
      for k, v in obj.items():
        if k != "html_path" and isinstance(v, dict):
          extract_outputs(v)

    extract_outputs(intermediate_results)

    return {
      "success": True,
      "plan": plan,
      "results": intermediate_results,
      "outputs": outputs,
      "execution_log": self._execution_log,
      "elapsed": round(elapsed, 2),
    }

  async def _execute_agent(
    self, agent_name: str, task: str, context: Dict
  ) -> Dict[str, Any]:
    base_ctx = context.get("_context", {})

    if agent_name == "WebCrawlerAgent":
      return await self._run_web_crawler(task, context, base_ctx)

    if agent_name in ("ArchiveAnalysisAgent", "SmartAnalysisAgent"):
      return await self._run_archive_analysis(task, context, base_ctx)

    if agent_name == "WebGalleryAgent":
      return await self._run_web_gallery(task, context, base_ctx)

    if agent_name == "DocumentParserAgent":
      files = base_ctx.get("files") or context.get("files") or []
      file_infos = [{"path": f, "type": "auto"} if isinstance(f, str) else f for f in files]
      if not file_infos:
        return {"success": False, "error": "未提供待解析文件", "data": None}
      result = await self.input_agent._parser.execute({"files": file_infos})
      return {"success": result.success, "data": result.data, "error": result.error, "answer": result.data}

    # HTML 网站 (WebGalleryAgent) + 3D 展厅 (Exhibition3DAgent) + 文档解析
    # 其它能力（PPT/视频/Word/微信/NeRF）已废弃
    legacy_outputs = {
      "Exhibition3DAgent": "agents.output.exhibition_3d_agent",
    }
    if agent_name in legacy_outputs:
      return await self._run_legacy_agent(agent_name, legacy_outputs[agent_name], task, context, base_ctx)

    if agent_name == "SmartOutputAgent":
      return await self.output_agent.run(task, {k: v for k, v in context.items() if k != "_context"})

    react_map = {
      "DocumentParserAgent": self.input_agent,
      "SmartInputAgent": self.input_agent,
    }

    agent = react_map.get(agent_name)
    if not agent:
      return {"success": False, "error": f"Agent '{agent_name}' 不存在"}

    full_task = task
    ctx_for_llm = {k: v for k, v in context.items() if k != "_context"}
    if ctx_for_llm:
      full_task += (
        f"\n\n上游数据：{json.dumps(ctx_for_llm, ensure_ascii=False, default=str)[:3000]}"
      )

    return await agent.run(full_task, ctx_for_llm)

  async def _run_web_crawler(
    self, task: str, context: Dict, base_ctx: Dict
  ) -> Dict[str, Any]:
    targets = (
      base_ctx.get("crawl_targets")
      or context.get("crawl_targets")
      or []
    )
    archive_type = base_ctx.get("archive_type", "custom")
    output_dir = base_ctx.get("output_dir", f"outputs/{archive_type}")
    archive_name = base_ctx.get("archive_name", "")
    relevance_keywords = base_ctx.get("relevance_keywords") or []
    time_anchors = base_ctx.get("time_anchors") or []

    # ---- 查询工程：自动生成多源搜索目标 ----
    # 如果用户没提供 crawl_targets，用查询工程引擎自动生成
    if not targets and archive_name:
      queries = engineer_queries(
        archive_name=archive_name,
        keywords=relevance_keywords,
        time_anchors=time_anchors,
      )
      targets = build_crawl_targets_from_queries(queries, relevance_keywords)
      self._log("WebCrawlerAgent", "query_engineering",
        f"查询工程生成 {len(targets)} 个搜索目标")

    if not targets:
      return {"success": False, "error": "未配置 crawl_targets 且无法自动生成搜索目标"}

    def _log(msg, level="INFO"):
      self._log("WebCrawlerAgent", level.lower(), msg)

    crawled = await self.web_crawler.crawl_targets(targets, log_callback=_log)

    # 下载阶段不做 VL 验证（节省 token），后续 analyze_and_categorize_images 统一分析
    downloaded = await download_crawl_images(
      crawled,
      output_dir,
      max_images=base_ctx.get("max_images", 40),
      verify_keywords=None,  # 关闭逐张 VL 验证，token 消耗减半
      theme=archive_name,
    )

    all_crawled_images = []
    for r in crawled:
      if r.get("success"):
        all_crawled_images.extend(r.get("images", []))

    image_candidates = collect_image_candidates(crawled, relevance_keywords=relevance_keywords)

    # 双管齐下之方法1：为缺少上下文的图片补充来源页上下文
    image_candidates = await enrich_image_contexts(image_candidates, max_pages=8)

    # 构建来源列表（支撑证据链）
    sources = []
    for r in crawled:
        if r.get("success"):
            sources.append({
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "domain": r.get("url", "").split("/")[2] if "//" in r.get("url", "") else "",
                "text_length": r.get("text_length", 0),
                "images_count": len(r.get("images", [])),
                "method": r.get("method", "direct"),
            })

    payload = {
      "crawled": crawled,
      "crawled_text": collect_crawl_text(crawled),
      "downloaded_images": downloaded,
      "url_to_local": build_url_to_local(downloaded),
      "image_urls": collect_image_urls(crawled, relevance_keywords=relevance_keywords),
      "image_candidates": image_candidates[:120],
      "crawled_images_meta": all_crawled_images[:50],
      "raw_path": output_dir,
      "success_count": sum(1 for r in crawled if r.get("success")),
      "search_engines_used": list(set(t.get("method", "direct") for t in targets)),
      "sources": sources,  # 来源列表
    }

    # 保存爬取原始资料到 output 目录，方便查阅和复用
    try:
      crawl_save_path = os.path.join(output_dir, "crawl_data.json")
      crawl_save = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "archive_name": archive_name,
        "sources": sources,
        "crawled_text": collect_crawl_text(crawled),
        "crawled_pages": [
          {"url": r.get("url", ""), "title": r.get("title", ""), "text_length": r.get("text_length", 0),
           "images_count": len(r.get("images", [])), "method": r.get("method", "direct"),
           "success": r.get("success", False)}
          for r in crawled if r.get("success")
        ],
        "downloaded_images": [
          {"path": img.get("relative_path", ""), "description": img.get("description", ""),
           "alt": img.get("alt", ""), "source_page": img.get("source_page", img.get("url", ""))}
          for img in downloaded if isinstance(img, dict)
        ],
      }
      with open(crawl_save_path, "w", encoding="utf-8") as f:
        json.dump(crawl_save, f, ensure_ascii=False, indent=2)
    except Exception:
      pass

    await self.web_crawler.close()
    return {"success": True, "data": payload, "answer": payload}

  async def _run_archive_analysis(
    self, task: str, context: Dict, base_ctx: Dict
  ) -> Dict[str, Any]:
    archive_type = base_ctx.get("archive_type", "custom")

    crawled_data = context.get("crawled_data") or {}
    crawled_text = crawled_data.get("crawled_text", "") if isinstance(crawled_data, dict) else str(crawled_data)[:50000]
    parsed_data = context.get("parsed_files") or {}
    parsed_files = parsed_data.get("parsed_files", []) if isinstance(parsed_data, dict) else []
    parsed_text_parts = []
    document_images = []
    document_sources = []
    for item in parsed_files:
      if not isinstance(item, dict):
        continue
      file_path = item.get("file", "")
      label = os.path.basename(file_path) if file_path else "上传材料"
      content = item.get("content", "")
      if content:
        parsed_text_parts.append(f"\n\n=== 上传材料: {label} ===\n{content[:20000]}")
      for table in item.get("table_data", []) if isinstance(item.get("table_data"), list) else []:
        parsed_text_parts.append(f"\n--- 表格: {label} #{table.get('index', '')} ---\n{json.dumps(table.get('rows', []), ensure_ascii=False)[:8000]}")
      for img in item.get("embedded_images", []) if isinstance(item.get("embedded_images"), list) else []:
        if isinstance(img, dict):
          document_images.append({
            "relative_path": img.get("local_path", ""),
            "local_path": img.get("local_path", ""),
            "description": img.get("filename", "文档内嵌图片"),
            "source_file": file_path,
            "verified": True,
          })
      if file_path:
        document_sources.append({"url": file_path, "title": label, "domain": "用户上传", "method": "document"})
    parsed_text = "".join(parsed_text_parts)
    combined_text = (crawled_text + parsed_text)[:80000]

    # 所有专题都优先使用通用 LLM 档案分析，legacy Agent 仅作为兜底
    keywords = base_ctx.get("relevance_keywords") or base_ctx.get("keywords") or []
    archive_name = base_ctx.get("archive_name", "档案")
    if not keywords:
      keywords = [archive_name]

    archive_json: Dict[str, Any] = {}
    source: str = "llm"
    try:
      archive_json, source = await analyze_archive_with_llm(
        self.llm_router,
        combined_text,
        keywords,
        archive_type=archive_type,
        archive_name=archive_name,
      )
      analysis_source = source or "llm"
    except Exception:
      legacy = await self._run_legacy_agent(
        "ArchiveAnalysisAgent",
        "agents.processing.archive_analysis_agent",
        task,
        context,
        base_ctx,
      )
      if legacy.get("success"):
        archive_json = legacy.get("data", {}) or {}
        analysis_source = "legacy_agent"
        source = "legacy_agent"
      else:
        return legacy

    downloaded = list(document_images)
    url_to_local = build_url_to_local(downloaded)
    if isinstance(crawled_data, dict):
      downloaded.extend(crawled_data.get("downloaded_images", []))
      url_to_local.update(crawled_data.get("url_to_local", build_url_to_local(downloaded)))

    crawled_images = crawled_data.get("crawled_images_meta", []) if isinstance(crawled_data, dict) else []

    # 路径 B 修复：无论 LLM JSON 解析是否成功，都强制调用 qwen3-vl-max 智能分类
    # 把这一步独立于 archive_json 来源，保证视觉模型一定有调用机会
    output_dir = base_ctx.get("output_dir", f"outputs/{archive_type}")
    try:
      image_analysis = await analyze_and_categorize_images(
        downloaded, archive_json, output_dir=output_dir, enable_vision=True
      )
    except Exception as e:
      print(f"[WARN] VL 图片分类失败（fallback 到关键词匹配）: {e}")
      image_analysis = {
        "categories": {"figures": [], "timeline": [], "gallery": [], "overview": []},
        "analyses": [],
        "method": "fallback",
        "error": str(e)[:200],
      }
    categories = image_analysis.get("categories", {})
    analyses = image_analysis.get("analyses", [])

    # 类型安全处理: LLM 返回的 figures/timeline 可能是字符串或字典，统一转为列表
    figures = archive_json.get("figures", [])
    if not isinstance(figures, list):
      figures = [figures] if isinstance(figures, dict) else []
    figures = [f for f in figures if isinstance(f, dict)]
    timeline_events = archive_json.get("timeline", [])
    if not isinstance(timeline_events, list):
      timeline_events = [timeline_events] if isinstance(timeline_events, dict) else []
    timeline_events = [ev for ev in timeline_events if isinstance(ev, dict)]

    # 用 VL 描述做语义匹配，而非按位置瞎分配
    # 为每张图片建立描述索引（合并 VL 分析、alt、验证信息）
    img_index = {}  # relative_path -> {description, alt, vl_tags, ...}
    for d in downloaded:
        if isinstance(d, dict) and d.get("relative_path"):
            ver = d.get("verification", {})
            img_index[d["relative_path"]] = {
                "alt": d.get("alt", ""),
                "desc": ver.get("description", d.get("alt", "")),
                "era": ver.get("era", ""),
                "content_type": ver.get("content_type", ""),
                "source_score": d.get("source_score", 0),
                "context": d.get("context", ""),  # 图片在原网页中的上下文
                "source_page": d.get("source_page", d.get("url", "")),
                "tags": [],  # 后面从 analyses 填充
            }
    # 把 VL analyses 中的 tags/description 也合并进来
    for ana in image_analysis.get("analyses", []):
        rel = ana.get("path", "")
        if rel in img_index:
            img_index[rel]["tags"] = [t.lower() for t in ana.get("tags", []) if isinstance(t, str)]
            if ana.get("description"):
                img_index[rel]["desc"] = img_index[rel]["desc"] + " " + ana["description"]

    # ── 相关性守卫：图片元数据必须包含 archive_name 或其核心关键词 ──
    # 防止完全不相关的图片进入语义匹配
    _archive_words = set(archive_name.lower().split())
    for _path in list(img_index.keys()):
        _info = img_index[_path]
        _meta = (_info["desc"] + " " + _info["alt"] + " " + _info["context"] + " "
                 + " ".join(_info["tags"])).lower()
        # 必须包含 archive_name（2字以上部分）或已通过 VL 验证
        _has_archive = any(w in _meta for w in _archive_words if len(w) >= 2)
        _has_vl_analysis = len(_info.get("tags", [])) > 0 or len(_info["desc"]) > 50
        if not _has_archive and not _has_vl_analysis:
            del img_index[_path]

    def _best_match(text: str, candidates: list, top_n: int = 1, used: set = None, min_score: float = 3.0, reject_names: list = None) -> list:
        """用关键词语义 + VL 描述 + 网页上下文匹配，从候选中找最佳图片。

        匹配策略（双管齐下）：
        1. 网页上下文匹配：图片在原网页中的上下文文字与搜索文本的相关性
        2. VL 视觉模型描述：图片的 VL 分析描述/alt/tags 与搜索文本的匹配
        3. 人名/专有名词权重更高
        4. 分数低于 min_score 的不返回（避免无关图片强行分配）
        5. reject_names: 排斥名称列表，若图片描述中明确包含排斥名称则拒绝（避免人物错配）
        """
        import re as _re
        text_lower = text.lower()
        # 提取关键词：中文词（2-8字）、英文单词、数字型号
        keywords = set()
        for m in _re.finditer(r'[\u4e00-\u9fff]{2,8}', text_lower):
            keywords.add(m.group())
        for m in _re.finditer(r'[a-z]+\d+[a-z]*|\d+', text_lower):
            kw = m.group()
            if len(kw) > 1:
                keywords.add(kw)
        for m in _re.finditer(r'[a-z]{3,}', text_lower):
            keywords.add(m.group())

        # 提取排斥名称关键词
        reject_keywords = set()
        if reject_names:
            for rn in reject_names:
                if rn and len(rn) >= 2:
                    reject_keywords.add(rn.lower())

        scored = []
        for path in candidates:
            if path not in img_index:
                continue
            if used and path in used:
                continue
            info = img_index[path]
            # VL 描述 + alt + tags
            desc = (info["desc"] + " " + info["alt"] + " " + " ".join(info["tags"])).lower()
            # 网页上下文（方法1：图片在原网页中的上下文文字）
            ctx = info.get("context", "").lower()

            # 排斥过滤：若图片描述/上下文中包含其他主要人物名称，直接拒绝
            if reject_keywords:
                meta = desc + " " + ctx
                if any(rk in meta for rk in reject_keywords):
                    continue

            score = 0
            for kw in keywords:
                # VL 描述匹配
                cnt = desc.count(kw)
                if cnt:
                    weight = 3 if (_re.search(r'[\u4e00-\u9fff]', kw) or _re.search(r'\d', kw)) else 1
                    score += cnt * weight
                # 网页上下文匹配（权重更高，因为上下文直接说明图片与什么内容相关）
                ctx_cnt = ctx.count(kw)
                if ctx_cnt:
                    weight = 4 if (_re.search(r'[\u4e00-\u9fff]', kw) or _re.search(r'\d', kw)) else 2
                    score += ctx_cnt * weight
            # source_score 微小加成
            score += info.get("source_score", 0) * 0.5
            # 只保留分数达标的候选
            if score >= min_score:
                scored.append((score, path))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:top_n]]

    used_images = set()
    # 收集所有主要人物名称，用于排斥过滤（避免张冠李戴）
    all_figure_names = [fg.get("name", "").strip() for fg in figures if isinstance(fg, dict) and fg.get("name")]

    # ── 1. 为人物匹配肖像 ──
    portrait_candidates = categories.get("figures", []) + categories.get("gallery", [])
    for fg in figures:
        if not isinstance(fg, dict):
            continue
        name = fg.get("name", "").strip()
        bio = fg.get("bio", "")
        # 搜索文本仅使用人物姓名（避免 bio 中提及的其他人物名字干扰匹配）
        search_text = name[:300]
        # 排斥其他人物名称
        other_names = [n for n in all_figure_names if n != name]
        matches = _best_match(search_text, portrait_candidates, top_n=1, used=used_images, reject_names=other_names)
        if matches:
            fg["image"] = matches[0]
            used_images.add(matches[0])

    # ── 2. 为时间线事件匹配场景/历史图片 ──
    scene_candidates = (categories.get("timeline", []) +
                        categories.get("gallery", []) +
                        categories.get("overview", []))
    for ev in timeline_events:
        if not isinstance(ev, dict):
            continue
        event = ev.get("event", "")
        desc = ev.get("description", "")
        location = ev.get("location", "")
        search_text = f"{event} {location} {desc}"[:300]
        available = [p for p in scene_candidates if p not in used_images]
        matches = _best_match(search_text, available, top_n=1)
        if matches:
            ev["image"] = matches[0]
            used_images.add(matches[0])

    # 将安全化后的数据写回 archive_json，确保下游使用正确的列表类型
    archive_json["figures"] = figures
    archive_json["timeline"] = timeline_events

    # 为 overview/overview 区域分配文档类图片
    overview_images = categories.get("overview", [])
    if overview_images and "overview_image" not in archive_json:
      archive_json["overview_image"] = overview_images[0]

    # gallery 使用未被匹配的剩余图片
    remaining = [p for p in (categories.get("gallery", []) +
                 categories.get("overview", [])) if p not in used_images]
    if remaining and "gallery" not in archive_json:
      archive_json["gallery"] = [
        {"src": img, "caption": img_index.get(img, {}).get("desc", "")[:60],
         "alt": img_index.get(img, {}).get("alt", ""),
         "era": img_index.get(img, {}).get("era", "")}
        for img in remaining[:16]
      ]

    # 确保 archive_type 是字典格式（NarrativeDesignAgent 等下游期望 dict）
    archive_type_val = archive_json.get("archive_type", archive_name)
    if not isinstance(archive_type_val, dict):
      archive_type_val = {"type": str(archive_type_val), "name": archive_name or str(archive_type_val)}

    payload = {
      "archive_data": archive_json,
      "archive_type": archive_type_val,
      "timeline": archive_json.get("timeline", []),
      "entity_extraction": {
        "persons": [
          {"name": f.get("name", ""), "role": f.get("role", ""), "description": f.get("bio", ""), "image": f.get("image", "")}
          for f in archive_json.get("figures", []) if isinstance(f, dict)
        ],
        "locations": archive_json.get("locations", []),
        "objects": archive_json.get("objects", []),
        "events": archive_json.get("timeline", []),
      },
      "themes": archive_json.get("spirit", {}).get("keywords", []) if isinstance(archive_json.get("spirit"), dict) else [],
      "relationships": archive_json.get("relationships", []),
      "overview": archive_json.get("overview", ""),
      "key_stats": archive_json.get("key_stats", {}),
      "data_source": source,
      "downloaded_images": downloaded,
      "sources": (crawled_data.get("sources", []) if isinstance(crawled_data, dict) else []) + document_sources,
      "document_images": document_images,
      "parsed_files": parsed_files,
      "image_analysis": {
        "categories": categories,
        "analyses_count": len(analyses),
        "method": image_analysis.get("method", "unknown"),
      },
    }
    return {"success": True, "data": payload, "answer": payload}

  async def _run_legacy_agent(
    self, agent_name: str, module_path: str, task: str, context: Dict, base_ctx: Dict
  ) -> Dict[str, Any]:
    import importlib

    # 修复问题 #40: 添加动态导入异常处理
    try:
      mod = importlib.import_module(module_path)
      cls = getattr(mod, agent_name)
      agent = cls()
    except ImportError as e:
      return {"success": False, "error": f"无法导入模块 {module_path}: {str(e)}", "data": None}
    except AttributeError as e:
      return {"success": False, "error": f"模块 {module_path} 中找不到类 {agent_name}: {str(e)}", "data": None}
    except Exception as e:
      return {"success": False, "error": f"初始化 Agent {agent_name} 失败: {str(e)}", "data": None}
    narrative = context.get("narrative_design") or {}
    analysis = context.get("analysis_result") or context.get("ArchiveAnalysisAgent") or {}
    crawled = context.get("crawled_data") or {}
    parsed = context.get("parsed_files") or {}

    task_input = {
      "initial_input": {
        **base_ctx,
        "title": base_ctx.get("title", "档案数字叙事"),
        "archive_type": base_ctx.get("archive_type", "custom"),
      },
      "dependencies": {
        **{k: v for k, v in context.items() if not k.startswith("_")},
        "ArchiveAnalysisAgent": {"data": analysis, "success": True} if isinstance(analysis, dict) else analysis,
        "WebCrawlerAgent": {"data": crawled, "success": True} if isinstance(crawled, dict) else crawled,
        "DocumentParserAgent": {"data": parsed, "success": True} if isinstance(parsed, dict) else parsed,
      },
    }
    try:
      result = await agent.execute(task_input)
    except Exception as e:
      import traceback; traceback.print_exc()
      return {"success": False, "error": f"执行 Agent {agent_name} 失败: {str(e)}\n{traceback.format_exc()}", "data": None}
    return {
      "success": result.success,
      "data": result.data,
      "error": result.error,
      "answer": result.data,
    }

  async def _run_web_gallery(
    self, task: str, context: Dict, base_ctx: Dict
  ) -> Dict[str, Any]:
    def _safe_dict(val, default=None):
      if isinstance(val, dict): return val
      if isinstance(val, str):
        try: import json; return json.loads(val)
        except: pass
      return default if default is not None else {}

    def _safe_list(val, default=None):
      if isinstance(val, list): return val
      return default if default is not None else []

    analysis = _safe_dict(context.get("analysis_result")) or _safe_dict(context.get("analyzed_data")) or {}
    narrative = _safe_dict(context.get("narrative_design")) or _safe_dict(context.get("narrative_plan")) or {}

    archive_type = base_ctx.get("archive_type", "custom")
    output_dir = base_ctx.get("output_dir", f"outputs/{archive_type}")
    os.makedirs(output_dir, exist_ok=True)

    archive_data = _safe_dict(analysis.get("archive_data"))
    if not archive_data:
      if analysis.get("archive_title"):
        archive_data = analysis
      else:
        archive_data = {
          "archive_title": base_ctx.get("archive_name", "档案数字叙事"),
          "overview": analysis.get("overview", ""),
          "timeline": _safe_list(analysis.get("timeline")),
          "figures": [
            {"name": p.get("name", ""), "role": p.get("role", ""), "bio": p.get("description", ""), "image": p.get("image", "")}
            for p in _safe_dict(analysis.get("entity_extraction"), {}).get("persons", []) if isinstance(p, dict)
          ],
          "spirit": _safe_dict({
            "title": f"{base_ctx.get('archive_name', '档案')}的核心价值",
            "content": analysis.get("overview", ""),
            "keywords": _safe_list(analysis.get("themes")),
          }),
          "route_summary": f"「{base_ctx.get('archive_name', '档案')}」数字叙事",
          "key_stats": _safe_dict(analysis.get("key_stats")),
          "gallery": [],
        }

    try:
      from utils.html_builder import build_archive_website

      source = analysis.get("data_source", "unknown") if isinstance(analysis, dict) else "unknown"
      gallery_images = analysis.get("downloaded_images", []) if isinstance(analysis, dict) else []
      crawler_sources = analysis.get("sources", []) if isinstance(analysis, dict) else []
      if not crawler_sources and isinstance(context.get("crawled_data"), dict):
        crawler_sources = context.get("crawled_data", {}).get("sources", [])
      user_title = base_ctx.get("title", "")
      if user_title and isinstance(user_title, str) and isinstance(archive_data, dict):
        archive_data["archive_title"] = user_title
      if not isinstance(archive_data, dict):
        archive_data = {"archive_title": base_ctx.get("archive_name", "档案数字叙事"), "overview": "", "timeline": [], "figures": []}
      html = build_archive_website(
        archive_data, gallery_images=gallery_images, theme=archive_type,
        archive_type=archive_type, sources=crawler_sources,
      )
      html_path = os.path.join(output_dir, "index.html")
      with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
      meta = {
        "project": archive_type,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": source,
        "html_path": html_path,
        "image_count": len(gallery_images) if isinstance(gallery_images, list) else 0,
      }
      with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
      return {"success": True, "data": {"html_path": html_path, "metadata": meta}}
    except Exception as e:
      import traceback
      self._log("WebGalleryAgent", "error", traceback.format_exc()[-500:])
      return {"success": False, "error": str(e), "data": None}

  def _apply_context_constraints(self, workflow: List[Dict], context: Dict):
    """根据前端显式选择约束 LLM 计划，避免 Planner 自行添加不需要的步骤。"""
    if context.get("enable_crawl", True) is False:
      workflow[:] = [s for s in workflow if s.get("agent") != "WebCrawlerAgent"]
    formats = context.get("output_formats") or []
    if isinstance(formats, str):
      formats = [formats]
    if formats:
      allowed_outputs = set()
      if "html" in formats:
        allowed_outputs.add("WebGalleryAgent")
      if "3d" in formats or "3d_exhibition" in formats:
        allowed_outputs.add("Exhibition3DAgent")
      workflow[:] = [
        s for s in workflow
        if s.get("agent") not in ("WebGalleryAgent", "Exhibition3DAgent")
        or s.get("agent") in allowed_outputs
      ]

  def _normalize_output_keys(self, plan: Dict):
    """将 LLM 生成的任意 output_key 统一替换为规范键名，确保数据流正确"""
    workflow = plan.get("workflow", [])
    for step in workflow:
      agent = step.get("agent", "")
      canonical = self._default_output_key(agent)
      old_key = step.get("output_key", "")
      if old_key and old_key != canonical:
        self._log("planner", "key_normalized", f"'{old_key}' → '{canonical}' ({agent})")
        step["output_key"] = canonical

  def _valid_agent_names(self):
    return {
      "WebCrawlerAgent", "DocumentParserAgent",
      "ArchiveAnalysisAgent", "SmartAnalysisAgent", "SmartInputAgent",
      "WebGalleryAgent", "Exhibition3DAgent", "SmartOutputAgent",
    }

  def _default_output_key(self, agent_name: str) -> str:
    mapping = {
      "WebCrawlerAgent": "crawled_data",
      "DocumentParserAgent": "parsed_files",
      "ArchiveAnalysisAgent": "analysis_result",
      "SmartAnalysisAgent": "analysis_result",
      "WebGalleryAgent": "website",
      "Exhibition3DAgent": "exhibition_3d",
      "SmartOutputAgent": "smart_output",
    }
    return mapping.get(agent_name, agent_name)

  def _log(self, agent: str, action: str, detail: str):
    entry = {
      "timestamp": datetime.now().isoformat(),
      "agent": agent,
      "action": action,
      "detail": detail[:500],
    }
    self._execution_log.append(entry)

  def get_status(self) -> Dict:
    return {
      "planner": self.planner.get_status(),
      "input_agent": self.input_agent.get_status(),
      "web_crawler": self.web_crawler.get_status(),
      "analysis_agent": self.analysis_agent.get_status(),
      "output_agent": self.output_agent.get_status(),
      "execution_log_count": len(self._execution_log),
    }

  async def close(self):
    closeables = [
      self.web_crawler,
      self.input_agent,
      self.analysis_agent,
      self.output_agent,
      self.planner,
    ]
    for obj in closeables:
      close = getattr(obj, "close", None)
      if close:
        try:
          result = close()
          if hasattr(result, "__await__"):
            await result
        except Exception as e:
          self._log(getattr(obj, "name", obj.__class__.__name__), "close_error", str(e))
