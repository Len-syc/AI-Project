# -*- coding: utf-8 -*-
"""动态方案生成的单元测试：stub 掉 LLM，覆盖四条路径。
用法：python scripts/test_dynamic_plan.py（无需启动服务、无需 API Key）"""
import sys

import app.llm as llm_mod
from app.tools import plan as plan_mod
from app.tools.registry import load_domains
from app.tools.eligibility import run_eligibility

PACK = load_domains()["suzhou_residence"]
PROFILE = {"城市": "苏州", "居住事由": "合法稳定就业", "居住登记月数": 8}
SOURCES = {k: "user" for k in PROFILE}
RESULTS = [run_eligibility("sz-jzz-apply", PROFILE, SOURCES, PACK),
           run_eligibility("sz-jzz-renew", PROFILE, SOURCES, PACK)]
FAILS = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILS.append(name)


VALID = {
    "summary": "登记已满半年且事由符合，先备齐材料线上申领居住证",
    "tasks": [
        {"name": "确认居住登记已满半年", "status": "已完成",
         "next_action": "准备住所与就业证明", "policy_ref": "苏州居住证申领"},
        {"name": "准备住所证明与身份证明", "materials": ["身份证明", "住所证明"],
         "status": "待处理", "next_action": "线上提交申领", "policy_ref": "苏州居住证申领"},
        {"name": "补充已有居住凭证信息以确认签注资格", "status": "未开始",
         "policy_ref": "苏州居住证签注（续期）"},
    ],
}


def run_with(responses):
    """monkeypatch llm.extract_json，按队列返回响应（函数抛异常=模拟坏输出）。"""
    calls = []
    orig = llm_mod.extract_json

    def fake(system, user, model=None):
        calls.append(user)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    llm_mod.extract_json = fake
    try:
        out = plan_mod.generate_plan(RESULTS, PROFILE, PACK, [], mode="api")
    finally:
        llm_mod.extract_json = orig
    return out, calls


print("== 1. LLM 输出合法 → 采用动态方案 ==")
out, calls = run_with([VALID])
check("source=llm", out["source"] == "llm")
check("3 个任务全过校验", len(out["tasks"]) == 3)
check("summary 保留", "居住证" in out["summary"])
check("只调用了一次 LLM", len(calls) == 1)
check("上下文含 skill 攻略", "办事攻略" in calls[0] and "居住登记" in calls[0])
check("上下文含资格结论", "sz-jzz" not in calls[0] and "苏州居住证申领：PASS" in calls[0])

print("\n== 2. LLM 两次都输出坏 JSON → 降级模板 ==")
out, calls = run_with([ValueError("bad json"), ValueError("bad json")])
check("source=template（降级）", out["source"] == "template")
check("模板任务非空", len(out["tasks"]) >= 3, f"{len(out['tasks'])} 步")
check("重试了 2 次", len(calls) == 2)

print("\n== 3. 首次缺 policy_ref → 带反馈重试后成功 ==")
bad = {"tasks": [
    {"name": "步骤一没有依据", "status": "未开始"},
    {"name": "准备材料", "policy_ref": "苏州居住证申领", "status": "待处理"},
    {"name": "提交申请", "policy_ref": "苏州居住证申领", "status": "未开始"},
]}
out, calls = run_with([bad, VALID])
check("重试后 source=llm", out["source"] == "llm")
check("重试请求带错误反馈", "修正" in calls[1] and "policy_ref" in calls[1])
check("校验抓到了缺失依据", "缺少 policy_ref" in calls[1])

print("\n== 4. 引用 FAIL 政策的步骤被拒（依据白名单） ==")
bad2 = {"tasks": [
    {"name": "A", "policy_ref": "苏州居住证申领", "status": "未开始"},
    {"name": "B", "policy_ref": "苏州居住证申领", "status": "未开始"},
    {"name": "C", "policy_ref": "不存在的政策", "status": "未开始"},
]}
out, calls = run_with([bad2, VALID])
check("重试请求指出依据不对应", "未对应任何候选政策" in calls[1])

print("\n== 5. mock 模式直走模板，不调 LLM ==")
calls = []
orig = llm_mod.extract_json
llm_mod.extract_json = lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(AssertionError("不应调用"))
try:
    out = plan_mod.generate_plan(RESULTS, PROFILE, PACK, [], mode="mock")
finally:
    llm_mod.extract_json = orig
check("source=template", out["source"] == "template")
check("未调用 LLM", not calls)

print("\n================")
print("FAILED:", FAILS if FAILS else "无，全部通过 ✅")
sys.exit(1 if FAILS else 0)
