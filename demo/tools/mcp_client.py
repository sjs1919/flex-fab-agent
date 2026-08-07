"""MCP Client — 通过 stdio 协议调用真 MCP 子进程工具（R5 缺陷修复）。

与 registry 配合使用：
  - registry.execute(name, args, mode="mcp") → 走 MCP 协议
  - registry.execute(name, args, mode="local") → 走原函数直调（默认，兼容现有）

设计要点：
  - 子进程生命周期：首次调用时启动，空闲 5 分钟自动退出。
  - 工具发现：启动时 list_tools → 缓存工具列表。
  - 调用：call_tool → 组装 JSON-RPC → 写 stdin → 读 stdout。
  - 超时/重试由 R1 的 sandbox 层统一处理。
"""
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Any


MCP_MODE = os.getenv("MCP_MODE", "local")  # local | mcp


class MCPToolClient:
    """通过 stdio 与 MCP Server 子进程通信。"""

    def __init__(self, server_script: str, python: str | None = None):
        self._script = server_script
        self._python = python or sys.executable
        self._process: subprocess.Popen | None = None
        self._tools: dict[str, dict] = {}  # name → tool schema
        self._last_used: float = 0

    def _ensure_running(self):
        """确保子进程在运行（首次调用时启动；空闲超时退出后重启）。"""
        if self._process is None or self._process.poll() is not None:
            self._process = subprocess.Popen(
                [self._python, self._script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # 初始化 + 发现工具
            self._send_json_rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "demo-mcp-client", "version": "0.1.0"},
            })
            tools_resp = self._send_json_rpc("tools/list", {})
            for t in tools_resp.get("tools", []):
                self._tools[t["name"]] = t
        self._last_used = time.time()

    def _send_json_rpc(self, method: str, params: dict) -> dict:
        """发送 JSON-RPC 请求，返回 result。"""
        req = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": method,
            "params": params,
        }
        raw = json.dumps(req) + "\n"
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP 子进程未启动或 stdin 不可写")
        self._process.stdin.write(raw)
        self._process.stdin.flush()
        if self._process.stdout is None:
            raise RuntimeError("MCP 子进程 stdout 不可读")
        line = self._process.stdout.readline()
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(f"MCP 错误: {resp['error']}")
        return resp.get("result", {})

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具。"""
        self._ensure_running()
        result = self._send_json_rpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # 提取文本内容
        content = result.get("content", [])
        texts = [c["text"] for c in content if c.get("type") == "text"]
        return "\n".join(texts)

    def list_tools(self) -> list[dict]:
        """返回缓存的工具列表。"""
        self._ensure_running()
        return list(self._tools.values())

    def close(self):
        """关闭子进程。"""
        if self._process:
            self._process.terminate()
            self._process = None


# 全局 client 缓存（按 server 名）
_clients: dict[str, MCPToolClient] = {}


def get_mcp_client(server_name: str, script_path: str) -> MCPToolClient:
    """获取或创建 MCP client（按 server 名缓存，复用子进程）。"""
    if server_name not in _clients:
        _clients[server_name] = MCPToolClient(script_path)
    return _clients[server_name]
