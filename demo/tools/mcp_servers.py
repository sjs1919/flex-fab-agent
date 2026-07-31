"""MCP Server 封装 -- 展示 MCP 架构（可独立 stdio 运行）。

为什么保留 MCP 封装：
  Demo 里 Agent 直接 import 工具函数调用（稳定性优先，绕开进程通信），
  但 MCP 是 week3 的核心教学点：工具按 server 分组、通过 JSON-RPC over stdio 暴露。
  本文件把同一批工具函数用 FastMCP @mcp.tool 装饰器再封装一次，独立可运行，
  体现"同一工具实现，两种暴露方式（直接调用 / MCP 协议）"。

运行方式（展示 MCP 协议）：
  python -m demo.tools.mcp_servers.order      # 订单 server
  python -m demo.tools.mcp_servers.resource   # 资源 server
"""
from mcp.server.fastmcp import FastMCP

from .order_tools import query_orders, get_order_detail, get_production_status
from .resource_tools import query_inventory, query_machine_load, query_customer


def build_order_server() -> FastMCP:
    """订单 MCP server（3 个工具）。"""
    mcp = FastMCP("order-server")
    mcp.add_tool(query_orders)
    mcp.add_tool(get_order_detail)
    mcp.add_tool(get_production_status)
    return mcp


def build_resource_server() -> FastMCP:
    """资源 MCP server（3 个工具）。"""
    mcp = FastMCP("resource-server")
    mcp.add_tool(query_inventory)
    mcp.add_tool(query_machine_load)
    mcp.add_tool(query_customer)
    return mcp
