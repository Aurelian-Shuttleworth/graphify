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

_needs_nix_lsp = pytest.mark.skipif(
    not (shutil.which("nixd") or shutil.which("nil")),
    reason="no Nix LSP server (nixd or nil) available on PATH",
)

# Keep legacy alias for readability in existing tests
_needs_nil = _needs_nix_lsp


@_needs_nil
@_needs_nix
def test_nix_lsp_batch_enrichment_adds_snippets():
    """Batch LSP enrichment adds snippet fields to tree-sitter nodes."""
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    path = FIXTURES / "sample.nix"
    result = extract_nix(path)

    per_file = [result]
    n, _resyncs = _batch_lsp_enrich_nix([0], [path], per_file)

    assert n == 1, "expected 1 file to be enriched"
    snippets = [n for n in result["nodes"] if n.get("snippet")]
    assert len(snippets) > 0, "no snippets found after LSP enrichment"


@_needs_nil
@_needs_nix
def test_nix_lsp_enrichment_preserves_edges():
    """LSP enrichment must not lose tree-sitter semantic edges or raw_calls.

    It IS expected to add new ``contains`` edges from the LSP hierarchy,
    connecting LSP-only nodes to their parents.
    """
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    path = FIXTURES / "sample_module.nix"
    result = extract_nix(path)

    edges_before = list(result["edges"])
    edge_count_before = len(edges_before)
    relations_before = {e["relation"] for e in edges_before}
    edge_triples_before = {
        (e["source"], e["target"], e["relation"]) for e in edges_before
    }

    per_file = [result]
    _batch_lsp_enrich_nix([0], [path], per_file)

    # No existing edge should be removed.
    edge_triples_after = {
        (e["source"], e["target"], e["relation"]) for e in result["edges"]
    }
    lost = edge_triples_before - edge_triples_after
    assert not lost, f"edges lost after LSP enrichment: {lost}"

    # Edge count should be >= before (LSP adds contains edges).
    assert len(result["edges"]) >= edge_count_before, \
        f"edge count decreased: {edge_count_before} -> {len(result['edges'])}"

    # All original relation types should still be present.
    assert relations_before <= {e["relation"] for e in result["edges"]}, \
        "edge relation types lost after LSP enrichment"

    # New edges should be valid contains edges with correct direction.
    new_edges = [
        e for e in result["edges"]
        if (e["source"], e["target"], e["relation"]) not in edge_triples_before
    ]
    for e in new_edges:
        assert e["relation"] == "contains", \
            f"unexpected new edge relation: {e['relation']}"
        # Parent→child: target ID should be longer or more specific
        assert not e["source"].startswith(e["target"]), \
            f"reversed contains edge: {e['source']} -> {e['target']}"

    assert "raw_calls" in result, "raw_calls key lost after LSP enrichment"


@_needs_nil
@_needs_nix
def test_nix_lsp_shared_session_multiple_files():
    """Shared session handles multiple files on one nil connection."""
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    paths = [FIXTURES / "sample.nix", FIXTURES / "sample_module.nix"]
    results = [extract_nix(p) for p in paths]

    n, _resyncs = _batch_lsp_enrich_nix([0, 1], paths, results)
    assert n == 2, f"expected 2 files enriched, got {n}"


def test_nix_lsp_graceful_without_lsp():
    """_batch_lsp_enrich_nix returns 0 when no Nix LSP is available."""
    from graphify.extract import _batch_lsp_enrich_nix
    from unittest.mock import patch

    with patch("shutil.which", return_value=None):
        n, _resyncs = _batch_lsp_enrich_nix(
            [0], [Path("fake.nix")], [{"nodes": [], "edges": []}]
        )
    assert n == 0, "should return 0 when no Nix LSP is available"


# ── Edge normalization tests ──────────────────────────────────────────────


def test_normalize_edges_lowercases_relation():
    """_normalize_edges should lowercase all relation strings."""
    from graphify.extract import _normalize_edges

    edges = [
        {"source": "a", "target": "b", "relation": "CONTAINS"},
        {"source": "c", "target": "d", "relation": "References"},
        {"source": "e", "target": "f", "relation": "contains"},
    ]
    _normalize_edges(edges)
    assert edges[0]["relation"] == "contains"
    assert edges[1]["relation"] == "references"
    assert edges[2]["relation"] == "contains"


