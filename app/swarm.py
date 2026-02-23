from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from .mcp_client import MCPClient, MCPClientError
from .models import (
    EscalationDecision,
    ResearchResult,
    ResponseDraft,
    SwarmRunResult,
    TicketRequest,
    TriageResult,
)
from .rag import KnowledgeBase

logger = logging.getLogger(__name__)

AGENTS_SDK_AVAILABLE = False
Agent = None
Runner = None
handoff = None

try:
    from agents import Agent as _Agent
    from agents import Runner as _Runner
    from agents import handoff as _handoff

    Agent = _Agent
    Runner = _Runner
    handoff = _handoff
    AGENTS_SDK_AVAILABLE = True
except Exception:
    AGENTS_SDK_AVAILABLE = False


def _run_single_agent(name: str, instructions: str, prompt: str) -> Optional[str]:
    if not AGENTS_SDK_AVAILABLE or Agent is None or Runner is None:
        return None

    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        agent = Agent(name=name, instructions=instructions, model="gpt-4.1-mini")
        result = Runner.run_sync(agent, input=prompt)
        output = getattr(result, "final_output", None)
        return output if isinstance(output, str) else str(result)
    except Exception as exc:
        logger.warning("Single-agent run failed (%s): %s", name, exc)
        return None


def _run_handoff_orchestration(ticket: TicketRequest) -> Optional[str]:
    """Use OpenAI Agents SDK handoffs to orchestrate triage -> research -> response -> escalation."""
    if not AGENTS_SDK_AVAILABLE or Agent is None or Runner is None or handoff is None:
        return None
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        escalation_agent = Agent(
            name="Escalation Agent",
            instructions="Decide handoff route and final operational action.",
            model="gpt-4.1-mini",
        )
        response_agent = Agent(
            name="Response Agent",
            instructions="Draft customer-ready response and immediate actions.",
            model="gpt-4.1-mini",
            handoffs=[handoff(escalation_agent)],
        )
        research_agent = Agent(
            name="Research Agent",
            instructions="Ground answers using KB context and identify external workflow needs.",
            model="gpt-4.1-mini",
            handoffs=[handoff(response_agent)],
        )
        triage_agent = Agent(
            name="Triage Agent",
            instructions="Classify urgency and SLA target for support tickets.",
            model="gpt-4.1-mini",
            handoffs=[handoff(research_agent)],
        )
        prompt = (
            "Run end-to-end support orchestration over this ticket.\n"
            f"Ticket ID: {ticket.ticket_id}\n"
            f"Customer: {ticket.customer_name} ({ticket.company})\n"
            f"Message: {ticket.message}\n"
            "Return concise operational guidance."
        )
        result = Runner.run_sync(triage_agent, input=prompt)
        output = getattr(result, "final_output", None)
        return output if isinstance(output, str) else str(result)
    except Exception as exc:
        logger.warning("Handoff orchestration failed, using deterministic fallback: %s", exc)
        return None


def _triage_agent(ticket: TicketRequest) -> TriageResult:
    lowered = f"{ticket.message} {ticket.urgency_hint or ''}".lower()

    if any(word in lowered for word in ["breach", "outage", "down", "incident", "security"]):
        urgency = "critical"
        sla = 15
        reason = "Possible service or security incident detected."
        confidence = 0.9
    elif any(word in lowered for word in ["urgent", "can't login", "cannot login", "blocked"]):
        urgency = "high"
        sla = 60
        reason = "Customer blocked from key workflow."
        confidence = 0.82
    elif any(word in lowered for word in ["billing", "invoice", "refund"]):
        urgency = "medium"
        sla = 240
        reason = "Billing-related request with potential business impact."
        confidence = 0.78
    else:
        urgency = "low"
        sla = 1440
        reason = "General support request with no outage indicators."
        confidence = 0.7

    prompt = (
        "Classify urgency as low/medium/high/critical and return one-sentence reason. "
        f"Ticket: {ticket.message}"
    )
    refined = _run_single_agent(
        name="Triage Agent",
        instructions="You triage incoming enterprise support tickets by urgency.",
        prompt=prompt,
    )
    if refined:
        reason = f"{reason} LLM note: {refined[:160]}"

    return TriageResult(
        urgency=urgency,
        reason=reason,
        confidence=confidence,
        sla_target_minutes=sla,
    )


