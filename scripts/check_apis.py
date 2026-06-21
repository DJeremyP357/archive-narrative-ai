#!/usr/bin/env python3
"""检查各 API Key 是否配置、各 Agent 理论上会用到哪些算力。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from core.bootstrap import build_diagnostics, create_llm_router


def main():
    router = create_llm_router()
    diag = build_diagnostics(router)

    print("=" * 60)
    print("  档案数字叙事 AI — API / Agent 诊断")
    print("=" * 60)

    print("\n【LLM 大模型】")
    for p in diag["llm_providers"]:
        mark = "[OK]" if p["available"] else "[--]"
        print(f"  {mark} {p['name']:12} model={p.get('model','')}")

    print("\n【图像 / 语音 / 视频 API】")
    for m in diag["media_apis"]:
        mark = "[OK]" if m["configured"] else "[--]"
        print(f"  {mark} {m['label']:12} ({m['env_var']})")

    print(f"\n【Agent 注册表】共 {diag['agent_count']} 个")
    for a in diag["agents"]:
        llm_note = ""
        if a["uses_llm_api"]:
            ready = "可用" if a["preferred_llm_ready"] else "未配置Key"
            llm_note = f" LLM={a['preferred_llm']}({ready})"
        wrap = f" ← {a['smart_wrapper']}" if a.get("smart_wrapper") else ""
        print(f"  [{a['layer']:12}] {a['name']:26} {a['kind']:6}{llm_note}{wrap}")

    print("\n【执行模式】")
    for k, v in diag["execution_modes"].items():
        print(f"  {k}: {v}")

    print("\n" + diag["homework_tip"])
    print("=" * 60)

    out = os.path.join("outputs", "diagnostics.json")
    os.makedirs("outputs", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n完整 JSON: {out}")


if __name__ == "__main__":
    main()
