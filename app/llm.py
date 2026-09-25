"""OpenAI 兼容协议的薄封装。mock 模式下不会被调用；api 模式下负责：
1. 主对话（带 tools）
2. 结构化抽取（JSON 输出）
3. VLM 材料识别
换厂商只改 .env 的 BASE_URL / API_KEY / MODEL。"""
import json
import base64
from openai import OpenAI
from app import config


def _client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


def chat(messages: list[dict], tools: list[dict] | None = None,
         model: str | None = None) -> dict:
    """返回 message dict：{content, tool_calls?}"""
    c = _client(config.LLM_BASE_URL, config.LLM_API_KEY)
    resp = c.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=messages,
        tools=tools,
    )
    m = resp.choices[0].message
    return {
        "content": m.content,
        "tool_calls": [tc.model_dump() for tc in (m.tool_calls or [])],
    }


def extract_json(system: str, user: str, model: str | None = None) -> dict:
    """结构化抽取：要求模型只输出 JSON。失败时抛异常由调用方降级。"""
    c = _client(config.LLM_BASE_URL, config.LLM_API_KEY)
    resp = c.chat.completions.create(
        model=model or config.LLM_SMALL_MODEL,
        messages=[
            {"role": "system", "content": system + "\n只输出 JSON，不要输出其他内容。"},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def vision_extract(image_path: str, system: str) -> dict:
    """把图片交给 VLM，返回其输出的 JSON（证件字段抽取）。"""
    c = _client(config.VLM_BASE_URL, config.VLM_API_KEY)
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    data_url = f"data:image/png;base64,{b64}"
    resp = c.chat.completions.create(
        model=config.VLM_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": system + "\n只输出 JSON，不要输出其他内容。"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    )
    text = resp.choices[0].message.content or "{}"
    # 容错：剥掉可能的 ```json 包裹
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text.strip())
