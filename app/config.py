"""全局配置：从 .env 读取，mock 模式下不依赖任何外部 API。"""
import os
from dotenv import load_dotenv

load_dotenv()

# LLM_MODE: mock = 纯本地规则跑通全链路（演示保底） | api = 走 OpenAI 兼容接口
LLM_MODE = os.getenv("LLM_MODE", "mock")

# TOOL_MODE: direct = 进程内直调工具（默认，演示保底）
#            mcp    = Agent 作为 MCP host，经 stdio 协议调用 app/mcp_servers/ 下的服务
TOOL_MODE = os.getenv("TOOL_MODE", "direct")

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
DOMAINS_DIR = os.path.join(BASE_DIR, "app", "domains")
DATA_DIR = os.path.join(BASE_DIR, "app", "data")
SAMPLE_DIR = os.path.join(DATA_DIR, "sample_materials")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
