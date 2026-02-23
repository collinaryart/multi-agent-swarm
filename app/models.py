from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Urgency = Literal["low", "medium", "high", "critical"]


class TicketRequest(BaseModel):
    ticket_id: str = Field(..., description="External ticket identifier")
    customer_name: str = Field(..., description="Customer's name")
    company: str = Field(..., description="Customer company name")
    message: str = Field(..., min_length=8, description="Ticket body")
    preferred_tone: Literal["friendly", "formal", "direct"] = "friendly"
    urgency_hint: Optional[str] = Field(
        default=None,
        description="Optional user hint about urgency (for demo control)",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TriageResult(BaseModel):
    urgency: Urgency
    reason: str
    confidence: float = Field(..., ge=0, le=1)
    sla_target_minutes: int


class ResearchResult(BaseModel):
    retrieved_notes: List[str]
    web_lookup_needed: bool
    synthesis: str
    mcp_actions: List[str] = Field(default_factory=list)


class ResponseDraft(BaseModel):
    subject: str
    message: str
    suggested_actions: List[str]


class EscalationDecision(BaseModel):
    escalate: bool
    route_to: Literal[
        "none",
        "human_support_lead",
        "security_specialist",
        "billing_specialist",
    ]
    reason: str
    mcp_actions: List[str] = Field(default_factory=list)


class SwarmRunResult(BaseModel):
    ticket_id: str
    triage: TriageResult
    research: ResearchResult
    response: ResponseDraft
    escalation: EscalationDecision
    generated_at: datetime
    orchestration: str = "OpenAI Agents SDK with fallback handoffs"
    trace_id: str


class KnowledgeDocIn(BaseModel):
    doc_id: str
    content: str = Field(..., min_length=20)
    source: str = "internal"


class KnowledgeDocOut(BaseModel):
    doc_id: str
    source: str
    content_preview: str


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=3, ge=1, le=10)


class MCPToolDescriptor(BaseModel):
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class MCPListToolsResponse(BaseModel):
    tools: List[MCPToolDescriptor]


class MCPDescribeToolRequest(BaseModel):
    name: str


class MCPInvokeToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPInvokeToolResponse(BaseModel):
    tool_name: str
    output: Dict[str, Any] = Field(default_factory=dict)


class MCPGatewayRequest(BaseModel):
    operation: Literal["list_tools", "describe_tool", "invoke_tool"]
    name: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPGatewayResponse(BaseModel):
    operation: str
    data: Dict[str, Any] = Field(default_factory=dict)


class APIError(BaseModel):
    detail: str
    trace_id: Optional[str] = None