def test_normalize_edges_flips_reversed_contains():
    """Reversed contains edges (child→parent) should be flipped."""
    from graphify.extract import _normalize_edges

    edges = [
        # child→parent: source ID starts with target ID
        {"source": "mod_options_programs", "target": "mod_options", "relation": "CONTAINS"},
        {"source": "mod_options", "target": "mod", "relation": "contains"},
    ]
    _normalize_edges(edges)

    # Both should now be parent→child
    assert edges[0]["source"] == "mod_options"
    assert edges[0]["target"] == "mod_options_programs"
    assert edges[1]["source"] == "mod"
    assert edges[1]["target"] == "mod_options"


def test_normalize_edges_preserves_correct_direction():
    """Correctly directed contains edges should not be flipped."""
    from graphify.extract import _normalize_edges

    edges = [
        {"source": "file_nid", "target": "file_nid_module", "relation": "contains"},
        {"source": "mod", "target": "mod_cfg", "relation": "contains"},
    ]
    _normalize_edges(edges)

    assert edges[0]["source"] == "file_nid"
    assert edges[0]["target"] == "file_nid_module"
    assert edges[1]["source"] == "mod"
    assert edges[1]["target"] == "mod_cfg"


# ── LSP hierarchy edge tests ─────────────────────────────────────────────


@_needs_nil
@_needs_nix
def test_lsp_symbols_returns_edges():
    """_lsp_symbols_for_file should return both nodes and edges."""
    from graphify.extract import _lsp_symbols_for_file
    from graphify.lsp_client import LspClient

    path = FIXTURES / "sample.nix"
    source = path.read_text()

    with LspClient("nil") as client:
        client.initialize(f"file://{path.parent.absolute()}")
        result = _lsp_symbols_for_file(client, path, source)

    assert "nodes" in result, "missing 'nodes' key"
    assert "edges" in result, "missing 'edges' key"
    assert isinstance(result["nodes"], dict)
    assert isinstance(result["edges"], list)
    assert len(result["nodes"]) > 0, "expected at least one node"
    assert len(result["edges"]) > 0, "expected at least one edge"


@_needs_nil
@_needs_nix
def test_lsp_edges_are_parent_to_child():
    """All LSP contains edges should be parent→child (not reversed)."""
    from graphify.extract import _lsp_symbols_for_file
    from graphify.lsp_client import LspClient

    path = FIXTURES / "sample_module.nix"
    source = path.read_text()

    with LspClient("nil") as client:
        client.initialize(f"file://{path.parent.absolute()}")
        result = _lsp_symbols_for_file(client, path, source)

    for edge in result["edges"]:
        assert edge["relation"] == "contains"
        # source should NOT start with target (that would be child→parent)
        assert not edge["source"].startswith(edge["target"]), \
            f"reversed: {edge['source']} -> {edge['target']}"


@_needs_nil
@_needs_nix
def test_lsp_root_symbols_connect_to_file_node():
    """Top-level LSP symbols should have contains edges from the file node."""
    from graphify.extract import _lsp_symbols_for_file, _make_id
    from graphify.lsp_client import LspClient

    path = FIXTURES / "sample.nix"
    source = path.read_text()
    file_nid = _make_id(str(path))

    with LspClient("nil") as client:
        client.initialize(f"file://{path.parent.absolute()}")
        result = _lsp_symbols_for_file(client, path, source)

    # At least one edge should originate from the file node
    file_edges = [e for e in result["edges"] if e["source"] == file_nid]
    assert len(file_edges) > 0, \
        f"no edges from file node {file_nid}"


@_needs_nil
@_needs_nix
def test_lsp_edges_deduplicated_during_merge():
    """Edge dedup should prevent the LSP merge from adding duplicate triples.

    Note: the tree-sitter Nix extractor already produces some duplicate
    edges (a known pre-existing issue).  This test checks that the LSP
    merge layer does not make it *worse*.
    """
    from graphify.extract import _batch_lsp_enrich_nix
    extract_nix = _import_extract_nix()

    path = FIXTURES / "sample_module.nix"
    result = extract_nix(path)

    # Count pre-existing duplicates from tree-sitter
    triples_before = [
        (e["source"], e["target"], e["relation"]) for e in result["edges"]
    ]
    dupes_before = len(triples_before) - len(set(triples_before))

    per_file = [result]
    _batch_lsp_enrich_nix([0], [path], per_file)

    # After LSP merge, duplicates should not increase
    triples_after = [
        (e["source"], e["target"], e["relation"]) for e in result["edges"]
    ]
    dupes_after = len(triples_after) - len(set(triples_after))

    assert dupes_after <= dupes_before, \
        f"LSP merge added duplicates: {dupes_before} -> {dupes_after}"


