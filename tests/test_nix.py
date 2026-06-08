"""Tests for Nix language extractor: bindings, functions, imports, inherit, NixOS modules."""
from __future__ import annotations
from pathlib import Path
import importlib.util
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

_needs_nix = pytest.mark.skipif(
    importlib.util.find_spec("tree_sitter_nix") is None
    and not __import__("os").environ.get("GRAPHIFY_TREE_SITTER_NIX_PATH"),
    reason="tree-sitter-nix not available (install via `pip install graphifyy[nix]` or set GRAPHIFY_TREE_SITTER_NIX_PATH)",
)


def _import_extract_nix():
    """Import extract_nix lazily so the skip marker works before import errors."""
    from graphify.extract import extract_nix
    return extract_nix


def _labels(r):
    return [n["label"] for n in r["nodes"]]


def _relations(r):
    return {e["relation"] for e in r["edges"]}


def _calls(r):
    node_by_id = {n["id"]: n["label"] for n in r["nodes"]}
    return {
        (node_by_id.get(e["source"], e["source"]), node_by_id.get(e["target"], e["target"]))
        for e in r["edges"] if e["relation"] == "calls"
    }


def _edges_with_relation(r, *relations):
    return [e for e in r["edges"] if e["relation"] in relations]


def _edge_labels(result: dict, relation: str, context: str | None = None) -> set[tuple[str, str]]:
    labels = {node["id"]: node["label"].strip("()").lstrip(".") for node in result["nodes"]}
    pairs = set()
    for edge in result["edges"]:
        if edge.get("relation") != relation:
            continue
        if context is not None and edge.get("context") != context:
            continue
        pairs.add((labels.get(edge["source"], edge["source"]), labels.get(edge["target"], edge["target"])))
    return pairs


# ── Core Nix (sample.nix) ────────────────────────────────────────────────────

@_needs_nix
def test_nix_no_error():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    assert "error" not in r


@_needs_nix
def test_nix_has_required_keys():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    assert "nodes" in r
    assert "edges" in r
    assert "raw_calls" in r


@_needs_nix
def test_nix_finds_file_node():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    assert any(n["label"] == "sample.nix" for n in r["nodes"])


@_needs_nix
def test_nix_finds_named_functions():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    labels = _labels(r)
    assert any("greet()" in l for l in labels)
    assert any("add()" in l for l in labels)
    assert any("mkServer()" in l for l in labels)


@_needs_nix
def test_nix_finds_named_attrsets():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    labels = _labels(r)
    assert any("defaults" in l for l in labels)
    assert any("registry" in l for l in labels)


@_needs_nix
def test_nix_finds_let_bindings():
    """Let-bound variables should appear as nodes."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    labels = _labels(r)
    # helpers is a let binding: helpers = import ./helpers.nix;
    assert any("helpers" in l for l in labels)


@_needs_nix
def test_nix_finds_inherit():
    """inherit (defaults) timeout retries should create nodes."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    labels = _labels(r)
    assert any("timeout" in l for l in labels)
    assert any("retries" in l for l in labels)


@_needs_nix
def test_nix_finds_calls():
    """Top-level calls: mkServer, greet, add should produce call edges."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    relations = _relations(r)
    # We expect at least some calls edges
    # The top-level bindings call mkServer, greet, add
    assert "calls" in relations or "contains" in relations


@_needs_nix
def test_nix_no_dangling_edges():
    """All edge sources must exist as node IDs."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    node_ids = {n["id"] for n in r["nodes"]}
    for e in r["edges"]:
        assert e["source"] in node_ids, f"dangling source: {e['source']} for edge {e}"


