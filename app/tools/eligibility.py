"""【3号模块】资格判断规则引擎：Eligibility。
核心原则（PRD 8.2）：模型负责理解，规则负责约束 —— 运行时判断全部由代码完成，
条件在数据层结构化（policies.json），不依赖 LLM 现场推理，结论天然可回溯。

状态语义：
  PASS          现有信息明确满足
  FAIL          现有信息明确不满足（附差距）
  UNKNOWN       缺少判断所需信息（Agent 应追问）
  MANUAL_REVIEW 条件字段来自系统推断或需主管部门认定
"""
import datetime
from app.schemas import Policy, UserProfile, EligibilityResult, ConditionResult
from app.tools.policy import policy_detail

_NOW = datetime.date.today()


def _check_one(cond, profile: dict, sources: dict) -> ConditionResult:
    field_value = profile.get(cond.field)

    # 字段缺失 → 信息不足，追问用户
    if field_value is None:
        return ConditionResult(condition_id=cond.id, desc=cond.desc, status="UNKNOWN",
                               reason=f"缺少「{cond.field}」信息，需要补充")

    # 布尔条件
    if cond.op == "true":
        ok = field_value is True
    elif cond.op == "false":
        ok = field_value is False
    # 等值/包含
    elif cond.op == "eq":
        ok = field_value == cond.value
    elif cond.op == "neq":
        ok = field_value != cond.value
    elif cond.op == "in":
        ok = field_value in cond.value
    # 毕业年限：当年 - 毕业年份 <= N
    elif cond.op == "within_years":
        try:
            ok = (_NOW.year - int(field_value)) <= int(cond.value)
        except (TypeError, ValueError):
            return ConditionResult(condition_id=cond.id, desc=cond.desc, status="UNKNOWN",
                                   reason=f"「{cond.field}」格式无法解析")
    # 数值/字符串比较（社保月数、注册时间 "YYYY-MM" 可按字典序比较）
    elif cond.op in ("gte", "lte"):
        try:
            ok = (field_value >= cond.value) if cond.op == "gte" else (field_value <= cond.value)
        except TypeError:
            return ConditionResult(condition_id=cond.id, desc=cond.desc, status="UNKNOWN",
                                   reason=f"「{cond.field}」类型无法比较")
    else:
        ok = False

    if not ok:
        gap = cond.desc
        return ConditionResult(condition_id=cond.id, desc=cond.desc, status="FAIL",
                               reason=f"暂不满足：{gap}")

    # 条件本身满足，但该字段来自系统推断 → 不能作为 PASS 唯一依据（PRD 6.2）
    if cond.infer_only or sources.get(cond.field) == "inferred":
        return ConditionResult(condition_id=cond.id, desc=cond.desc, status="MANUAL_REVIEW",
                               reason=f"「{cond.field}」来自系统推断或需主管部门认定，请人工确认")

    return ConditionResult(condition_id=cond.id, desc=cond.desc, status="PASS", reason="已满足")


_RANK = {"FAIL": 0, "MANUAL_REVIEW": 1, "UNKNOWN": 2, "PASS": 3}


def run_eligibility(policy_id: str, profile: dict, sources: dict) -> EligibilityResult:
    policy = policy_detail(policy_id)
    if policy is None:
        return EligibilityResult(policy_id=policy_id, policy_name=policy_id,
                                 overall="UNKNOWN", conditions=[],
                                 gap="政策库中不存在该政策")
    results = [_check_one(c, profile, sources) for c in policy.conditions]
    worst = min((r.status for r in results), key=lambda s: _RANK[s])
    gap = "；".join(r.reason for r in results if r.status in ("FAIL", "UNKNOWN")) \
        if worst in ("FAIL", "UNKNOWN") else ""
    return EligibilityResult(policy_id=policy.id, policy_name=policy.name,
                             overall=worst, conditions=results, gap=gap)
