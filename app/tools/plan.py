"""【3号模块】办理规划：Plan。
输入：候选政策 + 资格结果。输出：按前置关系排序的任务列表。
MVP 用「政策流程模板 + requires 依赖拓扑排序」，不依赖 LLM，保证演示稳定。"""
from app.schemas import Policy, PlanTask, EligibilityResult
from app.tools.policy import policy_detail, load_policies


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


def build_plan(eligibility_results: list[EligibilityResult],
               materials_uploaded: list[str] | None = None) -> list[PlanTask]:
    materials_uploaded = materials_uploaded or []
    tasks: list[PlanTask] = []

    # 只对"可办"（PASS / MANUAL_REVIEW）的政策生成路径；
    # UNKNOWN 的留待补全信息，FAIL 的不出现在方案里（差距已在资格面板说明）
    candidates = [policy_detail(r.policy_id) for r in eligibility_results
                  if r.overall in ("PASS", "MANUAL_REVIEW")]
    candidates = [p for p in candidates if p]
    candidates = _topo_sort(candidates)

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

    # 材料准备任务：候选政策所需材料去重合并
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
    return tasks
