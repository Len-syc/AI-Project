"""全局配置：从 .env 读取，mock 模式下不依赖任何外部 API。"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM_MODE: mock = 纯本地规则跑通全链路（演示保底） | api = 走 OpenAI 兼容接口
LLM_MODE = os.getenv("LLM_MODE", "mock")

# 主模型（OpenAI 兼容协议，换厂商只改这三个）
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_SMALL_MODEL = os.getenv("LLM_SMALL_MODEL", LLM_MODEL)

# 视觉模型（材料识别用，同样 OpenAI 兼容）
VLM_BASE_URL = os.getenv("VLM_BASE_URL", LLM_BASE_URL)
VLM_API_KEY = os.getenv("VLM_API_KEY", LLM_API_KEY)
VLM_MODEL = os.getenv("VLM_MODEL", "glm-4v-flash")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "app", "data")
POLICIES_FILE = os.path.join(DATA_DIR, "policies.json")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample_materials")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
