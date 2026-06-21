#!/usr/bin/env python3
"""
档案数字叙事 — 统一作业入口

示例:
  # 爬取网络资料并生成 HTML 网站
  python run_narrative.py --theme custom --title "敦煌莫高窟" --keywords 敦煌 莫高窟 丝绸之路 --crawl

  # 使用本地文件生成
  python run_narrative.py --theme celebrity_archives --formats html --files ./data/*.pdf

  # 仅检查 API 配置
  python run_narrative.py --check-only
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time

# Windows Playwright 兼容修复
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

# Windows 控制台中文编码修复
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleOutputCP(65001)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.agent_catalog import OUTPUT_FORMAT_TO_AGENT
from config.settings import settings
from core.bootstrap import create_app_context, shutdown_app_context
from core.smart_orchestrator import SmartOrchestrator


def build_v2_plan(
    archive_type: str,
    output_formats: list,
    has_files: bool,
    do_crawl: bool,
    archive_name: str = "",
) -> dict:
    """构建 v2 工作流计划"""
    workflow = []
    step = 1
    topic = archive_name or archive_type

    if has_files:
        workflow.append({
            "step": step,
            "agent": "DocumentParserAgent",
            "task": f"解析用户提供的{archive_type}档案文件",
            "input_from": [],
            "output_key": "parsed_files",
        })
        step += 1

    if do_crawl or not has_files:
        workflow.append({
            "step": step,
            "agent": "WebCrawlerAgent",
            "task": f"爬取与「{topic}」相关的公开档案资料与图片",
            "input_from": [],
            "output_key": "crawled_data",
        })
        step += 1

    prev = []
    if workflow:
        prev = [workflow[-1]["output_key"]]

    workflow.append({
        "step": step,
        "agent": "ArchiveAnalysisAgent",
        "task": "基于输入数据深度分析并提取叙事要素",
        "input_from": prev or ["crawled_data", "parsed_files"],
        "output_key": "analysis_result",
    })
    step += 1

    for fmt in output_formats:
        agent = OUTPUT_FORMAT_TO_AGENT.get(fmt)
        if not agent:
            continue
        workflow.append({
            "step": step,
            "agent": agent,
            "task": f"生成 {fmt} 格式叙事作品",
            "input_from": ["analysis_result"],
            "output_key": f"output_{fmt}",
        })
        step += 1

    return {
        "analysis": f"专题={archive_type}, 输出={output_formats}",
        "workflow": workflow,
        "output_formats": output_formats,
    }


def get_theme_crawl_targets(archive_type: str, keywords: list = None) -> list:
    """根据档案专题动态生成爬取目标（通用，无特殊分支）"""
    if not keywords:
        theme = settings.ARCHIVE_THEMES.get(archive_type, {})
        keywords = theme.get("keywords", [archive_type])

    if not keywords:
        return []

    from urllib.parse import quote
    primary_kw = keywords[0]
    targets = [
        {
            "name": f"百度百科-{primary_kw}",
            "url": f"https://baike.baidu.com/item/{quote(primary_kw)}",
            "method": "direct",
            "relevance_keywords": keywords,
        },
        {
            "name": f"百度搜索-{primary_kw}",
            "url": f"https://www.baidu.com/s?wd={quote(primary_kw)}",
            "method": "baidu_search",
            "relevance_keywords": keywords,
        },
        {
            "name": f"百度图片-{primary_kw}",
            "url": f"https://image.baidu.com/search/index?tn=baiduimage&word={quote(primary_kw)}",
            "method": "baidu_image_search",
            "relevance_keywords": keywords,
        },
    ]

    for kw in keywords[1:3]:
        targets.append({
            "name": f"百度百科-{kw}",
            "url": f"https://baike.baidu.com/item/{quote(kw)}",
            "method": "direct",
            "relevance_keywords": keywords,
        })
        targets.append({
            "name": f"百度搜索-{kw}",
            "url": f"https://www.baidu.com/s?wd={quote(kw)}",
            "method": "baidu_search",
            "relevance_keywords": keywords,
        })

    return targets


def get_theme_keywords(archive_type: str) -> list:
    """根据档案专题获取相关性关键词"""
    theme = settings.ARCHIVE_THEMES.get(archive_type, {})
    return theme.get("keywords", [])


async def run_v2(args, ctx):
    """v2: SmartOrchestrator 智能编排"""
    theme = settings.ARCHIVE_THEMES.get(args.theme, {})
    title = args.title or theme.get("name", args.theme)
    keywords = args.keywords or get_theme_keywords(args.theme) or [title]

    user_request = (
        f"为「{title}」生成档案数字叙事作品，专题类型 {args.theme}，"
        f"输出格式: {', '.join(args.formats)}。"
    )
    if args.description:
        user_request += f" 说明: {args.description}"

    safe_theme = re.sub(r'[^\w\s-]', '', args.theme).strip().replace(' ', '_') or "custom"
    context = {
        "archive_type": args.theme,
        "archive_name": title,
        "output_dir": os.path.join(ctx.output_dir, safe_theme),
        "files": args.files or [],
        "relevance_keywords": keywords,
    }

    if args.crawl:
        targets = get_theme_crawl_targets(args.theme, keywords)
        if targets:
            context["crawl_targets"] = targets

    plan = build_v2_plan(
        args.theme,
        args.formats,
        has_files=bool(args.files),
        do_crawl=args.crawl,
        archive_name=title,
    )

    orch = SmartOrchestrator(ctx.llm_router)
    try:
        result = await orch.execute(user_request, context=context, plan=plan)
    finally:
        await orch.close()

    return result


async def main():
    parser = argparse.ArgumentParser(description="档案数字叙事 AI Agent 统一入口")
    parser.add_argument(
        "--theme", default="custom",
        help="档案专题",
    )
    parser.add_argument(
        "--formats", "-f", nargs="+", default=["html"],
        choices=list(OUTPUT_FORMAT_TO_AGENT.keys()),
        help="输出格式",
    )
    parser.add_argument("--title", default="", help="作品标题")
    parser.add_argument("--description", default="", help="补充说明")
    parser.add_argument("--keywords", nargs="*", default=[], help="爬取关键词")
    parser.add_argument("--files", nargs="*", default=[], help="本地档案文件路径")
    parser.add_argument("--crawl", action="store_true", help="启用网络爬取")
    parser.add_argument("--check-only", action="store_true", help="仅打印 API 诊断")

    args = parser.parse_args()

    if args.check_only:
        from scripts.check_apis import main as check_main
        check_main()
        return

    print("=" * 60)
    print(f"  {settings.PROJECT_NAME}")
    print(f"  专题: {args.theme} | 格式: {args.formats}")
    print("=" * 60)

    ctx = create_app_context(output_dir="outputs")
    print(f"\n已注册 LLM: {', '.join(ctx.registered_llm_providers) or '(无)'}")

    if not ctx.registered_llm_providers:
        print("\n[WARN] 未检测到任何 LLM API Key")
        print("  请在 .env 中配置 QWEN_API_KEY\n")

    start = time.time()
    try:
        result = await run_v2(args, ctx)
    finally:
        await shutdown_app_context(ctx)

    elapsed = time.time() - start
    safe_theme = re.sub(r'[^\w\s-]', '', args.theme).strip().replace(' ', '_') or "custom"
    out_path = os.path.join(ctx.output_dir, safe_theme, "run_result.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    # 打印结果摘要
    print(f"\n{'=' * 60}")
    print(f"  完成，耗时 {elapsed:.1f}s")
    print(f"{'=' * 60}")

    if result.get("success"):
        results = result.get("results", {})
        if "website" in results:
            website = results["website"]
            if isinstance(website, dict) and website.get("html_path"):
                print(f"\n  [OK] 网站: {website['html_path']}")
        if "analysis_result" in results:
            analysis = results["analysis_result"]
            if isinstance(analysis, dict):
                source = analysis.get("data_source", "unknown")
                print(f"  [OK] 数据来源: {source}")
        if "crawled_data" in results:
            crawled = results["crawled_data"]
            if isinstance(crawled, dict):
                img_count = len(crawled.get("downloaded_images", []))
                print(f"  [OK] 下载图片: {img_count} 张")

    print(f"\n  结果保存: {out_path}")
    print(f"{'=' * 60}")

    return result


if __name__ == "__main__":
    asyncio.run(main())
