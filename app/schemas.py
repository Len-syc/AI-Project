"""统一数据结构。所有接口的字段、状态枚举以本文件为准（对应《接口规范文档》的代码化）。"""
from typing import Optional, Literal
from pydantic import BaseModel, Field

# ---------- 枚举 ----------
EligibilityStatus = Literal["PASS", "FAIL", "UNKNOWN", "MANUAL_REVIEW", "NOT_APPLICABLE"]
FieldSource = Literal["user", "inferred", "system"]
MaterialStatus = Literal["OK", "FIELD_ERROR", "CONFLICT", "UNREADABLE"]


# ---------- 用户画像 ----------
class UserProfile(BaseModel):
    城市: Optional[str] = None
    学历: Optional[str] = None            # 大专/本科/硕士/博士
    毕业年份: Optional[int] = None
    状态: Optional[str] = None            # 就业/创业/灵活就业/待业
    是否首次创业: Optional[bool] = None
    企业注册地: Optional[str] = None      # 苏州下辖区县
    企业注册时间: Optional[str] = None    # 如 "2026-03"
    社保缴纳月数: Optional[int] = None


# ---------- 政策 ----------
class PolicyCondition(BaseModel):
    id: str
    desc: str                              # 人类可读的条件描述
    field: str                             # 对应 UserProfile 字段名
    op: Literal["eq", "neq", "gte", "lte", "in", "true", "false",
                "within_years", "months_gte"]
    value: object = None
    infer_only: bool = False               # True=该字段仅系统推断可得时 → MANUAL_REVIEW


class Policy(BaseModel):
    id: str
    name: str
    department: str
    applies_to: str
    amount: str
    valid_until: str
    source: str                            # 官方来源（MVP 阶段为待核实占位）
    conditions: list[PolicyCondition]
    materials: list[str]
    process: list[str]
    requires: list[str] = []               # 前置政策 id
    keywords: list[str] = []


# ---------- 资格判断 ----------
class ConditionResult(BaseModel):
    condition_id: str
    desc: str
    status: EligibilityStatus
    reason: str


class EligibilityResult(BaseModel):
    policy_id: str
    policy_name: str
    overall: EligibilityStatus
    conditions: list[ConditionResult]
    gap: str = ""                          # FAIL/UNKNOWN 时的差距说明


# ---------- 办理方案 ----------
class PlanTask(BaseModel):
    name: str
    precondition: str = ""
    materials: list[str] = []
    status: Literal["已完成", "待处理", "未开始"] = "未开始"
    next_action: str = ""
    policy_ref: str = ""


# ---------- 材料 ----------
class MaterialIssue(BaseModel):
    type: Literal["missing", "conflict", "field_error", "manual"]
    detail: str
    basis: str = ""                        # 依据：政策名/条款


class MaterialRecord(BaseModel):
    doc_type: str
    filename: str
    status: MaterialStatus = "OK"
    fields: dict = {}


class MaterialCheckResult(BaseModel):
    materials: list[MaterialRecord]
    missing: list[str]
    conflicts: list[MaterialIssue]
    readiness: Literal["可提交", "建议补件后提交", "无法判断"] = "无法判断"


# ---------- Agent 会话 ----------
Stage = Literal["collect_profile", "analyzing", "await_material", "report"]


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(..., description="用户本轮输入")


class SSEEvent(BaseModel):
    event: Literal["stage_change", "tool_call", "tool_result", "message", "state", "done"]
    data: dict
