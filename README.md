# 政务办事智能辅助 Agent · MVP

> 面向高校毕业生就业创业场景的政务办事 Agent：理解办事目标 → 补全用户画像 → 检索政策 → 逐条资格判断 → 生成办理方案 → 材料上传与预检 → 预检报告。
> 对应《政务办事智能辅助Agent_PRD_V0.1》与《分工方案v1》的可运行参考实现（五人分工 → 五个模块目录）。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动（默认 mock 模式，无需任何 API Key，离线可跑）
python -m uvicorn app.main:app --port 8765

# 3. 打开演示页
#    http://127.0.0.1:8765/
```

接入真实 LLM：复制 `.env.example` 为 `.env`，改 `LLM_MODE=api` 并填入 Key（任何 OpenAI 兼容厂商均可，DeepSeek / 智谱 / 通义 已验证协议兼容）。mock/api 两种模式走同一条链路，只切换"画像抽取 / 材料识别"两处的实现。

## 演示脚本（约 3 分钟）

1. 打开页面，点 **一键演示（创业）** → Agent 抽取画像，若信息不足会**主动追问**
2. 补全信息后自动触发分析：右侧"政策匹配"展示**逐条条件判断 + 原因**，"办理方案"展示带前置顺序的步骤
3. 切到"材料中心"，点 **一键上传演示样本（3 件）** → 自动识别类型、抽取字段，发现**缺失材料**
4. 点 **生成报告** → 预检报告：已通过 / 待修改（**跨材料姓名冲突：张三 vs 李四**）/ 缺失 / 边界声明

其他可演示点：非苏州目标会明确提示"仅覆盖苏州"（不编造）；`困难情形` 字段缺失触发"信息不足 → 追问"；系统推断字段会触发"待人工确认"。

## 架构与分工对应

```
前端(5号)  web/index.html          Vue3 + Element Plus 单文件页（SSE 实时轨迹 + 五个结果面板）
   │
Agent(1号) app/main.py             FastAPI 入口 / 路由 / 静态托管
           app/agent/pipeline.py   状态机主流程（collect_profile → analyzing → await_material → report）
           app/store.py            会话存储（内存版，可换 SQLite）
           app/llm.py              OpenAI 兼容协议薄封装（chat / 结构化抽取 / VLM）
   │
Tools:
  2号  app/tools/policy.py         PolicySearch / PolicyDetail   数据: app/data/policies.json
  3号  app/tools/eligibility.py    规则引擎（PASS/FAIL/UNKNOWN/MANUAL_REVIEW + 逐条原因）
       app/tools/plan.py           办理规划（政策流程模板 + requires 拓扑排序）
  4号  app/tools/material.py       材料识别（api: VLM / mock: sidecar）+ 缺失 + 跨材料一致性
```

**核心设计原则**（PRD 8.2"模型负责理解，规则负责约束"）：流程骨架写死保证演示稳定；资格判断 100% 走代码规则引擎，条件结构化存于 `policies.json`，结论可回溯；LLM 只负责画像抽取（api 模式）与措辞。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent/chat` | 主对话。SSE 流式返回 `stage_change` / `tool_call` / `tool_result` / `message` / `state` 事件 |
| POST | `/api/materials/upload` | multipart 上传（`session_id` + `file`），返回识别结果 + 预检 + 全量快照 |
| GET | `/api/agent/session/{sid}` | 会话快照（前端刷新） |
| GET | `/api/policies` | 政策库列表（调试用） |
| GET | `/api/health` | 健康检查 + 当前 LLM 模式 |

启动后访问 `/docs` 可查看自动生成的 OpenAPI 文档（可导入 ApiFox，作为《接口规范文档》的底稿）。

## 测试

```bash
python scripts/e2e_test.py http://127.0.0.1:8765
```

28 项断言：画像抽取、追问逻辑、PolicySearch→Eligibility→Plan 调用链、四态资格结果、材料识别、跨材料冲突、缺失清单、报告生成、非苏州边界（不编造）。

## 演示数据说明（重要）

- `app/data/policies.json`：政策要素结构参照官方政策常见形态整理，**金额/条件/文号均为演示占位**，未逐条核实。
- `app/data/sample_materials/`：三张 PIL 合成样本图（带"演示样本"水印，非真实证照），其中申请表**故意**填了不同姓名用于演示冲突检查；每张图旁的 `.meta.json` 是 mock 模式的"识别结果"。
- 演示数据已内置，不涉及任何真实个人隐私。

## 上线前待办（按人认领）

| 人 | 待办 |
|---|---|
| 2号 | 逐条溯源 policies.json：金额、条件、有效期、官方原文链接替换 `source` 字段；补充更多区县/县级市差异 |
| 3号 | 扩充规则算子（如经营时长、年龄区间）；为 UNKNOWN 状态接"继续追问"闭环 |
| 4号 | api 模式实测 VLM 抽取准确率；增加更多材料类型与一致性规则（日期、企业名称） |
| 5号 | 单文件页迁移到 Vite + Vue3 工程（组件拆分）；移动端适配；对接真实 API 前先用本页的假数据模式 |
| 1号 | 会话持久化（store.py 换 SQLite）；api 模式回归 e2e；错误码表与《接口规范文档》定稿 |

## 已知边界

- 会话存内存，服务重启即清空（演示无影响）
- mock 模式的"画像抽取"是关键词规则，仅覆盖演示话术；api 模式由 LLM 结构化抽取，语料外表达也能兜住
- 材料识别 mock 模式依赖 sidecar 文件，任意新图片会标记为"无法识别 → 请人工核对"（这正是 PRD 的兜底路径）
