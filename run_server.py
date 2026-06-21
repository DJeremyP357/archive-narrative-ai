"""Windows Playwright 兼容启动"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8080)
