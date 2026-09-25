"""【1号模块】Agent 主流程：状态机 + 工具编排 + SSE 事件流。

阶段：collect_profile → analyzing → await_material → report
原则：流程骨架写死（保证演示稳定），LLM 只做画像抽取与措辞（api 模式），
判断全部走规则引擎（3号），检索走政策库（2号），材料走 VLM/sidecar（4号）。
"""
import json
import asyncio
from typing import AsyncGenerator
from app.schemas import UserProfile
from app.agent.profile_extract import extract_profile
from app.tools import policy as policy_tool
from app.tools import eligibility as elig_tool
from app.tools import plan as plan_tool
from app.tools import material as material_tool
from app import config

STATUS_LABEL = {"PASS": "✅ 符合", "FAIL": "⛔ 暂不满足", "UNKNOWN": "❓ 信息不足",
                "MANUAL_REVIEW": "🟡 待人工确认"}

# 追问顺序：先问判断分支依赖的字段
QUESTION_FLOW = [
    ("城市", "你准备在哪个城市就业/创业？（当前演示知识库覆盖苏州）"),
    ("学历", "你的学历是？（大专 / 本科 / 硕士 / 博士）"),
    ("毕业年份", "你是哪一年毕业的？（可直接说\"2026届\"）"),
    ("状态", "你目前的状态是：就业、创业、灵活就业，还是待业？"),
    ("是否首次创业", "你是第一次创业吗？"),
    ("企业注册地", "企业注册在苏州哪个区？（如工业园区、姑苏区、昆山等）"),
]

FORCE_ANALYZE_WORDS = ["开始分析", "帮我查", "就这些", "没有了", "直接分析", "先分析"]


def _required_fields(session: dict) -> list[str]:
    goal, profile = session["goal"], session["profile"]
    base = ["城市", "学历", "毕业年份", "状态"]
    if "创业" in goal or "开公司" in goal or profile.get("状态") == "创业":
        base += ["是否首次创业"]
        # 非苏州目标没有追问注册地的意义（演示库只覆盖苏州）
        if profile.get("城市") in (None, "苏州"):
            base += ["企业注册地"]
    return base


def _merge_profile(session: dict, extracted: dict) -> list[str]:
    """合并抽取结果，返回新补齐的字段名。"""
    updated = []
    profile = session["profile"]
    for k, v in extracted.items():
        if v is not None and profile.get(k) is None:
            profile[k] = v
            session["profile_sources"][k] = "user"
            updated.append(k)
    return updated


def _next_questions(session: dict, required: list[str]) -> list[str]:
    profile = session["profile"]
    missing = [f for f in QUESTION_FLOW if f[0] in required and profile.get(f[0]) is None]
    return [q for _, q in missing[:2]]      # 每轮最多追问 2 个


def _emit_state(session: dict) -> tuple[str, dict]:
    return "state", _snapshot(session)


def _snapshot(session: dict) -> dict:
    return {
        "session_id": session["session_id"],
        "stage": session["stage"],
        "goal": session["goal"],
        "profile": session["profile"],
        "profile_sources": session["profile_sources"],
        "policies": [policy_tool.policy_detail(pid).model_dump()
                     for pid in session["policy_ids"] if policy_tool.policy_detail(pid)],
        "eligibility": [e.model_dump() for e in session["eligibility"]],
        "plan": [t.model_dump() for t in session["plan"]],
        "materials": [m.model_dump() for m in session["materials"]],
        "material_check": session["material_check"].model_dump() if session["material_check"] else None,
        "report": session["report"],
    }


def _analyze(session: dict) -> tuple[str, list[tuple[str, dict]]]:
    """核心编排：检索 → 资格 → 规划。返回 (回复文本, SSE事件列表)。"""
    events: list[tuple[str, dict]] = []
    profile, sources = session["profile"], session["profile_sources"]

    events.append(("stage_change", {"stage": "analyzing", "label": "正在分析你的情况"}))

    # ---- PolicySearch（2号）----
    events.append(("tool_call", {"tool": "PolicySearch",
                                 "args": {"goal": session["goal"], "city": profile.get("城市")}}))
    found = policy_tool.policy_search(session["goal"], city=profile.get("城市"))
    session["policy_ids"] = [p.id for p in found]
    events.append(("tool_result", {"tool": "PolicySearch",
                                   "summary": f"命中 {len(found)} 条政策：{'、'.join(p.name for p in found) or '无'}"}))
    if not found:
        session["stage"] = "report"
        city = profile.get("城市") or "该城市"
        return (f"抱歉，当前演示知识库仅覆盖【苏州】的高校毕业生就业创业政策，"
                f"暂时没有{city}的可靠政策信息。为保证不误导你，我不做猜测性推荐。\n"
                f"你可以输入\"我想在苏州创业\"重新体验完整流程。"), events + [("state", _snapshot(session))]

    # ---- Eligibility（3号）----
    events.append(("stage_change", {"stage": "analyzing", "label": "正在逐条判断资格"}))
    session["eligibility"] = []
    for p in found:
        events.append(("tool_call", {"tool": "Eligibility",
                                     "args": {"policy": p.name, "conditions": len(p.conditions)}}))
        r = elig_tool.run_eligibility(p.id, profile, sources)
        session["eligibility"].append(r)
        events.append(("tool_result", {"tool": "Eligibility",
                                       "summary": f"{p.name} → {STATUS_LABEL[r.overall]}"}))

    # ---- Plan（3号）----
    events.append(("stage_change", {"stage": "analyzing", "label": "正在生成办理方案"}))
    events.append(("tool_call", {"tool": "Plan", "args": {"policies": len(found)}}))
    session["plan"] = plan_tool.build_plan(session["eligibility"])
    events.append(("tool_result", {"tool": "Plan",
                                   "summary": f"生成 {len(session['plan'])} 个办理步骤"}))

    session["stage"] = "await_material"

    # ---- 组织回复 ----
    lines = [f"根据你的情况（{_profile_brief(profile)}），从政策库中匹配到 {len(found)} 项相关政策：", ""]
    for i, e in enumerate(session["eligibility"], 1):
        lines.append(f"{i}. 【{e.policy_name}】{STATUS_LABEL[e.overall]}")
        if e.gap:
            lines.append(f"   差距：{e.gap}")
        if e.overall == "MANUAL_REVIEW":
            lines.append("   注意：存在需人工确认的条件（系统推断信息不作为结论依据），建议向主管部门核实。")
    lines += ["", "建议办理顺序已生成（见右侧\"办理方案\"）。", ""]
    needed = sorted({m for t in session["plan"] for m in t.materials})
    if needed:
        lines.append(f"需要准备的材料：{'、'.join(needed)}。")
        lines.append("请上传材料图片（演示样本见项目 app/data/sample_materials/），我会自动预检缺失项和信息冲突；"
                     "也可以直接输入\"生成报告\"查看当前预检结论。")
    text = "\n".join(lines)
    events.append(("state", _snapshot(session)))
    return text, events


