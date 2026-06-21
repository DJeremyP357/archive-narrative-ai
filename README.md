# 档案数字叙事 AI 系统

> 基于多模型协同的智能档案叙事生成系统 —— 从爬取、分析到 3D 沉浸式展示的全流程自动化

## 项目简介

本项目是一个档案智能叙事生成系统。用户输入一个档案主题（如"南仁东""红色档案""非遗档案"），系统自动完成：

1. **网络爬取** — 多引擎搜索并爬取相关图文资料
2. **关键词提取** — 基于底层大模型语料库生成相应关键词
3. **图片下载与验证** — 下载图片、内容去重、尺寸过滤、视觉模型验证相关性
4. **档案分析** — LLM 提取人物、时间线、关联关系、精神主题，生成结构化叙事
5. **图片智能分配** — 视觉语义匹配，为人物配肖像、为事件配场景图
6. **双端展示** — 生成叙事网页 + Three.js 3D 虚拟展厅

## 核心特性

- **多模型分工**：通义千问系列各司其职（LLM 分析 / VL 视觉验证 / Coder 代码生成 / Planner 规划）
- **智能图片匹配**：结合 VL 描述、网页上下文、中文 n-gram 语义匹配，避免人物张冠李戴
- **3D 沉浸展厅**：Three.js 第一人称漫游，墙面展示档案，走近展品查看详情
- **多档案类型**：红色档案、名人档案、非遗档案、民生档案等 7 种预定义专题
- **断点续跑**：检查点机制，长流程中断后可恢复

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + Uvicorn |
| LLM | 阿里云通义千问（qwen3-max / qwen3-vl / qwen3-omni 等） |
| 爬虫 | aiohttp + Playwright + 百度/Bing 搜索适配器 |
| 视觉分析 | qwen3-vl-235b（图片验证 + 分类 + 描述） |
| 3D 展示 | Three.js（WebGL 第一人称漫游） |
| 前端 | 原生 HTML/CSS/JS |

## 项目结构

```
archive-narrative-ai/
├── api/                    # FastAPI 接口层
│   └── main.py             # API 入口（/api/v2/narrative/smart）
├── agents/                 # Agent 层
│   ├── input/              # 输入层（文档解析、网络爬虫、智能输入）
│   ├── processing/         # 处理层（档案分析）
│   ├── output/             # 输出层（网页生成、3D 展厅、智能输出）
│   └── orchestrator/       # 编排层（规划器）
├── core/                   # 核心层
│   ├── smart_orchestrator.py   # 智能编排器（核心调度）
│   ├── llm_client.py           # 多模型路由
│   ├── vision_service.py       # 视觉验证服务
│   └── base_agent.py           # Agent 基类
├── config/                 # 配置层
│   ├── settings.py             # 环境配置
│   └── agent_catalog.py        # Agent 注册表
├── crawler/                # 爬虫层
│   ├── adapters/               # 搜索引擎适配器
│   └── content_extractor.py    # 内容提取
├── utils/                  # 工具层
│   ├── html_builder.py         # 叙事网页生成
│   ├── crawl_helpers.py        # 爬虫辅助函数
│   └── image_downloader.py     # 图片下载器
├── web/                    # 前端页面
│   ├── index.html
│   └── index.js
└── .env.example            # 环境变量模板
```

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/你的用户名/archive-narrative-ai.git
cd archive-narrative-ai

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install fastapi uvicorn aiohttp beautifulsoup4 lxml Pillow python-dotenv pydantic-settings
```

### 2. 配置 API Key

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入你的通义千问 API Key
# 获取地址：https://dashscope.console.aliyun.com/
```

`.env` 中必须配置的项：

```
QWEN_API_KEY=你的密钥
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3-max
QWEN_MODEL_PLANNER=qwen3.7-plus
QWEN_MODEL_VL=qwen3-vl-235b-a22b-instruct
QWEN_MODEL_OMNI=qwen3-omni-flash
QWEN_MODEL_LLM=qwen3-max
QWEN_MODEL_CODER=qwen3-coder-plus
```

### 3. 启动服务

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8080
```

浏览器访问 `http://localhost:8080/web/index.html` 打开前端页面。

### 4. 生成档案

在前端输入档案主题（如"南仁东"），选择档案类型，点击生成。系统会自动爬取、分析、生成网页和 3D 展厅。

生成结果保存在 `outputs/` 目录下。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v2/narrative/smart` | 提交档案生成任务（异步） |
| GET | `/api/v2/narrative/status/{task_id}` | 查询任务状态 |
| GET | `/api/v2/status` | 系统状态 |
| GET | `/api/v1/outputs/{filename}` | 获取生成产物 |

## 模型分工

| Agent | 模型 | 职责 |
|-------|------|------|
| PlannerAgent | qwen3.7-plus | 工作流规划 |
| ArchiveAnalysisAgent | qwen3-max | 档案内容分析、实体抽取、叙事生成 |
| WebCrawlerAgent | qwen3-vl-235b | 爬虫辅助判断 |
| DocumentParserAgent | qwen3-omni-flash | 文档解析 |
| ImageVerifier | qwen3-vl-235b | 图片相关性验证 |
| WebGalleryAgent | qwen3.7-plus | 网页生成 |

## 档案专题类型

| 类型 | 标识 | 描述 |
|------|------|------|
| 红色档案 | `red_archives` | 革命历史档案 |
| 名人档案 | `celebrity_archives` | 历史名人档案 |
| 非遗档案 | `intangible_heritage` | 非物质文化遗产 |
| 民生档案 | `folk_archives` | 民众生活变迁 |
| 社交媒体档案 | `social_media` | 网络数字记忆 |
| 游戏存档档案 | `game_archives` | 电子游戏历史 |
| 自定义 | `custom` | 用户自定义主题 |

## 注意事项

- 需要有效的阿里云 DashScope API Key
- 图片下载需要网络通畅，部分网站可能有反爬限制
- 3D 展厅需要支持 WebGL 的浏览器
- 生成一次完整档案约消耗 3-5 万 token（含 VL 验证）

## License

MIT
