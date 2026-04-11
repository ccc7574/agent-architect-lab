from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from agent_architect_lab.mcp.protocol import read_message, write_message


DOMAIN_KEYWORDS = {
    "retrieval": {"memory", "retrieval", "knowledge", "note", "notes", "provenance"},
    "evaluations": {"eval", "evals", "grader", "benchmark", "regression", "harness", "shadow"},
    "safety": {"safety", "guardrail", "policy", "approval", "default-deny"},
    "operations": {"incident", "rollback", "deploy", "runbook", "alert", "operator"},
    "product": {"product", "roadmap", "architecture", "platform", "plane"},
    "skills": {"skill", "skills", "routing", "router"},
}


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(term) >= 3]


def _frontmatter_payload(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    end_marker = content.find("\n---\n", 4)
    if end_marker == -1:
        return {}, content
    raw_frontmatter = content[4:end_marker]
    body = content[end_marker + 5 :]
    payload: dict[str, Any] = {}
    for line in raw_frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        normalized_key = key.strip().lower().replace("-", "_")
        normalized_value = value.strip()
        if normalized_value.startswith("[") and normalized_value.endswith("]"):
            payload[normalized_key] = [
                item.strip().strip("'\"")
                for item in normalized_value[1:-1].split(",")
                if item.strip()
            ]
            continue
        if "," in normalized_value:
            payload[normalized_key] = [item.strip().strip("'\"") for item in normalized_value.split(",") if item.strip()]
            continue
        payload[normalized_key] = normalized_value.strip("'\"")
    return payload, body


def _summary_from_body(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:220]
    return ""


def _headings_from_body(body: str) -> list[str]:
    headings: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings[:10]


def _infer_domains(text: str) -> list[str]:
    lowered = text.lower()
    domains = [
        domain
        for domain, hints in DOMAIN_KEYWORDS.items()
        if any(hint in lowered for hint in hints)
    ]
    if "memory" in lowered or "retrieval" in lowered:
        domains.append("retrieval")
    return sorted(dict.fromkeys(domains))


def _note_metadata(path: Path, content: str) -> dict[str, Any]:
    frontmatter, body = _frontmatter_payload(content)
    headings = _headings_from_body(body)
    title = str(frontmatter.get("title") or (headings[0] if headings else path.stem))
    summary = str(frontmatter.get("summary") or _summary_from_body(body))
    tags = frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    normalized_tags = sorted(dict.fromkeys(str(tag).strip().lower() for tag in tags if str(tag).strip()))
    domain_values = frontmatter.get("domains", []) or frontmatter.get("domain", [])
    if isinstance(domain_values, str):
        domain_values = [domain_values]
    domains = [str(item).strip().lower() for item in domain_values if str(item).strip()]
    if not domains:
        domains = _infer_domains(f"{title}\n{summary}\n{body}\n{path.stem}")
    return {
        "note_id": path.stem,
        "title": title,
        "path": str(path),
        "summary": summary,
        "domains": sorted(dict.fromkeys(domains)),
        "tags": normalized_tags,
        "headings": headings,
    }


def _search_notes(notes_dir: Path, query: str, *, domain: str = "", limit: int = 10) -> list[dict]:
    lowered = query.lower().strip()
    terms = _query_terms(query)
    query_domains = _infer_domains(query)
    requested_domain = domain.strip().lower()
    ranked_matches = []
    for path in sorted(notes_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        metadata = _note_metadata(path, content)
        if requested_domain and requested_domain not in metadata["domains"]:
            continue
        searchable_title = metadata["title"].lower()
        searchable_summary = metadata["summary"].lower()
        searchable_body = content.lower()
        searchable_domains = " ".join(metadata["domains"])
        matched_terms = [term for term in terms if term in searchable_body or term in searchable_title or term in searchable_summary]
        matched_domains = [item for item in query_domains if item in metadata["domains"]]
        matched_fields: list[str] = []
        score = 0
        if lowered and lowered in searchable_body:
            score += 12
            matched_fields.append("exact_query")
        if terms:
            title_hits = [term for term in terms if term in searchable_title]
            summary_hits = [term for term in terms if term in searchable_summary]
            body_hits = [term for term in terms if term in searchable_body]
            if title_hits:
                score += 5 * len(title_hits)
                matched_fields.append("title")
            if summary_hits:
                score += 3 * len(summary_hits)
                matched_fields.append("summary")
            if body_hits:
                score += len(body_hits)
                matched_fields.append("body")
        if matched_domains:
            score += 6 * len(matched_domains)
            matched_fields.append("domains")
        if lowered and lowered in searchable_domains:
            score += 4
        if score == 0:
            continue
        ranked_matches.append(
            (
                score,
                {
                    "title": metadata["note_id"],
                    "path": str(path),
                    "snippet": metadata["summary"],
                    "metadata": metadata,
                    "provenance": {
                        "source_type": "note",
                        "note_id": metadata["note_id"],
                        "path": str(path),
                        "score": score,
                        "matched_terms": matched_terms,
                        "matched_domains": matched_domains,
                        "matched_fields": sorted(dict.fromkeys(matched_fields)),
                        "query": query,
                    },
                },
            )
        )
    ranked_matches.sort(
        key=lambda item: (
            -item[0],
            -len(item[1]["provenance"]["matched_domains"]),
            -len(item[1]["provenance"]["matched_terms"]),
            item[1]["title"],
        )
    )
    return [payload for _, payload in ranked_matches[: max(limit, 1)]]


def _get_note(notes_dir: Path, note_id: str) -> dict:
    path = notes_dir / f"{note_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Note '{note_id}' does not exist.")
    content = path.read_text(encoding="utf-8")
    metadata = _note_metadata(path, content)
    return {
        "title": metadata["note_id"],
        "content": content,
        "metadata": metadata,
        "provenance": {
            "source_type": "note",
            "note_id": metadata["note_id"],
            "path": str(path),
            "domains": metadata["domains"],
            "tags": metadata["tags"],
        },
    }


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
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "domain": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                            },
                            "required": ["query"],
                        },
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
            result = {
                "matches": _search_notes(
                    notes_dir,
                    arguments["query"],
                    domain=str(arguments.get("domain", "")),
                    limit=int(arguments.get("limit", 10)),
                )
            }
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
