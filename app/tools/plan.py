"""【3号模块】办理规划：Plan（双层实现）。

- llm（api 模式）：政策要点 + skill 攻略 + 资格结果 + 用户画像 → LLM 动态生成
  个性化方案。**动态生成，结构化交付**：输出必须过 PlanTask schema 校验、
  每步必须带政策依据；校验失败带错误反馈重试一次，仍失败降级模板。
- template（mock 模式 / 兜底）：政策流程模板 + requires 拓扑排序，离线稳定。

原则（PRD 8.2）：模型负责理解，规则负责约束，来源负责证明。
方案是"建议"可以动态生成；资格判断是"结论"，始终走规则引擎（eligibility.py）。
"""
from app import config, llm
from app.schemas import Policy, PlanTask, EligibilityResult
from app.tools.policy import policy_detail
from app.tools.registry import DomainPack

_STATUSES = {"已完成", "待处理", "未开始"}


# ---------------- 模板路径（兜底 / mock） ----------------

def _topo_sort(policies: list[Policy]) -> list[Policy]:
    done, ordered = set(), []
    pending = list(policies)
    while pending:
        progressed = False
        for p in list(pending):
            if all(req in done for req in p.requires):
                ordered.append(p)
                done.add(p.id)
                pending.remove(p)
                progressed = True
        if not progressed:          # 环或引用缺失：按原序兜底
            ordered.extend(pending)
            break
    return ordered


def _template_plan(eligibility_results: list[EligibilityResult],
                   materials_uploaded: list[str]) -> tuple[list[PlanTask], str]:
    """只对"可办"（PASS / MANUAL_REVIEW）的政策生成路径；UNKNOWN 留待补信息，
    FAIL 不进方案（差距已在资格面板说明）。"""
    candidates = [policy_detail(r.policy_id) for r in eligibility_results
                  if r.overall in ("PASS", "MANUAL_REVIEW")]
    candidates = [p for p in candidates if p]
    candidates = _topo_sort(candidates)

    tasks: list[PlanTask] = []
    for p in candidates:
        for i, step in enumerate(p.process):
            tasks.append(PlanTask(
                name=step,
                precondition=p.process[i - 1] if i > 0 else "",
                materials=[],
                status="已完成" if i == 0 else "未开始",
                next_action=p.process[i + 1] if i + 1 < len(p.process) else "提交申请并跟踪进度",
                policy_ref=f"{p.name}（{p.department}）",
            ))

    needed = []
    for p in candidates:
        for m in p.materials:
            if m not in needed:
                needed.append(m)
    if needed:
        have = set(materials_uploaded)
        tasks.append(PlanTask(
            name="准备并上传申请材料",
            precondition="确认符合的候选政策",
            materials=needed,
            status="待处理" if have != set(needed) else "已完成",
            next_action="上传材料后由系统预检缺失与冲突" if have != set(needed) else "查看材料预检报告",
            policy_ref="；".join(p.name for p in candidates),
        ))
    return tasks, ""


# ---------------- 动态路径（api 模式） ----------------

_PLAN_SYSTEM = """你是政务办事规划助手。基于给定的政策要点、资格判断结果、用户画像和办事攻略，动态生成个性化办理方案。
规则：
1. 只依据给定材料生成步骤，不得编造政策、条件或材料；每个步骤的 policy_ref 必须注明依据的政策名称
2. 结合用户画像个性化：已完成的前置环节（如资格初判）标"已完成"；用户已上传的材料不再安排准备步骤
3. 体现政策间的前置依赖顺序（攻略中有顺序建议）
4. 对"信息不足"的事项，安排一个"补充XX信息/材料"的步骤，说明补充后可解锁什么
5. status 只能取：已完成 / 待处理 / 未开始
6. 输出 JSON：{"summary": "一句话方案摘要（不超过60字）", "tasks": [{"name": "...", "precondition": "...", "materials": ["..."], "status": "...", "next_action": "...", "policy_ref": "..."}]}
7. 步骤数量控制在 4~15 步"""


def _policy_block(p: Policy, requires_names: dict[str, str]) -> str:
    conds = "；".join(c.desc for c in p.conditions)
    reqs = "、".join(requires_names.get(r, r) for r in p.requires) or "无"
    return (f"## {p.name}\n"
            f"部门：{p.department}｜适用对象：{p.applies_to}｜金额：{p.amount}｜有效期至：{p.valid_until}\n"
            f"资格条件：{conds}\n"
            f"所需材料：{'、'.join(p.materials)}\n"
            f"参考流程：{' → '.join(p.process)}\n"
            f"前置事项：{reqs}\n"
            f"来源：{p.source}")