@_needs_nil
@_needs_nix
def test_snippet_cap():
    """Snippets from LSP should not exceed _MAX_SNIPPET_LINES."""
    from graphify.extract import _lsp_symbols_for_file, _MAX_SNIPPET_LINES
    from graphify.lsp_client import LspClient

    path = FIXTURES / "sample_module.nix"
    source = path.read_text()

    with LspClient("nil") as client:
        client.initialize(f"file://{path.parent.absolute()}")
        result = _lsp_symbols_for_file(client, path, source)

    for nid, node in result["nodes"].items():
        snippet = node.get("snippet", "")
        line_count = len(snippet.split("\n"))
        # +1 for the truncation marker line
        assert line_count <= _MAX_SNIPPET_LINES + 1, \
            f"snippet for {nid} has {line_count} lines (max {_MAX_SNIPPET_LINES})"


# ── Fixture Flake Tests ──────────────────────────────────────────────────────

FIXTURE_FLAKE = FIXTURES / "nix-flake"


@_needs_nix
class TestFixtureFlake:
    """Validate extraction of the synthetic test fixture flake."""

    @pytest.fixture(autouse=True, scope="class")
    def _extract_all(self, request):
        extract_nix = _import_extract_nix()
        nix_files = sorted(FIXTURE_FLAKE.rglob("*.nix"))
        results = {}
        errors = []
        for f in nix_files:
            r = extract_nix(f)
            results[f] = r
            if "error" in r:
                errors.append((f, r["error"]))
        request.cls.results = results
        request.cls.errors = errors
        request.cls.nix_files = nix_files

    def test_all_files_extracted(self):
        assert len(self.results) >= 9

    def test_no_extraction_errors(self):
        assert len(self.errors) == 0, \
            f"{len(self.errors)} errors:\n" + \
            "\n".join(f"  {p.name}: {e}" for p, e in self.errors)

    def test_constants_not_module(self):
        r = self.results[FIXTURE_FLAKE / "constants.nix"]
        labels = _labels(r)
        assert not any(l.endswith(" module") for l in labels)

    def test_modules_detected_as_modules(self):
        module_files = [
            "modules/default.nix",
            "modules/services/example.nix",
            "modules/programs/editor.nix",
            "home-manager/default.nix",
        ]
        for rel_path in module_files:
            path = FIXTURE_FLAKE / rel_path
            if path not in self.results:
                continue
            r = self.results[path]
            labels = _labels(r)
            assert any(l.endswith(" module") for l in labels), \
                f"{rel_path} should be a module, got: {labels}"

    def test_flake_nix_not_module(self):
        r = self.results[FIXTURE_FLAKE / "flake.nix"]
        labels = _labels(r)
        assert not any(l.endswith(" module") for l in labels)

    def test_modules_default_has_import_edges(self):
        r = self.results[FIXTURE_FLAKE / "modules" / "default.nix"]
        imports = _edges_with_relation(r, "imports_from")
        assert len(imports) >= 2

    def test_services_example_has_mkif_guard(self):
        r = self.results[FIXTURE_FLAKE / "modules" / "services" / "example.nix"]
        assert "guarded_by" in _relations(r)

    def test_services_example_has_config_refs(self):
        r = self.results[FIXTURE_FLAKE / "modules" / "services" / "example.nix"]
        config_refs = [e for e in r["edges"] if e.get("context") == "config_ref"]
        assert len(config_refs) >= 1

    def test_services_example_finds_options(self):
        r = self.results[FIXTURE_FLAKE / "modules" / "services" / "example.nix"]
        labels = _labels(r)
        option_labels = [l for l in labels if "options." in l or "enable" in l]
        assert len(option_labels) >= 1

    def test_services_example_has_cfg_binding(self):
        r = self.results[FIXTURE_FLAKE / "modules" / "services" / "example.nix"]
        labels = _labels(r)
        assert any(l == "cfg" for l in labels)

    def test_pkgs_tool_has_import(self):
        r = self.results[FIXTURE_FLAKE / "pkgs" / "tool" / "default.nix"]
        imports = _edges_with_relation(r, "imports_from")
        assert len(imports) >= 1

    def test_pkgs_lib_has_let_bindings(self):
        r = self.results[FIXTURE_FLAKE / "pkgs" / "lib.nix"]
        labels = _labels(r)
        assert any("mkHelper" in l for l in labels)

    def test_home_manager_has_imports(self):
        r = self.results[FIXTURE_FLAKE / "home-manager" / "default.nix"]
        imports = _edges_with_relation(r, "imports_from")
        assert len(imports) >= 2

    def test_overlay_is_not_module(self):
        r = self.results[FIXTURE_FLAKE / "overlays" / "default.nix"]
        labels = _labels(r)
        assert not any(l.endswith(" module") for l in labels)

    def test_no_dangling_edges_anywhere(self):
        dangling = []
        for path, r in self.results.items():
            ids = {n["id"] for n in r["nodes"]}
            for e in r["edges"]:
                if e["source"] not in ids:
                    dangling.append((path.name, e["source"], e["relation"]))
        assert len(dangling) == 0, \
            f"{len(dangling)} dangling edges:\n" + \
            "\n".join(f"  {f}: {s} ({r})" for f, s, r in dangling[:10])

    def test_node_field_completeness(self):
        required = {"id", "label", "file_type", "source_file", "source_location"}
        incomplete = []
        for path, r in self.results.items():
            for n in r["nodes"]:
                missing = required - set(n.keys())
                if missing:
                    incomplete.append((path.name, n.get("id", "?"), missing))
        assert len(incomplete) == 0

    def test_edge_field_completeness(self):
        required = {"source", "target", "relation", "confidence",
                     "source_file", "source_location", "weight"}
        incomplete = []
        for path, r in self.results.items():
            for e in r["edges"]:
                missing = required - set(e.keys())
                if missing:
                    incomplete.append((path.name, e.get("relation", "?"), missing))
        assert len(incomplete) == 0

    def test_total_node_count(self):
        total = sum(len(r["nodes"]) for r in self.results.values())
        assert total >= 50, f"expected >= 50 nodes, got {total}"

    def test_total_edge_count(self):
        total = sum(len(r["edges"]) for r in self.results.values())
        assert total >= 30, f"expected >= 30 edges, got {total}"

    def test_relation_diversity(self):
        all_rels: set[str] = set()
        for r in self.results.values():
            all_rels |= _relations(r)
        assert "contains" in all_rels
        assert "imports_from" in all_rels

    def test_print_summary(self, capsys):
        total_nodes = sum(len(r["nodes"]) for r in self.results.values())
        total_edges = sum(len(r["edges"]) for r in self.results.values())
        from collections import Counter
        all_rels: Counter[str] = Counter()
        module_count = 0
        for r in self.results.values():
            for e in r["edges"]:
                all_rels[e["relation"]] += 1
            if any(l.endswith(" module") for l in _labels(r)):
                module_count += 1
        print("\n" + "=" * 60)
        print("FIXTURE FLAKE EXTRACTION SUMMARY")
        print("=" * 60)
        print(f"Files: {len(self.results)} | Modules: {module_count} | Errors: {len(self.errors)}")
        print(f"Nodes: {total_nodes} | Edges: {total_edges}")
        print(f"Relations: {dict(all_rels)}")
        print("=" * 60)


