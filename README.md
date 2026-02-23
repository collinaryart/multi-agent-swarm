# AI Support Teammate Swarm

This repo implements a complete AI ops/support worker as a **4-agent swarm**:

- **Triage Agent**: receives ticket and classifies urgency/SLA.
- **Research Agent**: retrieves relevant internal knowledge (RAG) and flags when web validation is needed.
- **Response Agent**: drafts a personalized customer reply with next actions.
- **Escalation Agent**: decides autonomous resolution vs specialist/human handoff.


- **OpenAI Agents SDK orchestration** with direct imports from `agents`: `Agent`, `Runner`, and `handoff`.
- **4-agent swarm architecture** mirroring real AI support workers: triage, research, response, escalation.
- **MCP (Model Context Protocol) integration** for dynamic external tool discovery and invocation.
- **Simple production-minded RAG** via Chroma.
- **FastAPI + Swagger live demo** with typed Pydantic models, logging, and error handling.
- **Render free-tier ready** with straightforward startup and env configuration.

## Quick start

### Python version requirement (important)

Use **Python 3.11** (recommended) or **3.12**.

`chromadb` can fail on newer interpreters (for example 3.14) with:
`pydantic.v1.errors.ConfigError: unable to infer type for attribute "chroma_server_nofile"`.

```bash
py -3.11 -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open:
- API root: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`

### First-run demo setup (local mock MCP)

On Windows PowerShell:

```powershell
$env:MCP_SERVER_URL="http://127.0.0.1:8000/mock-mcp"
uvicorn app.main:app --reload
```

## Environment variables

- `OPENAI_API_KEY` (optional): enables live OpenAI Agents SDK reasoning.
  - If not set, the project still runs using deterministic fallback handoffs for demo reliability.
- `MCP_SERVER_URL` (optional): MCP server base URL used for tool discovery + invocation.
  - Example: `https://your-mcp-gateway.example.com`
  - Local mock option: `http://127.0.0.1:8000/mock-mcp`

## Demo ticket payload

Use `POST /run_swarm` (or `POST /swarm/run`) in Swagger with:

```json
{
  "ticket_id": "TCK-1001",
  "customer_name": "Alex Parker",
  "company": "FortuneCo",
  "message": "Our SSO is failing and users are locked out after a suspicious login attempt.",
  "preferred_tone": "formal",
  "urgency_hint": "possible security incident"
}
```

## MCP Integration — agents can dynamically discover and call any external workflow

The swarm includes a lightweight MCP HTTP/SSE client (`app/mcp_client.py`) and a FastAPI MCP gateway endpoint:

- `POST /mcp` with `operation: "list_tools"` -> discovers available MCP tools.
- `POST /mcp` with `operation: "describe_tool"` -> fetches tool schema/metadata.
- `POST /mcp` with `operation: "invoke_tool"` -> executes external workflows.

This lets agents dynamically trigger systems like:
- n8n / Make / Zapier automations
- email/notification workflows
- database or ticketing updates
- CRM/helpdesk integrations

Research Agent uses MCP when KB evidence is thin (for external discovery/web-enrichment), and Escalation Agent uses MCP for operational actions (e.g., notify leads, update ticket records).

### Built-in mock MCP server (for demos)

This repo includes an in-app mock MCP server so you can demo dynamic tool orchestration immediately:

- `GET /mock-mcp/tools`
- `POST /mock-mcp/tools/list`
- `POST /mock-mcp/tools/describe`
- `POST /mock-mcp/tools/invoke`
- SSE variants under `/mock-mcp/sse/*`

Example demo flow:
1. Set `MCP_SERVER_URL=http://127.0.0.1:8000/mock-mcp`
2. Run `POST /mcp` with `{ "operation": "list_tools" }`
3. Run `POST /run_swarm` and observe MCP-backed actions in `research.mcp_actions` and `escalation.mcp_actions`.

## Render deployment (free tier)

1. Push this repository to GitHub.
2. In Render, create a new **Web Service** from the repo.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add env var `OPENAI_API_KEY` (optional but recommended).
5. Add env var `MCP_SERVER_URL` when demonstrating external workflow orchestration.