def _profile_brief(profile: dict) -> str:
    parts = []
    if profile.get("毕业年份"):
        parts.append(f"{profile['毕业年份']}届")
    if profile.get("学历"):
        parts.append(profile["学历"])
    if profile.get("城市"):
        parts.append(profile["城市"])
    if profile.get("状态"):
        parts.append(profile["状态"])
    return "·".join(parts) or "信息收集中"


def build_report(session: dict) -> dict:
    """预检报告（PRD 9.2 结构）。"""
    required = sorted({m for t in session["plan"] for m in t.materials})
    check = material_tool.check_materials(session, required)
    session["material_check"] = check

    passed = [m.doc_type for m in check.materials
              if m.status == "OK" and m.doc_type not in [i.detail for i in check.conflicts]]
    to_fix = [c.detail for c in check.conflicts if c.type == "conflict"]
    manual = [c.detail for c in check.conflicts if c.type == "manual"]

    report = {
        "overall": check.readiness,
        "passed": passed,
        "to_fix": to_fix,
        "missing": check.missing,
        "manual_review": manual,
        "eligibility_summary": [
            {"policy": e.policy_name, "status": e.overall, "label": STATUS_LABEL[e.overall]}
            for e in session["eligibility"]],
    }
    session["report"] = report
    session["stage"] = "report"
    return report


def _report_text(report: dict) -> str:
    lines = ["【材料预检报告】", f"整体状态：{report['overall']}", ""]
    if report["passed"]:
        lines.append("✅ 已通过：" + "、".join(report["passed"]))
    if report["to_fix"]:
        lines.append("⚠️ 待修改：" + "；".join(report["to_fix"]))
    if report["missing"]:
        lines.append("❌ 缺失材料：" + "、".join(report["missing"]))
    if report["manual_review"]:
        lines.append("🟡 待人工确认：" + "；".join(report["manual_review"]))
    lines += ["", "说明：本报告为辅助预检，不构成正式审批意见，最终以主管部门审核为准。"]
    return "\n".join(lines)


async def handle_chat(session: dict, message: str) -> AsyncGenerator[str, None]:
    """处理一轮对话，yield SSE 格式事件。"""

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    session["messages"].append({"role": "user", "content": message})
    session["turns"] += 1
    yield sse("stage_change", {"stage": session["stage"], "label": "正在理解你的输入"})

    # 0. 首条消息 = 办事目标
    if not session["goal"]:
        session["goal"] = message

    reply = ""

    if session["stage"] == "collect_profile":
        extracted = extract_profile(message, config.LLM_MODE)
        _merge_profile(session, extracted)
        required = _required_fields(session)
        questions = _next_questions(session, required)
        force = any(w in message for w in FORCE_ANALYZE_WORDS)

        if not questions or force:
            reply, events = _analyze(session)
            for e, d in events:
                yield sse(e, d)
        else:
            reply = "好的，为了准确判断你能申请哪些政策，我需要确认几个信息：\n" + \
                    "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
            yield sse("state", _snapshot(session))

    elif session["stage"] == "await_material":
        if "报告" in message:
            report = build_report(session)
            reply = _report_text(report)
            yield sse("stage_change", {"stage": "report", "label": "已生成预检报告"})
            yield sse("state", _snapshot(session))
        else:
            required = sorted({m for t in session["plan"] for m in t.materials})
            missing = [m for m in required
                       if m not in [x.doc_type for x in session["materials"]]]
            reply = "请在下方\"材料中心\"上传材料图片，我会自动识别并预检。" \
                    f"（还缺：{'、'.join(missing) if missing else '无，可输入\"生成报告\"'}）"
            yield sse("state", _snapshot(session))

    elif session["stage"] == "report":
        if "重新" in message or "再来" in message:
            from app.store import new_session
            fresh = new_session()
            session.update(fresh)
            reply = "已重置会话。请描述你的办事目标，例如：我是2026届本科毕业生，准备在苏州创业，有什么政策可以申请？"
            yield sse("state", _snapshot(session))
        else:
            reply = "预检报告已生成（见右侧）。你可以继续上传补件材料后输入\"生成报告\"重新预检，或输入\"重新开始\"重置演示。"
            yield sse("state", _snapshot(session))

    session["messages"].append({"role": "assistant", "content": reply})
    yield sse("message", {"role": "assistant", "content": reply})
    yield sse("done", {})
