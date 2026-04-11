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
    (notes_dir / "ops-incidents.md").write_text(
        "# Ops Incidents\n\nRollback drills and alert ownership matter.\n",
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
    assert matches[0]["metadata"]["note_id"] == "memory-retrieval"
    assert "retrieval" in matches[0]["metadata"]["domains"]
    assert matches[0]["provenance"]["source_type"] == "note"
    assert "memory" in matches[0]["provenance"]["matched_terms"]
    assert "domains" in matches[0]["provenance"]["matched_fields"]


def test_handle_request_search_notes_supports_domain_filter_and_get_note_metadata(tmp_path: Path) -> None:
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    (notes_dir / "memory-retrieval.md").write_text(
        "---\n"
        "title: Retrieval Design\n"
        "domains: [retrieval, evaluations]\n"
        "tags: [memory, provenance]\n"
        "summary: Retrieval should return grounded sources.\n"
        "---\n"
        "# Retrieval Design\n\nRetrieval should return grounded sources.\n",
        encoding="utf-8",
    )
    (notes_dir / "safety-policies.md").write_text(
        "# Safety Policies\n\nHuman approval paths should default deny risky actions.\n",
        encoding="utf-8",
    )

    search_response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_notes", "arguments": {"query": "memory provenance", "domain": "retrieval", "limit": 1}},
        },
        notes_dir,
    )
    get_response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_note", "arguments": {"note_id": "memory-retrieval"}},
        },
        notes_dir,
    )

    matches = search_response["result"]["matches"]
    assert len(matches) == 1
    assert matches[0]["title"] == "memory-retrieval"
    assert matches[0]["metadata"]["title"] == "Retrieval Design"
    assert matches[0]["metadata"]["domains"] == ["evaluations", "retrieval"]
    assert matches[0]["provenance"]["matched_domains"] == ["retrieval"]

    note_payload = get_response["result"]
    assert note_payload["metadata"]["summary"] == "Retrieval should return grounded sources."
    assert note_payload["provenance"]["domains"] == ["evaluations", "retrieval"]
    assert note_payload["provenance"]["tags"] == ["memory", "provenance"]
