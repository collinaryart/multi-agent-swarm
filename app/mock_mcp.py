from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/mock-mcp", tags=["mock-mcp"])


class ToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


MOCK_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "web_search",
        "description": "Search web snippets for support context.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "ticket_id": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "update_ticket_db",
        "description": "Update ticket status and assignee in support database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "status": {"type": "string"},
                "route_to": {"type": "string"},
            },
            "required": ["ticket_id", "status"],
        },
    },
    {
        "name": "send_email",
        "description": "Send escalation notification email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]


def _find_tool(name: str) -> Dict[str, Any]:
    for tool in MOCK_TOOLS:
        if tool["name"] == name:
            return tool
    raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")


def _mock_output(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "web_search":
        query = arguments.get("query", "")
        return {
            "results": [
                {"title": "Status page", "snippet": f"No major outage linked to '{query}'."},
                {"title": "Runbook note", "snippet": "Escalate security terms to security_specialist."},
            ]
        }
    if name == "update_ticket_db":
        return {
            "updated": True,
            "ticket_id": arguments.get("ticket_id"),
            "status": arguments.get("status", "escalated"),
            "route_to": arguments.get("route_to", "human_support_lead"),
        }
    if name == "send_email":
        return {
            "sent": True,
            "to": arguments.get("to"),
            "subject": arguments.get("subject"),
            "message_id": "mock-msg-001",
        }
    raise HTTPException(status_code=404, detail=f"No mock behavior for tool: {name}")


def _sse_payload(data: Dict[str, Any]) -> StreamingResponse:
    def _stream() -> Any:
        yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/tools")
def list_tools_get() -> Dict[str, Any]:
    return {"tools": MOCK_TOOLS}


@router.post("/tools/list")
def list_tools_post() -> Dict[str, Any]:
    return {"tools": MOCK_TOOLS}


@router.post("/mcp/list_tools")
def list_tools_mcp() -> Dict[str, Any]:
    return {"tools": MOCK_TOOLS}


@router.post("/sse/list_tools")
def list_tools_sse() -> StreamingResponse:
    return _sse_payload({"tools": MOCK_TOOLS})


@router.post("/tools/describe")
def describe_tool(payload: ToolRequest) -> Dict[str, Any]:
    tool = _find_tool(payload.name)
    return {"tool": tool}


@router.post("/mcp/describe_tool")
def describe_tool_mcp(payload: ToolRequest) -> Dict[str, Any]:
    tool = _find_tool(payload.name)
    return {"tool": tool}


@router.post("/sse/describe_tool")
def describe_tool_sse(payload: ToolRequest) -> StreamingResponse:
    tool = _find_tool(payload.name)
    return _sse_payload({"tool": tool})


@router.post("/tools/invoke")
def invoke_tool(payload: ToolRequest) -> Dict[str, Any]:
    _find_tool(payload.name)
    return {"tool_name": payload.name, "output": _mock_output(payload.name, payload.arguments)}


@router.post("/mcp/invoke_tool")
def invoke_tool_mcp(payload: ToolRequest) -> Dict[str, Any]:
    _find_tool(payload.name)
    return {"tool_name": payload.name, "output": _mock_output(payload.name, payload.arguments)}


@router.post("/sse/invoke_tool")
def invoke_tool_sse(payload: ToolRequest) -> StreamingResponse:
    _find_tool(payload.name)
    return _sse_payload({"tool_name": payload.name, "output": _mock_output(payload.name, payload.arguments)})
