"""【4号模块】材料解析与检查：MaterialCheck。
处理层级（PRD 9.1）：L1 文件分类 → L2 字段抽取 → L3 缺失检查 → L4 跨材料一致性检查。

识别路径：
  - api 模式：VLM 单次调用输出 {doc_type, fields} JSON
  - mock 模式：读取上传文件旁的 <同名>.meta.json（演示数据的预置识别结果），
    保证无外网/API Key 时闭环可演示
"""
import os
import json
from app import config, llm
from app.schemas import MaterialRecord, MaterialCheckResult, MaterialIssue

VLM_PROMPT = """你是政务材料识别助手。识别这张图片属于哪类材料，并抽取关键字段。
doc_type 只能是：身份证明 / 学历证明 / 营业执照 / 创业补贴申请表 / 场地租赁合同 / 其他。
常见字段：姓名、证件号码、企业名称、法定代表人、注册日期、毕业院校、学历、租赁方、日期。
输出 JSON：{"doc_type": "...", "fields": {"字段名": "值", ...}}"""

# 归一化：不同证件上的"人名"字段名不同，统一映射后做一致性比对
_NAME_KEYS = ["姓名", "法定代表人", "申请人", "劳动者姓名"]

KNOWN_DOC_TYPES = ["身份证明", "学历证明", "营业执照", "创业补贴申请表", "场地租赁合同", "其他"]


def _parse_meta_sidecar(file_path: str, original_name: str) -> dict | None:
    """mock 识别结果来自 sidecar。上传文件已复制到 uploads/，sidecar 留在原处，
    因此按原始文件名到 sample_materials/ 回退查找。"""
    for candidate in (os.path.splitext(file_path)[0] + ".meta.json",
                      os.path.join(config.SAMPLE_DIR, os.path.splitext(original_name)[0] + ".meta.json")):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                return json.load(f)
    return None


def parse_document(session_id: str, file_path: str, original_name: str) -> MaterialRecord:
    """L1 分类 + L2 字段抽取。"""
    meta = _parse_meta_sidecar(file_path, original_name)
    if config.LLM_MODE == "api":
        try:
            data = llm.vision_extract(file_path, VLM_PROMPT)
            return MaterialRecord(doc_type=data.get("doc_type", "其他"),
                                  filename=original_name,
                                  fields=data.get("fields", {}))
        except Exception as e:      # VLM 失败 → sidecar 兜底，再不行标记不可识别
            if meta:
                return MaterialRecord(doc_type=meta.get("doc_type", "其他"),
                                      filename=original_name,
                                      fields=meta.get("fields", {}))
            return MaterialRecord(doc_type="其他", filename=original_name, status="UNREADABLE",
                                  fields={"_error": str(e)})

    # mock 模式：sidecar 即"识别结果"
    if meta:
        return MaterialRecord(doc_type=meta.get("doc_type", "其他"),
                              filename=original_name, fields=meta.get("fields", {}))
    return MaterialRecord(doc_type="其他", filename=original_name,
                          status="UNREADABLE", fields={})


def _name_of(rec: MaterialRecord) -> str | None:
    for k in _NAME_KEYS:
        v = rec.fields.get(k)
        if v:
            return str(v).strip()
    return None


def check_materials(session: dict, required: list[str]) -> MaterialCheckResult:
    """L3 缺失 + L4 一致性。required 来自候选政策的材料清单并集。"""
    records: list[MaterialRecord] = session["materials"]
    doc_types_present = [r.doc_type for r in records if r.status != "UNREADABLE"]

    # L3 缺失：政策要求但未上传（按 doc_type 粗匹配）
    missing = [m for m in required if m not in doc_types_present and m != "租金支付凭证"]

    # L4 跨材料一致性：同名不同值即冲突（演示用例：身份证"张三" vs 申请表"李四"）
    conflicts: list[MaterialIssue] = []
    name_map: dict[str, list[str]] = {}
    for r in records:
        n = _name_of(r)
        if n:
            name_map.setdefault(n, []).append(r.doc_type)
    if len(name_map) > 1:
        detail = "、".join(f"{docs[0]}为「{n}」" for n, docs in name_map.items())
        conflicts.append(MaterialIssue(type="conflict",
                                       detail=f"跨材料姓名不一致：{detail}",
                                       basis="申请材料须与本人身份证信息一致"))

    # 字段抽取为空但类型可识别 → 待人工确认
    for r in records:
        if r.status != "UNREADABLE" and not r.fields:
            conflicts.append(MaterialIssue(type="manual",
                                           detail=f"{r.doc_type}（{r.filename}）未能抽取到关键字段，请人工核对",
                                           basis="自动识别置信度不足"))

    if any(c.type == "conflict" for c in conflicts):
        readiness = "建议补件后提交"
    elif missing:
        readiness = "建议补件后提交"
    elif records:
        readiness = "可提交"
    else:
        readiness = "无法判断"

    return MaterialCheckResult(materials=records, missing=missing,
                               conflicts=conflicts, readiness=readiness)