def _build_context(eligibility_results: list[EligibilityResult], profile: dict,
                   pack: DomainPack, materials_uploaded: list[str]) -> str:
    by_id = {p.id: p for p in pack.policies}
    requires_names = {pid: by_id[pid].name for pid in by_id}

    prof = "；".join(f"{k}={v}" for k, v in profile.items() if v is not None) or "（未提供）"
    lines = [f"【用户画像】{prof}",
             f"【已上传材料】{'、'.join(materials_uploaded) or '无'}", ""]

    lines.append("【资格判断结果（规则引擎结论，不可更改）】")
    for r in eligibility_results:
        gap = f"（差距：{r.gap}）" if r.gap else ""
        lines.append(f"- {r.policy_name}：{r.overall}{gap}")
    lines.append("")

    ok_ids = [r.policy_id for r in eligibility_results if r.overall in ("PASS", "MANUAL_REVIEW")]
    unk = [r for r in eligibility_results if r.overall == "UNKNOWN"]
    lines.append("【候选政策要点（可规划进方案）】")
    for pid in ok_ids:
        if pid in by_id:
            lines.append(_policy_block(by_id[pid], requires_names))
    if unk:
        lines.append("【信息不足事项（安排补充信息步骤）】")
        for r in unk:
            lines.append(f"- {r.policy_name}：{r.gap}")
    lines.append("")
    lines.append("【办事攻略（领域经验，供排序与避坑参考）】")
    lines.append(pack.skill[:2500] or "（无）")
    return "\n".join(lines)


def _validate_plan(data, candidate_names: set[str]) -> tuple[list[PlanTask], list[str]]:
    """结构化校验：交付前把 LLM 输出压进 PlanTask schema。返回 (任务, 错误列表)。"""
    errors = []
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        return [], ["输出缺少 tasks 数组"]
    tasks: list[PlanTask] = []
    for i, t in enumerate(data["tasks"][:30]):
        if not isinstance(t, dict):
            errors.append(f"第{i+1}步不是对象")
            continue
        name = str(t.get("name", "")).strip()
        ref = str(t.get("policy_ref", "")).strip()
        if not name:
            errors.append(f"第{i+1}步缺少 name")
            continue
        if not ref:
            errors.append(f"第{i+1}步（{name[:20]}）缺少 policy_ref（必须注明依据政策）")
            continue
        status = t.get("status") if t.get("status") in _STATUSES else "未开始"
        materials = [str(m) for m in (t.get("materials") or []) if str(m).strip()]
        tasks.append(PlanTask(
            name=name[:60],
            precondition=str(t.get("precondition", "")).strip()[:60],
            materials=materials,
            status=status,
            next_action=str(t.get("next_action", "")).strip()[:80],
            policy_ref=ref[:80],
        ))
    if len(tasks) < 3:
        errors.append(f"有效步骤仅 {len(tasks)} 步（至少 3 步）")
    # 依据可追溯：policy_ref 至少提到一个候选政策名（或"综合"）
    for t in tasks:
        if t.policy_ref and not any(n[:6] in t.policy_ref for n in candidate_names) and "综合" not in t.policy_ref:
            errors.append(f"步骤「{t.name[:20]}」的依据「{t.policy_ref[:30]}」未对应任何候选政策")
            break
    return tasks, errors


def generate_plan(eligibility_results: list[EligibilityResult], profile: dict,
                  pack: DomainPack, materials_uploaded: list[str],
                  mode: str) -> dict:
    """入口。返回 {"tasks": [...], "source": "llm"|"template", "summary": str}。"""
    if mode != "api":
        tasks, _ = _template_plan(eligibility_results, materials_uploaded)
        return {"tasks": tasks, "source": "template", "summary": ""}

    # 依据白名单：PASS/MANUAL_REVIEW 可规划步骤，UNKNOWN 可安排补充信息步骤；FAIL 不可引用
    candidates = [policy_detail(r.policy_id, pack) for r in eligibility_results
                  if r.overall in ("PASS", "MANUAL_REVIEW", "UNKNOWN")]
    candidate_names = {p.name for p in candidates if p}
    context = _build_context(eligibility_results, profile, pack, materials_uploaded)

    feedback = ""
    for attempt in (1, 2):                      # 校验失败带错误反馈重试一次
        try:
            data = llm.extract_json(_PLAN_SYSTEM, context + feedback,
                                    model=config.LLM_MODEL)
        except Exception:
            feedback = f"\n\n【上次输出无法解析为 JSON，请严格按 JSON 格式重试】({attempt}/2)"
            continue
        tasks, errors = _validate_plan(data, candidate_names)
        if not errors:
            summary = str(data.get("summary", "")).strip()[:80]
            return {"tasks": tasks, "source": "llm", "summary": summary}
        feedback = ("\n\n【上次输出存在以下问题，请修正后重新输出完整 JSON】\n- "
                    + "\n- ".join(errors[:5]))

    tasks, _ = _template_plan(eligibility_results, materials_uploaded)   # 降级
    return {"tasks": tasks, "source": "template", "summary": ""}
