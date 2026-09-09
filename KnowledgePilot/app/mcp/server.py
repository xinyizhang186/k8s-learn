from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.engine import agent


router = APIRouter(prefix="/mcp", tags=["MCP"])


class MCPCall(BaseModel):
    name: str
    arguments: dict = {}


@router.get("/tools")
async def list_tools():
    return {"protocol": "knowledgepilot-mcp-compatible", "tools": agent.registry.schemas()}


@router.post("/call")
async def call_tool(request: MCPCall):
    try:
        result = await agent.registry.call(request.name, request.arguments, "mcp-" + request.name)
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
