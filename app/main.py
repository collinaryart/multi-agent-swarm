import logging
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .mcp_client import MCPClient, MCPClientError
from .models import (
    APIError,
    MCPGatewayRequest,
    MCPGatewayResponse,
    KnowledgeDocIn,
    KnowledgeDocOut,
    SearchRequest,
    SwarmRunResult,
    TicketRequest,
)
from .mock_mcp import router as mock_mcp_router
from .rag import KnowledgeBase
from .swarm import run_support_swarm

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Support Teammate Swarm",
    description=(
        "4-agent support swarm (Triage, Research, Response, Escalation) "
        "with OpenAI Agents SDK handoffs, MCP integration, and live Swagger demo."
    ),
    version="1.0.0",
)
app.include_router(mock_mcp_router)

kb = KnowledgeBase()
kb.seed_default()
mcp_client = MCPClient(server_url=os.getenv("MCP_SERVER_URL"))


@app.exception_handler(MCPClientError)
def handle_mcp_error(_: Request, exc: MCPClientError) -> JSONResponse:
    trace_id = str(uuid4())
    logger.exception("MCP error trace_id=%s error=%s", trace_id, exc)
    return JSONResponse(
        status_code=502,
        content=APIError(detail=str(exc), trace_id=trace_id).model_dump(),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    trace_id = str(uuid4())
    logger.exception("Unhandled error trace_id=%s error=%s", trace_id, exc)
    return JSONResponse(
        status_code=500,
        content=APIError(detail="Internal server error", trace_id=trace_id).model_dump(),
    )


@app.get("/")
def root() -> dict:
    return {
        "project": "AI Support Teammate Swarm",
        "status": "running",
        "docs": "/docs",
        "run_swarm": "/run_swarm",
        "mcp_gateway": "/mcp",
        "mock_mcp_tools": "/mock-mcp/tools",
    }


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "kb_docs": kb.collection.count(),
        "mcp_enabled": mcp_client.enabled,
    }


@app.post("/swarm/run", response_model=SwarmRunResult, tags=["swarm"])
def run_swarm(ticket: TicketRequest) -> SwarmRunResult:
    return run_support_swarm(ticket, kb, mcp_client=mcp_client)


@app.post("/run_swarm", response_model=SwarmRunResult, tags=["swarm"])
def run_swarm_alias(ticket: TicketRequest) -> SwarmRunResult:
    return run_support_swarm(ticket, kb, mcp_client=mcp_client)


@app.post("/kb/add", response_model=KnowledgeDocOut, tags=["knowledge-base"])
def add_doc(doc: KnowledgeDocIn) -> KnowledgeDocOut:
    try:
        kb.add_document(doc_id=doc.doc_id, content=doc.content, source=doc.source)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to add document: {exc}") from exc
    return KnowledgeDocOut(
        doc_id=doc.doc_id,
        source=doc.source,
        content_preview=doc.content[:140],
    )


@app.post("/kb/search", response_model=list[KnowledgeDocOut], tags=["knowledge-base"])
def search_docs(payload: SearchRequest) -> list[KnowledgeDocOut]:
    hits = kb.search(payload.query, payload.limit)
    return [
        KnowledgeDocOut(doc_id=f"result-{idx+1}", source=source, content_preview=text[:140])
        for idx, (source, text) in enumerate(hits)
    ]


@app.post("/mcp", response_model=MCPGatewayResponse, tags=["mcp"])
def mcp_gateway(payload: MCPGatewayRequest) -> MCPGatewayResponse:
    if not mcp_client.enabled:
        raise HTTPException(status_code=400, detail="MCP_SERVER_URL not configured.")

    if payload.operation == "list_tools":
        tools = [tool.model_dump() for tool in mcp_client.list_tools()]
        return MCPGatewayResponse(operation=payload.operation, data={"tools": tools})

    if payload.operation == "describe_tool":
        if not payload.name:
            raise HTTPException(status_code=422, detail="Tool name is required for describe_tool.")
        details = mcp_client.describe_tool(payload.name)
        return MCPGatewayResponse(operation=payload.operation, data=details)

    if payload.operation == "invoke_tool":
        if not payload.name:
            raise HTTPException(status_code=422, detail="Tool name is required for invoke_tool.")
        output = mcp_client.invoke_tool(payload.name, payload.arguments)
        return MCPGatewayResponse(operation=payload.operation, data=output)

    raise HTTPException(status_code=400, detail=f"Unsupported operation: {payload.operation}")
