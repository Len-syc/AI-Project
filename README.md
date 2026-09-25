# 政务办事智能辅助 Agent · MVP

> 面向"普通人办政事"的通用政务办事 Agent：理解办事目标 → 识别所属领域 → 补全用户画像 → 检索政策/事项 → 逐条资格判断 → 生成办理方案 → 材料上传与预检 → 预检报告。
> 知识库为**领域数据包**（画像 schema + 结构化事项），未来由官网爬取数据经 `app/ingest/` 管线灌入——新增办事领域**不改代码，只加数据**。
> 对应《政务办事智能辅助Agent_PRD_V0.1》的可运行参考实现。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 启动（默认 mock 模式，无需任何 API Key，离线可跑）
python -m uvicorn app.main:app --port 8765

# 3. 打开演示页
#    http://127.0.0.1:8765/
```

接入真实 LLM：复制 `.env.example` 为 `.env`，改 `LLM_MODE=api` 并填入 Key（任何 OpenAI 兼容厂商均可）。mock/api 两种模式走同一条链路，只切换"画像抽取 / 材料识别 / 领域路由"等处的实现。

工具调用方式：`.env` 里 `TOOL_MODE=direct`（默认，进程内直调）或 `TOOL_MODE=mcp`（Agent 作为 MCP host，经 stdio 调用 3 个 FastMCP 工具服务）。MCP 服务也可独立运行，供任意 MCP 客户端复用：`python app/mcp_servers/policy_server.py`。

## 演示脚本（约 3 分钟）

1. 打开页面，点 **演示：创业补贴** 或 **演示：居住证** → Agent 自动识别领域、抽取画像，信息不足时**主动追问**
2. 触发分析：右侧"政策匹配"展示**逐条条件判断 + 原因**，"办理方案"展示带前置顺序的步骤
3. 切到"材料中心"，点 **一键上传演示样本（3 件）** → 自动识别类型、抽取字段，发现**缺失材料**
4. 点 **生成报告** → 预检报告：已通过 / 待修改（**跨材料姓名冲突：张三 vs 李四**）/ 缺失 / 边界声明

其他可演示点：说"我想办点事"会**列出可选领域**引导选择；非苏州目标明确提示"仅覆盖"（不编造）；增强字段缺失显示"信息不足"；系统推断字段触发"待人工确认"。

## 架构

```
前端(5号)  web/index.html          Vue3 + Element Plus 单文件页（SSE 实时轨迹 + 五个结果面板，领域无关）
   │
Agent(1号) app/main.py             FastAPI 入口 / 路由 / 静态托管
           app/agent/pipeline.py   状态机主流程（collect_profile →〔await_domain〕→ analyzing → await_material → report）
           app/tools/registry.py   领域包注册表：加载 domains/ + 意图路由
           app/store.py            会话存储（内存版，可换 SQLite）
           app/llm.py              OpenAI 兼容协议薄封装（chat / 结构化抽取 / VLM）
   │
知识层（数据，不是代码）：
  app/domains/<domain>/domain.json    画像 schema：字段、追问话术、ask_if 条件、抽取规则、必填标记
  app/domains/<domain>/policies.json  结构化事项：条件(可判断)/材料/流程/前置关系/官方来源
  app/domains/<domain>/skill.md       办事攻略：办理顺序经验、材料雷区、时间窗口（注入规划上下文）
  ├─ suzhou_startup    高校毕业生就业创业（6 条事项）
  └─ suzhou_residence  居住证办理（2 条事项）
   │
Tools（领域无关，且同时以 MCP 服务形式对外暴露）：
  2号  app/tools/policy.py         PolicySearch / PolicyDetail（按域检索）
  3号  app/tools/eligibility.py    规则引擎（PASS/FAIL/UNKNOWN/MANUAL_REVIEW + 逐条原因）
       app/tools/plan.py           办理规划【双层】：api 模式 = LLM 读政策要点+skill攻略+资格结果
                                   动态生成，结构化校验失败重试一次后降级；mock = 流程模板+拓扑排序
  4号  app/tools/material.py       材料识别（api: VLM / mock: sidecar）+ 缺失 + 跨材料一致性
   │
MCP 服务层（app/mcp_servers/，FastMCP · stdio 传输，任意 MCP 客户端可连）：
  policy_server.py（2号）            policy_search / policy_detail / list_domains
  eligibility_plan_server.py（3号）  check_eligibility / generate_plan
  material_server.py（4号）          parse_document / check_materials
  TOOL_MODE=direct（默认）           进程内直调，演示保底
  TOOL_MODE=mcp                      Agent 作为 MCP host，经 stdio 协议调用上述服务
                                     （app/mcp_client.py 专职后台任务持有连接 + app/agent/tool_gateway.py 网关）
   │
