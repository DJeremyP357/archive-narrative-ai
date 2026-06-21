import os
import sys
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uuid
from threading import Lock as _ThreadLock

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config.settings import settings
from core.bootstrap import create_llm_router
from core.smart_orchestrator import SmartOrchestrator

# V2 智能编排器（项目唯一编排入口）
smart_orchestrator: Optional[SmartOrchestrator] = None

# 异步任务存储（task_id -> {status, result, error, progress}）
_task_store: Dict[str, dict] = {}
_task_lock = _ThreadLock()

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """项目唯一编排入口 — 仅初始化 SmartOrchestrator（V2）

    V1 DAG 编排器（MultiAgentOrchestrator）已废弃，不再注册 11 个 Agent。
    V2 内部按需懒加载所需 Agent（WebCrawler / DocumentParser / ArchiveAnalysis
    / WebGallery / Exhibition3D），由 PlannerAgent 动态决定调用谁。
    """
    print("[INIT] 正在初始化档案数字叙事AI系统（V2 唯一编排器）...")

    global smart_orchestrator
    llm_router = create_llm_router()
    smart_orchestrator = SmartOrchestrator(llm_router)
    available_providers = [
        p["name"] for p in llm_router.get_available_providers() if p.get("available")
    ]
    print("[OK] 智能编排器已初始化，可用 LLM 提供商: {available_providers or ['none']}")

    # 启动任务存储定期清理（每10分钟）
    cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    print("[STOP] 系统正在关闭...")
    cleanup_task.cancel()
    if smart_orchestrator:
        await smart_orchestrator.close()
    print("[OK] 资源清理完成")


async def _periodic_cleanup():
    """每10分钟清理一次过期任务"""
    while True:
        try:
            await asyncio.sleep(600)
            count = _cleanup_task_store()
            if count > 0:
                print(f"[CLEANUP] 已清理 {count} 个过期任务")
        except asyncio.CancelledError:
            break
        except Exception:
            pass

# 创建FastAPI应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="档案数字叙事AI系统 - 多Agent协同的档案智能叙事生成平台",
    version=settings.VERSION,
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== API路由 ==========

# 对外展示的 Agent 名单
AGENT_NAMES = [
    "PlannerAgent",
    "WebCrawlerAgent", "DocumentParserAgent",
    "ArchiveAnalysisAgent",
    "WebGalleryAgent", "Exhibition3DAgent",
]


@app.get("/")
async def root():
    """根路径 - 系统信息（V2 唯一编排器）"""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "orchestrator": "SmartOrchestrator",
        "available_agents": AGENT_NAMES,
        "archive_themes": list(settings.ARCHIVE_THEMES.keys()),
    }


@app.get("/status")
async def system_status():
    """获取 V2 智能编排器状态"""
    if smart_orchestrator:
        return smart_orchestrator.get_status()
    return {"status": "not_initialized"}

@app.post("/api/v1/parse/documents")
async def parse_documents(files: List[UploadFile] = File(...)):
    """解析上传的档案文件 — V2 通过 SmartOrchestrator 委托"""
    from agents.input.document_parser_agent import DocumentParserAgent

    agent = DocumentParserAgent()

    # 保存上传的文件
    file_infos = []
    for file in files:
        file_path = f"temp/{file.filename}"
        os.makedirs("temp", exist_ok=True)

        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        file_infos.append({
            "path": file_path,
            "type": "auto"
        })

    # 执行解析
    result = await agent.run({"files": file_infos})
    payload = result.to_dict()
    data = payload.get("data") or {}
    parsed_files = data.get("parsed_files", []) if isinstance(data, dict) else []
    payload["file_paths"] = [info["path"] for info in file_infos]
    payload["previews"] = [
        {
            "file": item.get("file", ""),
            "type": item.get("type", ""),
            "preview": (item.get("content") or item.get("description") or str(item.get("table_data", "")))[:500],
            "error": item.get("error", ""),
        }
        for item in parsed_files if isinstance(item, dict)
    ]

    return payload


@app.get("/api/v1/outputs/{filename}")
async def get_output(filename: str):
    """获取生成的文件 — 按主题目录递归查找"""
    for root, dirs, files in os.walk("outputs"):
        if filename in files:
            return FileResponse(os.path.join(root, filename))
    raise HTTPException(status_code=404, detail="文件未找到")


@app.get("/api/v1/themes")
async def get_archive_themes():
    """获取支持的档案专题"""
    return settings.ARCHIVE_THEMES

# ========== 智能编排 API（ReAct Agent） ==========

