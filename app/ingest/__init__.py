"""ingest 管线：官网爬取数据 → 结构化领域知识包。

数据流：
  crawler 输出(raw/) → Converter(适配爬取格式) → 中间格式(见 README.md)
  → 校验(Policy schema) → 写入 app/domains/<domain>/policies.json

爬虫数据格式目前未定（由数据方稍后提供）。接入时只需新增一个 Converter
子类实现 raw_item → 中间格式 dict 的转换，注册到 CONVERTERS 即可，
其余校验、写入逻辑全部复用。
"""
from app.ingest.base import Converter, register, validate_policy
from app.ingest.generic_llm import LLMGuideConverter

CONVERTERS = {
    "llm_guide": LLMGuideConverter,   # 通用：{title,url,department,text} 页面正文 → LLM 抽取
}


def get_converter(name: str) -> type[Converter]:
    if name not in CONVERTERS:
        raise KeyError(f"未知转换器 {name}，可选: {list(CONVERTERS)}")
    return CONVERTERS[name]
