"""MCP 客户端管理器：Agent 作为 MCP host，通过 stdio 连接三个工具服务。

实现要点：stdio_client 的连接上下文必须在其所属任务内长期存活（anyio 任务亲和性），
由请求任务直接持有会随请求结束而断连。因此每个服务由一个**专职后台任务**持有连接、
串行处理请求队列；调用方通过 Future 拿结果。连接死亡后自动重建。"""
import asyncio
import json
import os
import sys
import contextlib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(BASE_DIR, "app", "mcp_servers")

SERVERS = {
    "policy": "policy_server.py",
    "eligibility_plan": "eligibility_plan_server.py",
    "material": "material_server.py",
}


class _ToolError(Exception):
    """远端工具执行出错（isError 结果），连接本身正常。"""


class _ConnError(Exception):
    """连接建立/传输失败，需要重建连接。"""


def _parse_result(result):
    """从 CallToolResult 提取结构化结果（优先 structuredContent，退化到文本 JSON）。"""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    for c in result.content:
        if getattr(c, "text", None):
            return json.loads(c.text)
    return None


class _Worker:
    """持有一条 stdio MCP 连接的后台任务。"""

    def __init__(self, server: str):
        self.server = server
        self.script = SERVERS[server]
        self._q: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Event | None = None
        self._setup_error: str | None = None
        self._pending: list[asyncio.Future] = []

    async def call(self, name: str, args: dict):
        if self._task is None or self._task.done():
            self._start()
        assert self._q is not None and self._ready is not None
        try:
            await asyncio.wait_for(self._ready.wait(), 30)
        except asyncio.TimeoutError:
            self._task = None
            raise _ConnError(f"服务 {self.server} 初始化超时")
        if self._setup_error:
            raise _ConnError(f"服务 {self.server} 初始化失败：{self._setup_error}")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending.append(fut)
        self._q.put_nowait((name, args, fut))
        try:
            return await fut
        finally:
            if fut in self._pending:
                self._pending.remove(fut)

    def _start(self):
        self._q = asyncio.Queue()
        self._ready = asyncio.Event()
        self._setup_error = None
        self._pending = []
        self._task = asyncio.create_task(self._run())

    def _fail_all(self, err: _ConnError):
        for fut in self._pending:
            if not fut.done():
                fut.set_result(err)
        self._pending = []

    async def _run(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(SERVER_DIR, self.script)],
            cwd=BASE_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": BASE_DIR},
        )
        try:
            async with contextlib.AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self._ready.set()
                while True:
                    item = await self._q.get()
                    if item is None:                    # shutdown
                        return
                    name, args, fut = item
                    try:
                        result = await session.call_tool(name, args)
                        if getattr(result, "isError", False):
                            texts = [c.text for c in result.content if getattr(c, "text", None)]
                            fut.set_result(_ToolError("; ".join(texts)[:300]))
                        else:
                            fut.set_result(_parse_result(result))
                    except Exception as e:              # 传输层断连
                        self._fail_all(_ConnError(f"{type(e).__name__}: {e}"))
                        return                          # 连接不可用，退出由下次调用重建
        except Exception as e:                          # 连接建立失败
            self._setup_error = f"{type(e).__name__}: {e}"
            self._ready.set()
            self._fail_all(_ConnError(f"{self._setup_error}"))

    def resolve(self, raw):
        """把 worker 的返回转成结果或异常；连接级错误则重置自身待重建。"""
        if isinstance(raw, _ConnError):
            self._task = None
            self._q = None
            raise RuntimeError(f"MCP 服务 {self.server} 连接失败：{raw}")
        if isinstance(raw, _ToolError):
            raise RuntimeError(f"MCP 工具 {self.server} 执行失败：{raw}")
        return raw


_WORKERS: dict[str, _Worker] = {}


async def call_tool(server: str, name: str, args: dict):
    if server not in SERVERS:
        raise KeyError(f"未知 MCP 服务 {server}，可选: {list(SERVERS)}")
    if server not in _WORKERS or _WORKERS[server]._task is None:
        _WORKERS[server] = _Worker(server)
    worker = _WORKERS[server]
    raw = await worker.call(name, args)
    return worker.resolve(raw)


async def shutdown():
    for w in _WORKERS.values():
        if w._task and w._q:
            w._q.put_nowait(None)
        w._task = None
    _WORKERS.clear()
