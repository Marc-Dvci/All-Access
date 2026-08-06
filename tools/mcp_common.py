"""A minimal JSON-RPC-over-stdio MCP server.

Both development-time MCP servers in `.bob/mcp.json` are built on this. It
implements the three methods a client needs to be useful -- `initialize`,
`tools/list`, `tools/call` -- plus the `notifications/initialized` acknowledgment
and `ping`, and nothing else.

There is no MCP SDK dependency on purpose. These servers exist so IBM Bob can
read a development schema registry and the committed test artifacts during a
session; adding a package to the project's dependency tree so that a
development-time tool can speak a protocol that is four JSON messages wide would
be a poor trade. The wire format is stable and specified, and the whole
implementation is under two hundred lines.

Transport rules that matter and are easy to get wrong:

* One JSON object per line on stdin, one per line on stdout. Anything this
  process wants to say to a human goes to **stderr** -- a stray `print` corrupts
  the stream and the client's error will not point here.
* A request carries an `id` and expects a response. A notification has no `id`
  and must not get one; replying to a notification is a protocol violation that
  some clients drop the connection over.
* An error inside a tool is *not* a JSON-RPC error. It is a successful response
  whose `content` describes the failure and whose `isError` is true. JSON-RPC
  errors are reserved for the protocol itself -- unknown method, bad params --
  because a client that cannot tell "your query was wrong" from "the server is
  broken" will retry the wrong one.
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

PROTOCOL_VERSION = "2025-06-18"

# JSON-RPC error codes. Only the ones this server can actually produce.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class Tool:
    """One callable tool.

    `handler` returns anything JSON-serialisable; it is rendered as pretty JSON
    into a single text content block. Raising is fine and expected -- the
    exception becomes an `isError` result the model can read and react to.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MCPServer:
    name: str
    version: str = "0.1.0"
    instructions: str = ""
    tools: dict[str, Tool] = field(default_factory=dict)

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
    ) -> Callable[[Callable[[dict[str, Any]], Any]], Callable[[dict[str, Any]], Any]]:
        def register(fn: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
            self.tools[name] = Tool(
                name=name,
                description=description,
                input_schema=input_schema or {"type": "object", "properties": {}},
                handler=fn,
            )
            return fn

        return register

    # -- protocol ----------------------------------------------------------

    def _initialize(self, _params: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def _list_tools(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": [t.describe() for t in self.tools.values()]}

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        tool = self.tools.get(str(name))
        if tool is None:
            # Deliberately a tool-level error rather than METHOD_NOT_FOUND: the
            # protocol call was well formed, the model just asked for a tool
            # that is not on this server, and it can recover from being told so.
            return _text_result(
                f"unknown tool {name!r}; available: {', '.join(sorted(self.tools))}",
                is_error=True,
            )
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _text_result("`arguments` must be an object", is_error=True)
        try:
            payload = tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised
            print(traceback.format_exc(), file=sys.stderr)
            return _text_result(f"{type(exc).__name__}: {exc}", is_error=True)
        return _text_result(
            payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
        )

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """One request in, at most one response out. `None` means notification."""
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}

        if method == "notifications/initialized" or message_id is None:
            return None

        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "initialize": self._initialize,
            "tools/list": self._list_tools,
            "tools/call": self._call_tool,
            "ping": lambda _p: {},
        }
        handler = handlers.get(str(method))
        if handler is None:
            return _error(message_id, METHOD_NOT_FOUND, f"unknown method {method!r}")
        try:
            return {"jsonrpc": "2.0", "id": message_id, "result": handler(params)}
        except Exception as exc:  # noqa: BLE001 - protocol-level failure
            print(traceback.format_exc(), file=sys.stderr)
            return _error(message_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")

    def run(self) -> None:
        """Serve until stdin closes."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                _write(_error(None, PARSE_ERROR, str(exc)))
                continue
            if not isinstance(message, dict):
                _write(_error(None, INVALID_REQUEST, "message must be a JSON object"))
                continue
            response = self.handle(message)
            if response is not None:
                _write(response)


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()
