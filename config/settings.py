import os
from typing import Dict, List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "档案数字叙事AI系统"
    VERSION: str = "2.0.0"
    DEBUG: bool = True

    # ========== 国产大语言模型API ==========

    # 深度求索 DeepSeek (推荐首选)
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL: Optional[str] = os.getenv(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
    )
    DEEPSEEK_MODEL: Optional[str] = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 通义千问 Qwen (阿里云)
    QWEN_API_KEY: Optional[str] = os.getenv("QWEN_API_KEY")
    QWEN_BASE_URL: Optional[str] = os.getenv(
        "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    QWEN_MODEL: Optional[str] = os.getenv("QWEN_MODEL", "qwen-plus")

    # 5 个模型各司其职（统一走 DashScope 协议，单 QWEN_API_KEY 即可）
    # 🧠 中央调度：意图识别、任务规划、ReAct 推理
    QWEN_MODEL_PLANNER: Optional[str] = os.getenv("QWEN_MODEL_PLANNER", "qwen3.7-plus")
    # 👁️ 视觉：爬虫图片过滤、智能分类、图像理解
    QWEN_MODEL_VL: Optional[str] = os.getenv("QWEN_MODEL_VL", "qwen3-vl-235b-a22b-instruct")
    # 🎬 全模态：解析用户上传的图片/音频/视频档案
    QWEN_MODEL_OMNI: Optional[str] = os.getenv("QWEN_MODEL_OMNI", "qwen3-omni-flash")
    # ✍️ 大语言：长文档分析、叙事文案
    QWEN_MODEL_LLM: Optional[str] = os.getenv("QWEN_MODEL_LLM", "qwen3-max")
    # 💻 代码：HTML/CSS/JS 网站 + Three.js 3D 展厅
    QWEN_MODEL_CODER: Optional[str] = os.getenv("QWEN_MODEL_CODER", "qwen3-coder-plus")

    # 月之暗面 Kimi / Moonshot
    KIMI_API_KEY: Optional[str] = os.getenv("KIMI_API_KEY")
    KIMI_BASE_URL: Optional[str] = os.getenv(
        "KIMI_BASE_URL", "https://api.moonshot.cn/v1"
    )
    KIMI_MODEL: Optional[str] = os.getenv("KIMI_MODEL", "moonshot-v1-8k")

    # 智谱AI ChatGLM
    ZHIPU_API_KEY: Optional[str] = os.getenv("ZHIPU_API_KEY")
    ZHIPU_BASE_URL: Optional[str] = os.getenv(
        "ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    ZHIPU_MODEL: Optional[str] = os.getenv("ZHIPU_MODEL", "glm-4")

    # 百度文心一言 ERNIE
    WENXIN_API_KEY: Optional[str] = os.getenv("WENXIN_API_KEY")
    WENXIN_SECRET_KEY: Optional[str] = os.getenv("WENXIN_SECRET_KEY")
    WENXIN_MODEL: Optional[str] = os.getenv("WENXIN_MODEL", "ernie-4.0-8k")

    # 百川智能 Baichuan
    BAICHUAN_API_KEY: Optional[str] = os.getenv("BAICHUAN_API_KEY")
    BAICHUAN_BASE_URL: Optional[str] = os.getenv(
        "BAICHUAN_BASE_URL", "https://api.baichuan-ai.com/v1"
    )
    BAICHUAN_MODEL: Optional[str] = os.getenv("BAICHUAN_MODEL", "Baichuan4")

    # 腾讯混元 Hunyuan
    HUNYUAN_SECRET_ID: Optional[str] = os.getenv("HUNYUAN_SECRET_ID")
    HUNYUAN_SECRET_KEY: Optional[str] = os.getenv("HUNYUAN_SECRET_KEY")
    HUNYUAN_MODEL: Optional[str] = os.getenv("HUNYUAN_MODEL", "hunyuan-pro")

    # 讯飞星火 Spark
    SPARK_APP_ID: Optional[str] = os.getenv("SPARK_APP_ID")
    SPARK_API_KEY: Optional[str] = os.getenv("SPARK_API_KEY")
    SPARK_API_SECRET: Optional[str] = os.getenv("SPARK_API_SECRET")
    SPARK_MODEL: Optional[str] = os.getenv("SPARK_MODEL", "4.0Ultra")

    # 自托管/私有化部署
    LOCAL_LLM_URL: Optional[str] = os.getenv(
        "LOCAL_LLM_URL", "http://localhost:8000/v1"
    )

    # ========== 国产图像生成API ==========

    # 通义万相 (阿里) — 生图首选
    TONGYI_WANXIANG_API_KEY: Optional[str] = os.getenv("TONGYI_WANXIANG_API_KEY")

    # 文心一格 (百度)
    WENXIN_YIGE_API_KEY: Optional[str] = os.getenv("WENXIN_YIGE_API_KEY")
    WENXIN_YIGE_SECRET: Optional[str] = os.getenv("WENXIN_YIGE_SECRET")

    # 智谱 CogView
    COGVIEW_API_KEY: Optional[str] = os.getenv("COGVIEW_API_KEY")

    # 可灵 (快手) — 图像+视频生成
    KLING_API_KEY: Optional[str] = os.getenv("KLING_API_KEY")
    KLING_API_SECRET: Optional[str] = os.getenv("KLING_API_SECRET")

    # ========== 国产语音合成API ==========

    # 百度语音合成
    BAIDU_TTS_APP_ID: Optional[str] = os.getenv("BAIDU_TTS_APP_ID")
    BAIDU_TTS_API_KEY: Optional[str] = os.getenv("BAIDU_TTS_API_KEY")
    BAIDU_TTS_SECRET: Optional[str] = os.getenv("BAIDU_TTS_SECRET")

    # 阿里云语音合成
    ALI_TTS_ACCESS_ID: Optional[str] = os.getenv("ALI_TTS_ACCESS_ID")
    ALI_TTS_ACCESS_SECRET: Optional[str] = os.getenv("ALI_TTS_ACCESS_SECRET")
    ALI_TTS_APP_KEY: Optional[str] = os.getenv("ALI_TTS_APP_KEY")

    # 讯飞语音合成
    XUNFEI_TTS_APP_ID: Optional[str] = os.getenv("XUNFEI_TTS_APP_ID")
    XUNFEI_TTS_API_KEY: Optional[str] = os.getenv("XUNFEI_TTS_API_KEY")
    XUNFEI_TTS_API_SECRET: Optional[str] = os.getenv("XUNFEI_TTS_API_SECRET")

    # 腾讯云语音合成
    TENCENT_TTS_SECRET_ID: Optional[str] = os.getenv("TENCENT_TTS_SECRET_ID")
    TENCENT_TTS_SECRET_KEY: Optional[str] = os.getenv("TENCENT_TTS_SECRET_KEY")

    # ========== 国产视频生成API ==========

    # 通义万相视频 (阿里千问系列) — 生视频首选
    QWEN_VIDEO_API_KEY: Optional[str] = os.getenv("QWEN_VIDEO_API_KEY")

    # 可灵视频生成 (快手)
    KLING_VIDEO_API_KEY: Optional[str] = os.getenv("KLING_VIDEO_API_KEY")

    # 即梦视频生成 (字节跳动/火山引擎)
    JIMENG_API_KEY: Optional[str] = os.getenv("JIMENG_API_KEY")
    JIMENG_SECRET: Optional[str] = os.getenv("JIMENG_SECRET")

    # ========== 爬虫配置 ==========
    PLAYWRIGHT_HEADLESS: bool = True
    REQUESTS_TIMEOUT: int = 30
    MAX_RETRY: int = 3
    CRAWL_DELAY: float = 1.0  # 爬取间隔(秒)，遵守robots协议
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # ========== 输出配置 ==========
    OUTPUT_DIR: str = "outputs"
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    TEMP_DIR: str = "temp"

    # ========== 3D模型配置 ==========
    NERF_STUDIO_URL: Optional[str] = os.getenv("NERF_STUDIO_URL")
    GAUSSIAN_SPLATTING_URL: Optional[str] = os.getenv("GAUSSIAN_SPLATTING_URL")

    # ========== 档案专题配置 ==========
    # 预定义专题（可通过 register_theme() 动态扩展）
    ARCHIVE_THEMES: Dict[str, Dict] = {
        "red_archives": {
            "name": "红色档案",
            "description": "中国共产党革命历史档案",
            "keywords": ["革命", "党史", "长征", "延安", "抗战", "解放战争"],
            "narrative_style": "庄重、感人、激励",
        },
        "folk_archives": {
            "name": "民生档案",
            "description": "反映民众生活变迁的档案",
            "keywords": ["户籍", "土地", "婚姻", "教育", "医疗", "就业"],
            "narrative_style": "温情、真实、贴近生活",
        },
        "intangible_heritage": {
            "name": "非遗档案",
            "description": "非物质文化遗产档案",
            "keywords": ["传统技艺", "民俗", "戏曲", "手工艺", "口头传统"],
            "narrative_style": "文化传承、匠心、活态",
        },
        "celebrity_archives": {
            "name": "名人档案",
            "description": "历史名人相关档案",
            "keywords": ["人物", "生平", "成就", "影响", "时代"],
            "narrative_style": "传记式、深度、启发",
        },
        "social_media": {
            "name": "社交媒体档案",
            "description": "社交媒体数据档案",
            "keywords": ["微博", "微信", "网络文化", "数字记忆"],
            "narrative_style": "年轻化、互动、多元",
        },
        "game_archives": {
            "name": "游戏存档档案",
            "description": "电子游戏历史档案",
            "keywords": ["游戏史", "像素", "怀旧", "电竞", "MOD"],
            "narrative_style": "怀旧、创新、亚文化",
        },
        "custom": {
            "name": "自定义档案",
            "description": "用户自定义的档案专题",
            "keywords": [],
            "narrative_style": "根据内容自适应",
        },
    }

    model_config = {"env_file": ".env", "extra": "allow"}


settings = Settings()