from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .models import MCPToolDescriptor

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    pass


class MCPClient:
    """Minimal MCP client over HTTP/SSE for tool discovery and invocation."""

    def __init__(
        self,
        server_url: Optional[str],
        timeout_seconds: float = 12.0,
    ) -> None:
        self.server_url = (server_url or "").rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.server_url)

    def _request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise MCPClientError("MCP server URL is not configured.")

        url = f"{self.server_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method=method, url=url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {"data": data}
        except Exception as exc:
            logger.exception("MCP HTTP request failed: %s %s", method, url)
            raise MCPClientError(f"MCP request failed for {path}: {exc}") from exc

    def _request_sse(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise MCPClientError("MCP server URL is not configured.")

        url = f"{self.server_url}{path}"
        headers = {"Accept": "text/event-stream"}

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            raw = line.replace("data:", "", 1).strip()
                            if raw == "[DONE]":
                                break
                            try:
                                data = json.loads(raw)
                                if isinstance(data, dict):
                                    return data
                            except json.JSONDecodeError:
                                logger.warning("Skipping non-JSON SSE payload from MCP.")
            raise MCPClientError("No JSON event payload returned by MCP SSE endpoint.")
        except Exception as exc:
            logger.exception("MCP SSE request failed for %s", url)
            raise MCPClientError(f"MCP SSE request failed for {path}: {exc}") from exc

    def list_tools(self) -> List[MCPToolDescriptor]:
        """List tools using common MCP endpoint conventions."""
        payloads = [
            ("GET", "/tools", None, False),
            ("POST", "/tools/list", {}, False),
            ("POST", "/mcp/list_tools", {}, False),
            ("POST", "/sse/list_tools", {}, True),
        ]
        for method, path, payload, sse in payloads:
            try:
                data = self._request_sse(path, payload) if sse else self._request_json(method, path, payload)
                raw_tools = data.get("tools", [])
                tools: List[MCPToolDescriptor] = []
                for item in raw_tools:
                    if isinstance(item, dict) and item.get("name"):
                        tools.append(
                            MCPToolDescriptor(
                                name=item["name"],
                                description=item.get("description", ""),
                                input_schema=item.get("input_schema", item.get("schema", {})),
                            )
                        )
                if tools:
                    return tools
            except MCPClientError:
                continue
        return []

    def describe_tool(self, name: str) -> Dict[str, Any]:
        payloads = [
            ("POST", "/tools/describe", {"name": name}, False),
            ("POST", "/mcp/describe_tool", {"name": name}, False),
            ("POST", "/sse/describe_tool", {"name": name}, True),
        ]
        for method, path, payload, sse in payloads:
            try:
                return self._request_sse(path, payload) if sse else self._request_json(method, path, payload)
            except MCPClientError:
                continue
        raise MCPClientError(f"Unable to describe MCP tool '{name}'.")

    def invoke_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"name": name, "arguments": arguments or {}}
        payloads = [
            ("POST", "/tools/invoke", payload, False),
            ("POST", "/mcp/invoke_tool", payload, False),
            ("POST", "/sse/invoke_tool", payload, True),
        ]
        for method, path, body, sse in payloads:
            try:
                return self._request_sse(path, body) if sse else self._request_json(method, path, body)
            except MCPClientError:
                continue
        raise MCPClientError(f"Unable to invoke MCP tool '{name}'.")