class SmartNarrativeRequest(BaseModel):
    user_request: str = Field(..., description="用户的自然语言需求描述")
    files: Optional[List[str]] = Field(default=[], description="文件路径列表")
    crawl_keywords: Optional[List[str]] = Field(default=[], description="爬取关键词")
    output_formats: Optional[List[str]] = Field(default=["html"], description="期望的输出格式")
    archive_type: Optional[str] = Field(default="custom", description="档案专题类型")
    archive_name: Optional[str] = Field(default="", description="档案专题名称（自定义时使用）")
    enable_crawl: Optional[bool] = Field(default=True, description="是否启用网络爬取")


def _build_smart_context(request: SmartNarrativeRequest) -> dict:
    """构建通用的智能编排上下文"""
    archive_type = request.archive_type or "custom"
    archive_name = request.archive_name or ""
    
    # 获取专题配置（如果是预定义专题）
    theme_config = settings.ARCHIVE_THEMES.get(archive_type, {})
    
    # 优先使用用户输入的专题名称
    if not archive_name:
        archive_name = theme_config.get("name", "自定义档案")
    
    # 构建关键词列表：优先使用用户输入的关键词
    keywords = list(request.crawl_keywords or [])
    if not keywords:
        # 如果是预定义专题，使用配置的关键词
        if archive_type in settings.ARCHIVE_THEMES:
            keywords = theme_config.get("keywords", [])
        # 如果还是没有关键词，使用专题名称作为关键词
        if not keywords:
            keywords = [archive_name]
    
    # 为自定义专题生成唯一的输出目录，避免同名作品互相覆盖
    if archive_type == "custom":
        import re, hashlib
        safe_name = re.sub(r'[^\w\s-]', '', archive_name).strip().replace(' ', '_')
        if not safe_name or len(safe_name) < 2:
            safe_name = f"custom_{hashlib.md5(archive_name.encode()).hexdigest()[:8]}"
        output_subdir = f"{safe_name[:40]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        output_subdir = archive_type
    
    context = {
        "archive_type": archive_type,
        "archive_name": archive_name,
        "output_formats": request.output_formats or ["html"],
        "relevance_keywords": keywords,
        "output_dir": os.path.join("outputs", output_subdir),
        "enable_crawl": bool(request.enable_crawl),
        "checkpoint_key": f"{archive_type}_{archive_name}",  # 检查点键，同主题可恢复
    }
    
    if request.files:
        context["files"] = request.files
    
    # 爬取目标由 SmartOrchestrator 内部 engineer_queries() 自动生成
    return context