def _find_tool_by_keywords(mcp_client: MCPClient, *keywords: str) -> Optional[str]:
    try:
        tools = mcp_client.list_tools()
    except MCPClientError:
        return None
    for tool in tools:
        haystack = f"{tool.name} {tool.description}".lower()
        if any(word in haystack for word in keywords):
            return tool.name
    return None


def _safe_invoke_tool(mcp_client: MCPClient, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        mcp_client.describe_tool(tool_name)
        return mcp_client.invoke_tool(tool_name, arguments=arguments)
    except MCPClientError as exc:
        logger.warning("MCP invoke failed for tool %s: %s", tool_name, exc)
        return None


def _research_agent(ticket: TicketRequest, kb: KnowledgeBase, mcp_client: Optional[MCPClient]) -> ResearchResult:
    snippets = kb.search(ticket.message, limit=3)
    notes = [f"[{source}] {text}" for source, text in snippets]
    web_lookup_needed = len(notes) < 2
    mcp_actions = []

    if mcp_client and mcp_client.enabled and web_lookup_needed:
        web_tool = _find_tool_by_keywords(mcp_client, "web", "search", "knowledge")
        if web_tool:
            result = _safe_invoke_tool(
                mcp_client,
                web_tool,
                {"query": ticket.message, "ticket_id": ticket.ticket_id},
            )
            if result:
                mcp_actions.append(f"Invoked MCP tool: {web_tool}")
                notes.append(f"[mcp:{web_tool}] {str(result)[:240]}")

    synthesis = "Use internal runbooks and policies to resolve the issue."
    prompt = (
        "Summarize the top support guidance in 2 sentences. "
        f"Ticket: {ticket.message}\nKnowledge: {' | '.join(notes)}"
    )
    refined = _run_single_agent(
        name="Research Agent",
        instructions=(
            "You research support issues using internal KB first, and flag when external web validation is needed."
        ),
        prompt=prompt,
    )
    if refined:
        synthesis = refined[:500]
    elif notes:
        synthesis = " ".join(note.split("] ", 1)[-1] for note in notes[:2])

    return ResearchResult(
        retrieved_notes=notes,
        web_lookup_needed=web_lookup_needed,
        synthesis=synthesis,
        mcp_actions=mcp_actions,
    )


def _response_agent(ticket: TicketRequest, triage: TriageResult, research: ResearchResult) -> ResponseDraft:
    tone_map = {
        "friendly": "warm, empathetic, and human",
        "formal": "professional and concise",
        "direct": "clear and action-oriented",
    }
    tone_hint = tone_map[ticket.preferred_tone]
    base_actions = [
        "Acknowledge the issue and provide immediate next step.",
        "Share ETA based on the assigned SLA.",
        "Offer a fallback workaround if available.",
        "Generate internal runbook update notes via Codex/Claude Code workflow.",
    ]

    prompt = (
        f"Draft a short support reply for {ticket.customer_name} at {ticket.company}. "
        f"Urgency={triage.urgency}. Tone={tone_hint}. Research={research.synthesis}"
    )
    drafted = _run_single_agent(
        name="Response Agent",
        instructions=(
            "You craft personalized customer support messages with recommended actions and clear ownership."
        ),
        prompt=prompt,
    )

    subject = f"[{triage.urgency.upper()}] Update on ticket {ticket.ticket_id}"
    if drafted:
        message = drafted[:1000]
    else:
        message = (
            f"Hi {ticket.customer_name},\n\n"
            "Thanks for raising this with us. We have triaged your request and started investigation using our internal runbooks. "
            f"Current priority is **{triage.urgency}** with a target response window of {triage.sla_target_minutes} minutes.\n\n"
            f"What we know so far: {research.synthesis}\n\n"
            "We'll share another update shortly with resolution steps.\n\n"
            "Best,\nAI Support Teammate Swarm"
        )

    return ResponseDraft(subject=subject, message=message, suggested_actions=base_actions)


def _escalation_agent(ticket: TicketRequest, triage: TriageResult, mcp_client: Optional[MCPClient]) -> EscalationDecision:
    lowered = ticket.message.lower()
    mcp_actions = []

    def maybe_operationalize_escalation(route_to: str) -> None:
        if not mcp_client or not mcp_client.enabled:
            return
        ticket_tool = _find_tool_by_keywords(mcp_client, "ticket", "database", "crm", "update")
        if ticket_tool:
            result = _safe_invoke_tool(
                mcp_client,
                ticket_tool,
                {
                    "ticket_id": ticket.ticket_id,
                    "status": "escalated",
                    "route_to": route_to,
                },
            )
            if result:
                mcp_actions.append(f"Invoked MCP tool: {ticket_tool}")
        email_tool = _find_tool_by_keywords(mcp_client, "email", "notify", "slack", "teams")
        if email_tool:
            result = _safe_invoke_tool(
                mcp_client,
                email_tool,
                {
                    "to": "support-leads@company.com",
                    "subject": f"Escalation required for {ticket.ticket_id}",
                    "body": f"Ticket routed to {route_to}. Message: {ticket.message}",
                },
            )
            if result:
                mcp_actions.append(f"Invoked MCP tool: {email_tool}")

    if "security" in lowered or "breach" in lowered:
        maybe_operationalize_escalation("security_specialist")
        return EscalationDecision(
            escalate=True,
            route_to="security_specialist",
            reason="Security indicators found in ticket.",
            mcp_actions=mcp_actions,
        )
    if any(word in lowered for word in ["billing", "invoice", "refund"]) and triage.urgency in {"high", "critical"}:
        maybe_operationalize_escalation("billing_specialist")
        return EscalationDecision(
            escalate=True,
            route_to="billing_specialist",
            reason="High-priority billing issue needs specialist ownership.",
            mcp_actions=mcp_actions,
        )
    if triage.urgency == "critical":
        maybe_operationalize_escalation("human_support_lead")
        return EscalationDecision(
            escalate=True,
            route_to="human_support_lead",
            reason="Critical severity requires immediate human oversight.",
            mcp_actions=mcp_actions,
        )

    return EscalationDecision(
        escalate=False,
        route_to="none",
        reason="Autonomous resolution path is acceptable.",
        mcp_actions=mcp_actions,
    )


def run_support_swarm(ticket: TicketRequest, kb: KnowledgeBase, mcp_client: Optional[MCPClient] = None) -> SwarmRunResult:
    trace_id = str(uuid.uuid4())
    logger.info("Starting swarm run ticket=%s trace_id=%s", ticket.ticket_id, trace_id)

    orchestration = "OpenAI Agents SDK with handoff() + deterministic fallback"
    handoff_summary = _run_handoff_orchestration(ticket)

    triage = _triage_agent(ticket)
    research = _research_agent(ticket, kb, mcp_client)
    if handoff_summary:
        research.synthesis = f"{research.synthesis}\n\nHandoff summary: {handoff_summary[:280]}"
    response = _response_agent(ticket, triage, research)
    escalation = _escalation_agent(ticket, triage, mcp_client)

    return SwarmRunResult(
        ticket_id=ticket.ticket_id,
        triage=triage,
        research=research,
        response=response,
        escalation=escalation,
        generated_at=datetime.utcnow(),
        orchestration=orchestration,
        trace_id=trace_id,
    )
