from __future__ import annotations

from pathlib import Path

from agent_architect_lab.mcp.server import handle_request


def test_handle_request_search_notes_matches_query_terms(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "memory-retrieval.md").write_text(
        "# Memory Retrieval\n\nMemory retrieval needs a durable note layer.\n",
        encoding="utf-8",
    )

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_notes", "arguments": {"query": "memory retrieval system design"}},
        },
        notes_dir,
    )

    matches = response["result"]["matches"]
    assert matches
    assert matches[0]["title"] == "memory-retrieval"