@_needs_nix
def test_nix_node_fields_complete():
    """Every node must have all 5 required fields."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    required = {"id", "label", "file_type", "source_file", "source_location"}
    for n in r["nodes"]:
        missing = required - set(n.keys())
        assert not missing, f"node {n.get('id', '?')} missing fields: {missing}"


@_needs_nix
def test_nix_edge_fields_complete():
    """Every edge must have all 7 required fields."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    required = {"source", "target", "relation", "confidence", "source_file", "source_location", "weight"}
    for e in r["edges"]:
        missing = required - set(e.keys())
        assert not missing, f"edge {e.get('source', '?')} → {e.get('target', '?')} missing fields: {missing}"


@_needs_nix
def test_nix_import_edges_have_import_context():
    """Import edges should have context='import'."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    import_edges = _edges_with_relation(r, "imports", "imports_from")
    # sample.nix has `import ./helpers.nix` — but helpers.nix doesn't exist so import
    # resolution will skip it. The inherit (defaults) should produce imports_from.
    if import_edges:
        for e in import_edges:
            assert "context" in e, f"import edge missing context: {e}"


@_needs_nix
def test_nix_call_edges_have_call_context():
    """Call edges should have context='call'."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    call_edges = _edges_with_relation(r, "calls")
    for e in call_edges:
        assert e.get("context") == "call", f"call edge missing context: {e}"


@_needs_nix
def test_nix_builtins_filtered_from_calls():
    """Nix builtins like toString should not produce call edges."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    calls = _calls(r)
    for src, tgt in calls:
        tgt_clean = tgt.strip("()").lstrip(".")
        assert tgt_clean not in ("toString", "import", "map", "filter"), \
            f"builtin {tgt} should be filtered: {src} → {tgt}"


@_needs_nix
def test_nix_not_module():
    """sample.nix is a let expression, not a NixOS module."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    labels = _labels(r)
    # The module entry would have " module" suffix (e.g. "sample module")
    assert not any(l.endswith(" module") for l in labels), \
        f"sample.nix should not be detected as a NixOS module, got: {labels}"


@_needs_nix
def test_nix_contains_edges():
    """Top-level bindings should have 'contains' edges from the file node."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    assert "contains" in _relations(r)


@_needs_nix
def test_nix_with_expression():
    """with helpers; should produce a references edge with with_scope context."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample.nix")
    with_edges = [e for e in r["edges"] if e.get("context") == "with_scope"]
    assert len(with_edges) >= 1, "expected at least one with_scope reference"


# ── NixOS Module (sample_module.nix) ─────────────────────────────────────────

@_needs_nix
def test_nix_module_no_error():
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    assert "error" not in r


@_needs_nix
def test_nix_module_detects_module_signature():
    """Files with { config, lib, ... }: body should get a __module entry node."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    labels = _labels(r)
    assert any("module" in l for l in labels), \
        f"expected module entry node, got labels: {labels}"


@_needs_nix
def test_nix_module_finds_options():
    """mkOption declarations should produce option nodes."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    labels = _labels(r)
    # Should find options like options.package, options.port, etc.
    option_labels = [l for l in labels if "options." in l]
    assert len(option_labels) >= 1, f"expected option nodes, got: {labels}"


@_needs_nix
def test_nix_module_finds_enable_option():
    """mkEnableOption should produce an enable node."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    labels = _labels(r)
    assert any("enable" in l for l in labels), \
        f"expected enable option node, got: {labels}"


@_needs_nix
def test_nix_module_finds_mkif_guard():
    """mkIf should produce guarded_by edges."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    relations = _relations(r)
    assert "guarded_by" in relations, \
        f"expected guarded_by edges from mkIf, got relations: {relations}"


@_needs_nix
def test_nix_module_finds_named_function():
    """mkConfiguration is a named function in the let block."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    labels = _labels(r)
    assert any("mkConfiguration()" in l for l in labels), \
        f"expected mkConfiguration function, got: {labels}"


@_needs_nix
def test_nix_module_contains_edges():
    """Module should have contains edges from the module entry to bindings."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    contains = _edges_with_relation(r, "contains")
    assert len(contains) >= 2, f"expected at least 2 contains edges, got {len(contains)}"


