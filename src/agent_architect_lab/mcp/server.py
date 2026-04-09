from __future__ import annotations

import re
import sys
from pathlib import Path

from agent_architect_lab.mcp.protocol import read_message, write_message


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(term) >= 3]


def _search_notes(notes_dir: Path, query: str) -> list[dict]:
    lowered = query.lower().strip()
    terms = _query_terms(query)
    ranked_matches = []
    for path in sorted(notes_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        haystack = f"{path.stem}\n{content}".lower()
        score = 0
        if lowered and lowered in haystack:
            score += 10
        if terms:
            score += sum(1 for term in terms if term in haystack)
        if score == 0:
            continue
        snippet = next((line.strip() for line in content.splitlines() if line.strip()), "")[:220]
        ranked_matches.append((score, {"title": path.stem, "path": str(path), "snippet": snippet}))
    ranked_matches.sort(key=lambda item: (-item[0], item[1]["title"]))
    return [payload for _, payload in ranked_matches[:10]]


def _get_note(notes_dir: Path, note_id: str) -> dict:
    path = notes_dir / f"{note_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Note '{note_id}' does not exist.")
    return {"title": path.stem, "content": path.read_text(encoding="utf-8")}


def handle_request(request: dict, notes_dir: Path) -> dict:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"serverInfo": {"name": "agent-architect-lab-mcp", "version": "0.1.0"}}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "search_notes",
                        "description": "Search internal agent architecture notes.",
                        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                    },
                    {
                        "name": "get_note",
                        "description": "Read a note by note id.",
                        "inputSchema": {"type": "object", "properties": {"note_id": {"type": "string"}}, "required": ["note_id"]},
                    },
                ]
            },
        }
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "search_notes":
            result = {"matches": _search_notes(notes_dir, arguments["query"])}
        elif name == "get_note":
            result = _get_note(notes_dir, arguments["note_id"])
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown tool '{name}'"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method '{method}'"}}


def serve(notes_dir: Path) -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        request = read_message(stdin)
        if request is None:
            break
        response = handle_request(request, notes_dir)
        write_message(stdout, response)