知识接入管线（爬虫数据 → 知识包）：
  app/ingest/   中间格式规范 + 转换器接口 + 校验 + CLI（详见 app/ingest/README.md）
```

**核心设计原则**（PRD 8.2"模型负责理解，规则负责约束，来源负责证明"）：

- 流程骨架写死保证演示稳定；**资格判断 100% 走代码规则引擎**（结论不可动态化），结论可回溯
- **办理方案动态生成、结构化交付**：api 模式下 LLM 通读候选政策要点 + skill 攻略 + 规则引擎的资格结论，
  输出结构化 PlanTask，每步强制携带政策依据，校验失败带反馈重试一次，仍失败自动降级模板——
  前端标注方案来源（AI 动态生成 / 模板兜底）
- **领域知识全部数据化**：画像字段、追问话术、抽取规则、资格条件、办事攻略都是领域包内的数据/文档——新增"公积金提取""新生儿落户"等领域 = 新增一个 `domains/` 目录
- **爬虫数据接入有明确插槽**：爬取格式定稿后写一个 Converter（`app/ingest/`），校验通过的条目才进知识库，禁止编造；每条知识强制带官方来源
- 画像字段分"必填（阻塞追问）/ 增强（缺失显示信息不足）"，满足最少追问原则（PRD 12.2）

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/agent/chat` | 主对话。SSE 流式返回 `stage_change` / `tool_call` / `tool_result` / `message` / `state` 事件 |
| POST | `/api/materials/upload` | multipart 上传（`session_id` + `file`），返回识别结果 + 预检 + 全量快照 |
| GET | `/api/agent/session/{sid}` | 会话快照（前端刷新） |
| GET | `/api/domains` | 可用领域列表 |
| GET | `/api/policies?domain=` | 知识库列表（可按域过滤，调试用） |
| GET | `/api/health` | 健康检查 + 当前 LLM 模式 |

启动后访问 `/docs` 可查看自动生成的 OpenAPI 文档（可导入 ApiFox，作为《接口规范文档》的底稿）。

## 测试

```bash
python scripts/e2e_test.py http://127.0.0.1:8765      # 全链路回归（当前 LLM/TOOL 模式，需服务已启动）
python scripts/test_dynamic_plan.py                    # 动态方案单测（stub LLM，无需服务/Key）
python scripts/test_mcp_servers.py                     # MCP 协议级测试（3 服务 7 工具，无需 uvicorn）
```

e2e 覆盖 12 组场景：创业领域全链路（画像追问 → 检索 → 四态资格 → 材料冲突 → 报告）、居住证领域全链路、模糊目标领域引导、非覆盖地区不编造兜底、领域 API。`TOOL_MODE=mcp` 启动服务后跑同一套 e2e 即验证 MCP host 路径。
动态方案单测覆盖：合法输出采用、坏 JSON 两次降级模板、缺依据带反馈重试、FAIL 政策引用白名单拒绝、mock 模式不调 LLM。

## 演示数据说明（重要）

- `app/domains/*/policies.json`：事项要素结构参照官方办事指南常见形态整理，**金额/条件/文号均为演示占位**，未逐条核实。
- `app/data/sample_materials/`：三张 PIL 合成样本图（带"演示样本"水印，非真实证照），其中申请表**故意**填了不同姓名用于演示冲突检查；每张图旁的 `.meta.json` 是 mock 模式的"识别结果"。
- 演示数据已内置，不涉及任何真实个人隐私。

## 上线前待办（按人认领）

| 人 | 待办 |
|---|---|
| 数据方 | 提供官网爬取数据样例（格式定稿） |
| 2号 | 按爬取格式实现/校准 Converter，批量灌入真实知识包；逐条溯源替换演示数据 |
| 3号 | 扩充规则算子（如经营时长、年龄区间）；UNKNOWN 状态接"继续追问"闭环 |
| 4号 | api 模式实测 VLM 抽取准确率；按领域配置材料 doc_type 与一致性规则 |
| 5号 | 单文件页迁移到 Vite + Vue3 工程（组件拆分）；移动端适配 |
| 1号 | 会话持久化（store.py 换 SQLite）；api 模式回归 e2e；领域路由在 api 模式下换 LLM 分类（处理否定表述等关键词法盲区） |

## 已知边界

- 会话存内存，服务重启即清空（演示无影响）
- mock 模式画像抽取是 schema 里的关键词规则，仅覆盖常见表述；api 模式由 LLM 结构化抽取，语料外表达也能兜住
- 意图路由 mock 模式为关键词打分，否定表述（"我不是苏州户口"）可能误命中——已通过领域关键词约束缓解，api 模式建议换 LLM 路由
- 材料识别 mock 模式依赖 sidecar 文件，任意新图片会标记为"无法识别 → 请人工核对"（这正是 PRD 的兜底路径）
