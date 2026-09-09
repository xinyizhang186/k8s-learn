import time
from collections.abc import Callable
from typing import Any

from app.db.database import save_tool_call


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, tuple[dict[str, Any], Callable[..., Any]]] = {}

    def register(self, name: str, description: str, schema: dict[str, Any], handler: Callable[..., Any]) -> None:
        self.tools[name] = ({"name": name, "description": description, "inputSchema": schema}, handler)

    def schemas(self) -> list[dict[str, Any]]:
        return [metadata for metadata, _ in self.tools.values()]

    async def call(self, name: str, args: dict[str, Any], trace_id: str) -> Any:
        if name not in self.tools:
            raise ValueError(f"工具不存在: {name}")
        _, handler = self.tools[name]
        started = time.perf_counter()
        try:
            result = handler(**args)
            if hasattr(result, "__await__"):
                result = await result
            save_tool_call(trace_id, name, args, "success", (time.perf_counter() - started) * 1000)
            return result
        except Exception as exc:
            save_tool_call(trace_id, name, args, "error", (time.perf_counter() - started) * 1000, str(exc))
            raise