async def _run_generate_task(task_id: str, user_request: str, context: dict):
    """异步执行生成任务（与主事件循环共享，无线程）"""
    _heartbeat_timer = None

    # 保存原始 _log 方法
    _orig_log = smart_orchestrator._log

    def _patched_log(agent: str, action: str, detail: str):
        _orig_log(agent, action, detail)
        # 实时更新 task_store，让前端能看到每个 Agent 的执行状态
        agent_labels = {
            "planner": "规划器",
            "WebCrawlerAgent": "网络爬虫",
            "DocumentParserAgent": "文档解析",
            "ArchiveAnalysisAgent": "档案分析",
            "SmartAnalysisAgent": "智能分析",
            "WebGalleryAgent": "网站生成",
            "Exhibition3DAgent": "3D展厅生成",
            "SmartOutputAgent": "输出编排",
            "orchestrator": "编排器",
        }
        label = agent_labels.get(agent, agent)
        if action == "started":
            _update_task(task_id, "running", f"{label} 正在执行...")
        elif action == "completed":
            _update_task(task_id, "running", f"{label} 已完成")
        elif action in ("failed", "error"):
            _update_task(task_id, "running", f"{label} 执行出错")
        # 同时保存执行日志到 task_store，供前端实时读取
        with _task_lock:
            task = _task_store.get(task_id)
            if task:
                if "execution_log" not in task:
                    task["execution_log"] = []
                task["execution_log"].append({
                    "agent": agent, "action": action,
                    "detail": detail[:200], "timestamp": datetime.now().isoformat()
                })

    smart_orchestrator._log = _patched_log

    def _heartbeat():
        nonlocal _heartbeat_timer
        task = _task_store.get(task_id)
        if task and task.get("status") == "running":
            _update_task(task_id, "running", task.get("progress", "正在生成中..."))
        _heartbeat_timer = asyncio.get_event_loop().call_later(15, _heartbeat)

    try:
        progress = "正在基于现有输入生成作品..."
        if context.get("files"):
            progress = "正在解析上传档案并生成作品..."
        elif context.get("enable_crawl", True):
            progress = "正在爬取网络资料并生成作品..."
        _update_task(task_id, "running", progress)
        _heartbeat()

        try:
            result = await asyncio.wait_for(smart_orchestrator.execute(user_request, context), timeout=1800)
        finally:
            if _heartbeat_timer:
                _heartbeat_timer.cancel()
            # 恢复原始 _log 方法
            smart_orchestrator._log = _orig_log

        outputs = []
        _seen_paths = set()

        def extract_outputs(obj):
            if not obj or not isinstance(obj, dict):
                return
            path = obj.get("html_path")
            if path and path not in _seen_paths:
                _seen_paths.add(path)
                norm_path = path.replace("\\", "/")
                out_type = "3D 展厅" if ("exhibition_3d" in norm_path or "3d" in norm_path.lower()) else "HTML 网站"
                outputs.append({"type": out_type, "path": path,
                    "url": "/outputs/" + norm_path.split("outputs/")[-1] if "outputs" in norm_path else path})
            for k, v in obj.items():
                if isinstance(v, dict) and k not in ("_context", "metadata"):
                    extract_outputs(v)

        results = result.get("results", {})
        extract_outputs(results)

        _update_task(task_id, "completed", "生成完成", {
            "status": "completed" if result.get("success") else "partial",
            "plan": result.get("plan"),
            "results": results,
            "outputs": result.get("outputs") or outputs,
            "execution_log": result.get("execution_log", []),
            "data_source": results.get("analysis_result", {}).get("data_source", "unknown") if isinstance(results.get("analysis_result"), dict) else "unknown",
            "elapsed": result.get("elapsed"),
        })
        # 任务成功完成，清除检查点
        from core.smart_orchestrator import _clear_checkpoint
        _clear_checkpoint(context.get("checkpoint_key", ""))
    except asyncio.TimeoutError:
        if _heartbeat_timer:
            _heartbeat_timer.cancel()
        _update_task(task_id, "failed", "生成任务超时（超过30分钟），检查点已保存，重新提交可从断点恢复")
    except Exception as e:
        if _heartbeat_timer:
            _heartbeat_timer.cancel()
        _update_task(task_id, "failed", str(e)[:200])


def _update_task(task_id: str, status: str, progress: str, result: dict = None):
    with _task_lock:
        _task_store[task_id] = {"status": status, "progress": progress,
                                "result": result, "updated_at": datetime.now().isoformat()}


def _cleanup_task_store():
    """清理超过30分钟的任务，防止内存泄漏"""
    with _task_lock:
        now = datetime.now()
        expired = [
            tid for tid, t in _task_store.items()
            if t.get("updated_at") and (now - datetime.fromisoformat(t["updated_at"])).total_seconds() > 1800
        ]
        for tid in expired:
            del _task_store[tid]
        return len(expired)


@app.post("/api/v2/narrative/smart")
async def smart_generate(request: SmartNarrativeRequest):
    """异步叙事生成 — 提交任务后立即返回 task_id，前端轮询 /api/v2/narrative/status/{task_id}"""
    if not smart_orchestrator:
        raise HTTPException(status_code=503, detail="智能编排器未初始化")

    context = _build_smart_context(request)
    task_id = str(uuid.uuid4())[:8]
    _update_task(task_id, "pending", "任务已提交")

    asyncio.create_task(_run_generate_task(task_id, request.user_request, context))

    return {"task_id": task_id, "status": "pending", "message": "任务已提交，请轮询状态"}


@app.get("/api/v2/narrative/status/{task_id}")
async def task_status(task_id: str):
    """查询异步任务状态"""
    with _task_lock:
        task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return {"task_id": task_id, **task}

@app.get("/api/v2/status")
async def smart_system_status():
    """获取智能编排系统状态"""
    if not smart_orchestrator:
        return {"status": "not_initialized"}
    return smart_orchestrator.get_status()

@app.get("/api/v1/llm/providers")
async def get_llm_providers():
    """获取可用的LLM提供商"""
    return {
        "providers": [
            {"name": "Qwen（通义千问）", "status": "available" if settings.QWEN_API_KEY else "not_configured", "model": settings.QWEN_MODEL},
        ]
    }


# ========== 前端需要的诊断路由 ==========

@app.get("/api/v1/system/diagnostics")
async def system_diagnostics():
    """系统诊断 — 返回 Agent 列表、LLM 状态、媒体 API 状态"""
    from core.bootstrap import build_diagnostics
    return build_diagnostics()