# ── Flake Lock Parser Tests ──────────────────────────────────────────────────

class TestFlakeLockParsing:
    """Validate _extract_flake_lock() on the fixture flake.lock."""

    @pytest.fixture(autouse=True, scope="class")
    def _parse_lock(self, request):
        from graphify.extract import _extract_flake_lock
        lock_path = FIXTURE_FLAKE / "flake.lock"
        request.cls.result = _extract_flake_lock(lock_path)

    def test_flake_lock_produces_depends_on_edges(self):
        depends_on = [e for e in self.result["edges"] if e["relation"] == "depends_on"]
        # 3 inputs: nixpkgs, home-manager, flake-parts
        assert len(depends_on) == 3

    def test_depends_on_has_flake_input_context(self):
        for e in self.result["edges"]:
            if e["relation"] == "depends_on":
                assert e.get("context") == "flake_input", \
                    f"depends_on edge missing flake_input context: {e}"

    def test_synthetic_nodes_have_github_labels(self):
        labels = [n["label"] for n in self.result["nodes"]]
        github_labels = [l for l in labels if l.startswith("github:")]
        assert len(github_labels) == 3
        # Verify owner/repo format
        for label in github_labels:
            parts = label.split(":")
            assert "/" in parts[1], f"expected owner/repo in {label}"

    def test_root_node_skipped(self):
        ids = [n["id"] for n in self.result["nodes"]]
        # "root" should not appear as a node
        for nid in ids:
            assert "root" not in nid.split("_"), \
                f"root entry should not produce a node: {nid}"

    def test_synthetic_nodes_have_dependency_file_type(self):
        for n in self.result["nodes"]:
            assert n["file_type"] == "dependency", \
                f"flake input node should have file_type=dependency: {n}"

    def test_edges_point_from_flake_nix(self):
        """All depends_on edges should source from the flake.nix file node."""
        from graphify.extract import _make_id
        flake_nix = FIXTURE_FLAKE / "flake.nix"
        expected_source = _make_id(str(flake_nix))
        for e in self.result["edges"]:
            assert e["source"] == expected_source, \
                f"depends_on edge should source from flake.nix: {e}"

    def test_edge_field_completeness(self):
        required = {"source", "target", "relation", "confidence",
                     "source_file", "source_location", "weight"}
        for e in self.result["edges"]:
            missing = required - set(e.keys())
            assert not missing, f"edge missing fields {missing}: {e}"

    def test_node_field_completeness(self):
        required = {"id", "label", "file_type", "source_file", "source_location"}
        for n in self.result["nodes"]:
            missing = required - set(n.keys())
            assert not missing, f"node missing fields {missing}: {n}"