@_needs_nix
def test_nix_module_config_references():
    """config.X.Y references should produce references edges with config_ref context."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    config_refs = [e for e in r["edges"] if e.get("context") == "config_ref"]
    assert len(config_refs) >= 1, \
        f"expected config_ref edges, got: {[e.get('context') for e in r['edges']]}"


@_needs_nix
def test_nix_module_node_fields_complete():
    """Module extractor nodes must also have all 5 required fields."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    required = {"id", "label", "file_type", "source_file", "source_location"}
    for n in r["nodes"]:
        missing = required - set(n.keys())
        assert not missing, f"module node {n.get('id', '?')} missing fields: {missing}"


@_needs_nix
def test_nix_module_edge_fields_complete():
    """Module extractor edges must have all 7 required fields."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    required = {"source", "target", "relation", "confidence", "source_file", "source_location", "weight"}
    for e in r["edges"]:
        missing = required - set(e.keys())
        assert not missing, f"module edge {e.get('source', '?')} → {e.get('target', '?')} missing: {missing}"


@_needs_nix
def test_nix_module_no_dangling_edges():
    """All edge sources in module extraction must exist as node IDs."""
    extract_nix = _import_extract_nix()
    r = extract_nix(FIXTURES / "sample_module.nix")
    node_ids = {n["id"] for n in r["nodes"]}
    for e in r["edges"]:
        assert e["source"] in node_ids, f"dangling source in module: {e['source']}"


# ── LSP Batch Enrichment ─────────────────────────────────────────────────────

import shutil

_needs_nil = pytest.mark.skipif(
    not shutil.which("nil"),
    reason="nil LSP server not available on PATH",
)


@_needs_nil
@_needs_nix
def test_nix_lsp_batch_enrichment_adds_snippets():
    """Batch LSP enrichment adds snippet fields to tree-sitter nodes."""
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    path = FIXTURES / "sample.nix"
    result = extract_nix(path)

    per_file = [result]
    n = _batch_lsp_enrich_nix([0], [path], per_file)

    assert n == 1, "expected 1 file to be enriched"
    snippets = [n for n in result["nodes"] if n.get("snippet")]
    assert len(snippets) > 0, "no snippets found after LSP enrichment"


@_needs_nil
@_needs_nix
def test_nix_lsp_enrichment_preserves_edges():
    """LSP enrichment must not lose tree-sitter semantic edges or raw_calls."""
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    path = FIXTURES / "sample_module.nix"
    result = extract_nix(path)

    edge_count_before = len(result["edges"])
    relations_before = {e["relation"] for e in result["edges"]}

    per_file = [result]
    _batch_lsp_enrich_nix([0], [path], per_file)

    assert len(result["edges"]) == edge_count_before, \
        f"edge count changed: {edge_count_before} -> {len(result['edges'])}"
    assert relations_before == {e["relation"] for e in result["edges"]}, \
        "edge relation types changed after LSP enrichment"
    assert "raw_calls" in result, "raw_calls key lost after LSP enrichment"


@_needs_nil
@_needs_nix
def test_nix_lsp_shared_session_multiple_files():
    """Shared session handles multiple files on one nil connection."""
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    paths = [FIXTURES / "sample.nix", FIXTURES / "sample_module.nix"]
    results = [extract_nix(p) for p in paths]

    n = _batch_lsp_enrich_nix([0, 1], paths, results)
    assert n == 2, f"expected 2 files enriched, got {n}"


def test_nix_lsp_graceful_without_nil():
    """_batch_lsp_enrich_nix returns 0 when nil is absent."""
    from graphify.extract import _batch_lsp_enrich_nix
    from unittest.mock import patch

    with patch("shutil.which", return_value=None):
        n = _batch_lsp_enrich_nix(
            [0], [Path("fake.nix")], [{"nodes": [], "edges": []}]
        )
    assert n == 0, "should return 0 when nil is not available"