# ========== 对话路由（前端聊天用） ==========

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    history: Optional[List[Dict]] = Field(default=[], description="历史对话")
    files: Optional[List[str]] = Field(default=[], description="已上传文件路径")
    archive_type: Optional[str] = Field(default="custom", description="档案专题")
    archive_name: Optional[str] = Field(default="", description="档案专题名称")
    mode: Optional[str] = Field(default="chat", description="模式: chat=对话, parse=结构化提取")


# 这些词只用于聊天回复引导，不再在聊天接口中直接启动生成。
_TRIGGER_KEYWORDS = [
    "生成", "做一个", "建一个", "创建", "出作品", "出网站", "做网站",
    "搭建", "搭建展厅", "3D展厅", "三维展厅", "数字叙事", "叙事作品",
    "开始制作", "动手", "启动生成", "GO", "go", "开始",
]


def _looks_like_generate_intent(message: str) -> bool:
    """判断用户消息是否在请求生成档案数字叙事作品。"""
    msg = (message or "").lower()
    if "档案专题解析器" in msg:
        return False
    return bool(msg.strip()) and any(kw.lower() in msg for kw in _TRIGGER_KEYWORDS)


@app.post("/api/v2/chat")
async def chat_with_agent(request: ChatRequest):
    """与 Agent 对话 — 角色注入 + 上下文感知

    模式：
    - parse: 结构化提取，直接透传 prompt 给 LLM，无角色注入
    - chat: 顾问式对话（默认）
    """
    if not smart_orchestrator:
        raise HTTPException(status_code=503, detail="智能编排器未初始化")

    # === parse 模式：直接透传，不做角色注入和意图检测 ===
    if request.mode == "parse":
        try:
            messages = [{"role": "user", "content": request.message}]
            result = await smart_orchestrator.llm_router.chat_with_fallback(
                messages, agent_name="SmartOrchestrator"
            )
            reply = result["choices"][0]["message"]["content"]
            return {"reply": reply, "intent": "parse", "agent": "SmartOrchestrator"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")

    theme_config = settings.ARCHIVE_THEMES.get(request.archive_type, {})
    theme_name = theme_config.get("name", request.archive_type)
    archive_name = request.archive_name or request.archive_type or "档案"

    # === 1. 生成意图只引导，不在聊天接口直接启动工作流 ===
    if _looks_like_generate_intent(request.message):
        return {
            "reply": (
                f"我已识别到你想生成「{archive_name}」档案数字叙事作品。"
                "请确认右侧的专题名称、输出格式和是否启用爬虫，然后点击「生成作品」按钮开始。"
            ),
            "intent": "generate_hint",
            "agent": "SmartOrchestrator",
        }

    # === 2. 顾问式对话 — 角色注入 ===
    role = (
        f"你是「档案数字叙事馆」的资深档案顾问 Agent，名叫「叙叙」。\n"
        f"当前对话围绕「{archive_name}」（专题分类：{theme_name}）。\n"
        f"你的职责：\n"
        f"  1. 回答用户关于该档案的历史、人物、事件、文化价值的问题；\n"
        f"  2. 帮用户厘清叙事结构（时间线、人物、影像、空间）；\n"
        f"  3. 在用户明确表示「生成/做网站/做展厅」时，简短回答后引导其使用系统自动生成；\n"
        f"  4. 不要瞎编档案中不存在的细节；不确定就坦白；\n"
        f"  5. 回答要简洁、有温度、像博物馆讲解员，不超过 200 字。"
    )

    messages = [{"role": "system", "content": role}]
    for h in (request.history or [])[-10:]:
        role_h = h.get("role", "user")
        if role_h not in ("user", "assistant", "system"):
            role_h = "user"
        messages.append({"role": role_h, "content": h.get("content", "")})
    messages.append({"role": "user", "content": request.message})

    try:
        result = await smart_orchestrator.llm_router.chat_with_fallback(
            messages,
            agent_name="SmartOrchestrator"  # qwen3-max：长上下文调度
        )
        reply = result["choices"][0]["message"]["content"]
        return {
            "reply": reply,
            "intent": "chat",
            "agent": "SmartOrchestrator",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")


# ========== 静态文件服务（让前端能访问产物） ==========

from fastapi.staticfiles import StaticFiles

# 挂载 outputs 目录为静态文件服务（支持所有子目录）
if os.path.exists("outputs"):
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# 挂载 web 目录为静态文件服务（前端页面）
if os.path.exists("web"):
    app.mount("/web", StaticFiles(directory="web", html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