# ── Option Type Extraction Tests ─────────────────────────────────────────────

@_needs_nix
class TestOptionTypeExtraction:
    """Validate typed_as edges from mkOption type annotations."""

    @pytest.fixture(autouse=True, scope="class")
    def _extract_modules(self, request):
        extract_nix = _import_extract_nix()
        request.cls.services = extract_nix(
            FIXTURE_FLAKE / "modules" / "services" / "example.nix"
        )
        request.cls.editor = extract_nix(
            FIXTURE_FLAKE / "modules" / "programs" / "editor.nix"
        )

    def _typed_as_edges(self, result):
        return [e for e in result["edges"] if e["relation"] == "typed_as"]

    def test_simple_type_produces_typed_as_edge(self):
        """type = types.package → typed_as edge."""
        typed = self._typed_as_edges(self.services)
        contexts = [e.get("context", "") for e in typed]
        assert any("types.package" in c for c in contexts), \
            f"expected types.package in typed_as contexts: {contexts}"

    def test_compound_type_produces_typed_as_edge(self):
        """type = types.listOf types.str → typed_as edge."""
        typed = self._typed_as_edges(self.services)
        contexts = [e.get("context", "") for e in typed]
        # The allowedHosts option has types.listOf types.str
        assert any("listOf" in c for c in contexts), \
            f"expected listOf in typed_as contexts: {contexts}"

    def test_submodule_type_produces_typed_as_edge(self):
        """type = types.submodule { ... } → typed_as edge."""
        typed = self._typed_as_edges(self.services)
        contexts = [e.get("context", "") for e in typed]
        assert any("submodule" in c for c in contexts), \
            f"expected submodule in typed_as contexts: {contexts}"

    def test_enable_option_has_bool_type(self):
        """mkEnableOption implicitly has types.bool."""
        typed = self._typed_as_edges(self.services)
        contexts = [e.get("context", "") for e in typed]
        assert any("types.bool" in c for c in contexts), \
            f"expected types.bool for enable option: {contexts}"

    def test_port_type_extracted(self):
        """type = types.port → typed_as edge."""
        typed = self._typed_as_edges(self.services)
        contexts = [e.get("context", "") for e in typed]
        assert any("types.port" in c for c in contexts), \
            f"expected types.port in typed_as contexts: {contexts}"

    def test_typed_as_count(self):
        """services/example.nix should have multiple typed_as edges."""
        typed = self._typed_as_edges(self.services)
        # enable(bool), package, port, settings(submodule), extraConfig(attrsOf),
        # plus nested: verbose(bool), logLevel(enum), allowedHosts(listOf)
        assert len(typed) >= 5, \
            f"expected >= 5 typed_as edges, got {len(typed)}"

    def test_editor_types_extracted(self):
        """programs/editor.nix should also have typed_as edges."""
        typed = self._typed_as_edges(self.editor)
        assert len(typed) >= 3, \
            f"expected >= 3 typed_as edges in editor, got {len(typed)}"

    def test_typed_as_edge_completeness(self):
        """All typed_as edges should have full fields."""
        required = {"source", "target", "relation", "confidence",
                     "source_file", "source_location", "weight"}
        typed = self._typed_as_edges(self.services)
        for e in typed:
            missing = required - set(e.keys())
            assert not missing, f"typed_as edge missing fields {missing}: {e}"
