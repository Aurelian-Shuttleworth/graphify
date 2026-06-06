"""Integration test: run the Nix extractor against the real nix-darwin flake.

This is NOT a unit test — it validates that extract_nix correctly explores
a production flake with ~60 .nix files covering every major Nix pattern:
modules, imports, callPackage, mkOption, mkIf, inherit, let, flake outputs.

Run with:
    uv run pytest tests/test_nix_integration.py -v -s

Requires:
    - tree-sitter-nix (pip install graphifyy[nix])
    - The nix-darwin flake at FLAKE_ROOT (see below)
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import importlib.util
import os
import pytest

# ── Configuration ────────────────────────────────────────────────────────────

FLAKE_ROOT = Path(
    os.environ.get(
        "NIX_DARWIN_FLAKE_ROOT",
        "/Users/aurelianshuttleworth/Workspace/Aurelian/nix/nix-darwin",
    )
)

_needs_nix = pytest.mark.skipif(
    importlib.util.find_spec("tree_sitter_nix") is None
    and not os.environ.get("GRAPHIFY_TREE_SITTER_NIX_PATH"),
    reason="tree-sitter-nix not available",
)

_needs_flake = pytest.mark.skipif(
    not (FLAKE_ROOT / "flake.nix").exists(),
    reason=f"nix-darwin flake not found at {FLAKE_ROOT}",
)


def _import_extract_nix():
    from graphify.extract import extract_nix
    return extract_nix


# ── Helpers ──────────────────────────────────────────────────────────────────

def _labels(r: dict) -> list[str]:
    return [n["label"] for n in r["nodes"]]


def _relations(r: dict) -> set[str]:
    return {e["relation"] for e in r["edges"]}


def _edges_by_relation(r: dict, rel: str) -> list[dict]:
    return [e for e in r["edges"] if e["relation"] == rel]


def _edges_by_context(r: dict, ctx: str) -> list[dict]:
    return [e for e in r["edges"] if e.get("context") == ctx]


def _node_ids(r: dict) -> set[str]:
    return {n["id"] for n in r["nodes"]}


def _assert_no_error(r: dict, path: Path) -> None:
    assert "error" not in r, f"{path.name} extraction failed: {r.get('error')}"


def _assert_no_dangling_sources(r: dict, path: Path) -> None:
    ids = _node_ids(r)
    for e in r["edges"]:
        assert e["source"] in ids, (
            f"{path.name}: dangling source {e['source']} "
            f"in edge {e['relation']} → {e['target']}"
        )


def _assert_required_keys(r: dict, path: Path) -> None:
    assert "nodes" in r, f"{path.name}: missing 'nodes'"
    assert "edges" in r, f"{path.name}: missing 'edges'"
    assert "raw_calls" in r, f"{path.name}: missing 'raw_calls'"


# ══════════════════════════════════════════════════════════════════════════════
# 1. FLAKE.NIX — top-level attrset with outputs function
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestFlakeNix:
    """Validate extraction of the top-level flake.nix.

    Structure: { description; inputs = { ... }; outputs = inputs@{ ... }: ... }
    The walker walks function bodies for both structure and calls, so the
    outputs() body's let bindings, imports, and nested attrsets are all
    extracted as nodes and edges.
    """

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.r = extract_nix(FLAKE_ROOT / "flake.nix")

    def test_no_error(self):
        _assert_no_error(self.r, FLAKE_ROOT / "flake.nix")

    def test_required_keys(self):
        _assert_required_keys(self.r, FLAKE_ROOT / "flake.nix")

    def test_finds_file_node(self):
        assert any(n["label"] == "flake.nix" for n in self.r["nodes"])

    def test_not_detected_as_module(self):
        """Flake is a plain attrset, not a NixOS module."""
        assert not any(l.endswith(" module") for l in _labels(self.r)), \
            "flake.nix should not be detected as a module"

    def test_finds_outputs_function(self):
        """outputs = inputs@{ ... }: ... is a named function."""
        labels = _labels(self.r)
        assert any("outputs()" in l for l in labels), \
            f"expected outputs() function, got: {labels}"

    def test_finds_inputs_attrset(self):
        """inputs = { ... } is a named attrset."""
        labels = _labels(self.r)
        assert any("inputs" == l for l in labels), \
            f"expected inputs attrset, got: {labels}"

    def test_finds_input_entries(self):
        """Should find flake input names (nix-darwin, home-manager, etc.)."""
        labels = set(_labels(self.r))
        expected_inputs = {"nix-darwin", "home-manager", "antigravity"}
        found = expected_inputs & labels
        assert len(found) >= 2, \
            f"expected input entries, found: {found} from {labels}"

    def test_has_contains_edges(self):
        assert "contains" in _relations(self.r)

    def test_inputs_nested_structure(self):
        """Input entries should be nested under the inputs attrset."""
        contains = _edges_by_relation(self.r, "contains")
        # Find edges where source is the inputs node
        node_labels = {n["id"]: n["label"] for n in self.r["nodes"]}
        inputs_children = [
            node_labels.get(e["target"], "?")
            for e in contains
            if node_labels.get(e["source"]) == "inputs"
        ]
        assert len(inputs_children) >= 5, \
            f"expected ≥5 inputs children, got: {inputs_children}"

    def test_no_dangling_sources(self):
        _assert_no_dangling_sources(self.r, FLAKE_ROOT / "flake.nix")

    def test_node_count(self):
        """Flake with inputs + outputs body should produce 25+ nodes."""
        assert len(self.r["nodes"]) >= 25, \
            f"expected ≥25 nodes (inputs + function body content), got {len(self.r['nodes'])}"

    def test_function_body_let_bindings(self):
        """outputs() body let bindings should be extracted."""
        labels = set(_labels(self.r))
        expected = {"username", "system", "stateVersion", "constants"}
        found = expected & labels
        assert len(found) >= 3, \
            f"expected let bindings from outputs body, found: {found} in {labels}"

    def test_function_body_imports(self):
        """outputs() body contains import edges (./nix/shell.nix, etc.)."""
        imports = _edges_by_relation(self.r, "imports_from")
        assert len(imports) >= 1, \
            f"expected import edges from outputs body, got {len(imports)}"

    def test_has_import_relation(self):
        assert "imports_from" in _relations(self.r)


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONSTANTS.NIX — simple attrset (no module, no function)
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestConstantsNix:
    """Validate extraction of the plain attrset constants.nix."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.r = extract_nix(FLAKE_ROOT / "constants.nix")

    def test_no_error(self):
        _assert_no_error(self.r, FLAKE_ROOT / "constants.nix")

    def test_not_module(self):
        assert not any(l.endswith(" module") for l in _labels(self.r))

    def test_finds_username(self):
        labels = _labels(self.r)
        assert any("username" in l for l in labels), \
            f"expected username binding, got: {labels}"

    def test_finds_nested_attrsets(self):
        """Should find themes, fonts, git sub-attrsets."""
        labels = set(_labels(self.r))
        expected = {"themes", "fonts", "git"}
        found = expected & labels
        assert len(found) >= 2, \
            f"expected nested attrsets, found: {found}"

    def test_no_imports(self):
        """Pure data file — should have no import edges."""
        imports = _edges_by_relation(self.r, "imports_from")
        assert len(imports) == 0, \
            f"expected no imports in constants.nix, got {len(imports)}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, FLAKE_ROOT / "constants.nix")


# ══════════════════════════════════════════════════════════════════════════════
# 3. HOME-MANAGER/DEFAULT.NIX — parameterized attrset (NOT a module)
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestHomeManagerDefaultNix:
    """Validate home-manager/default.nix.

    This is a parameterized attrset { stateVersion, username, ... }: { ... }
    NOT a NixOS module (no config/lib/pkgs in formals).
    """

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "home-manager" / "default.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_has_import_edges(self):
        """This file imports many child modules — should have import edges."""
        imports = _edges_by_relation(self.r, "imports_from")
        assert len(imports) >= 5, \
            f"expected ≥5 import edges, got {len(imports)}"

    def test_imports_antigravity(self):
        targets = {e["target"] for e in _edges_by_relation(self.r, "imports_from")}
        assert any("antigravity" in t for t in targets), \
            f"expected import to antigravity module, got: {targets}"

    def test_rich_node_count(self):
        """A large file should produce many nodes."""
        assert len(self.r["nodes"]) >= 15, \
            f"expected ≥15 nodes, got {len(self.r['nodes'])}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 4. ANTIGRAVITY MODULE — NixOS module with mkOption, mkIf, imports
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestAntigravityModule:
    """Validate extraction of the antigravity module."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "home-manager" / "modules" / "antigravity" / "default.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_finds_cfg_binding(self):
        """cfg = config.programs.antigravity; should produce a node."""
        labels = _labels(self.r)
        assert any("cfg" == l for l in labels), \
            f"expected cfg binding, got: {labels}"

    def test_has_import_edges(self):
        """Should import at least ./mcp."""
        imports = _edges_by_relation(self.r, "imports_from")
        assert len(imports) >= 1, \
            f"expected import edges, got {len(imports)}"

    def test_has_contains_edges(self):
        assert "contains" in _relations(self.r)

    def test_rich_node_count(self):
        assert len(self.r["nodes"]) >= 5, \
            f"expected ≥5 nodes, got {len(self.r['nodes'])}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 5. TYPES.NIX — function returning type defs (NOT a standard module)
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestTypesNix:
    """Validate extraction of types.nix (function, not module)."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "home-manager" / "modules" / "antigravity" / "types.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_finds_type_definitions(self):
        """Should find mcpServerType or similar type bindings."""
        labels = _labels(self.r)
        type_labels = [l for l in labels if "Type" in l or "type" in l.lower()]
        assert len(type_labels) >= 1, \
            f"expected type definitions, got: {labels}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 6. MCP DEFAULT.NIX — module with callPackage + nested imports
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestMcpDefaultNix:
    """Validate MCP module with callPackage and child imports."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "home-manager" / "modules" / "antigravity" / "mcp" / "default.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_detected_as_module(self):
        assert any(l.endswith(" module") for l in _labels(self.r))

    def test_finds_cfg_binding(self):
        labels = _labels(self.r)
        assert any("cfg" in l for l in labels)

    def test_has_callpackage_imports(self):
        """pkgs.callPackage ./packages/X.nix {} should produce import edges."""
        cp_edges = _edges_by_context(self.r, "callPackage")
        assert len(cp_edges) >= 1, \
            f"expected callPackage import edges, contexts: {[e.get('context') for e in self.r['edges']]}"

    def test_has_import_edges(self):
        """Should have import edges for servers and packages."""
        all_imports = _edges_by_relation(self.r, "imports_from")
        assert len(all_imports) >= 3, \
            f"expected ≥3 import edges, got {len(all_imports)}"

    def test_mkif_guard(self):
        assert "guarded_by" in _relations(self.r)

    def test_config_refs(self):
        config_refs = _edges_by_context(self.r, "config_ref")
        assert len(config_refs) >= 1, \
            "expected config_ref edges from cfg.enable etc."

    def test_rich_node_count(self):
        """MCP module is large — should produce many nodes."""
        assert len(self.r["nodes"]) >= 20, \
            f"expected ≥20 nodes, got {len(self.r['nodes'])}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 7. PROGRAMS.NIX — program configs with many imports
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestProgramsNix:
    """Validate the programs.nix file."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "home-manager" / "programs.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_many_import_edges(self):
        """programs.nix imports many program config files."""
        imports = _edges_by_relation(self.r, "imports_from")
        assert len(imports) >= 5, \
            f"expected ≥5 import edges, got {len(imports)}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 8. DARWIN BASE — system-level config
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestDarwinBaseNix:
    """Validate darwin/base/default.nix."""

    @pytest.fixture(autouse=True)
    def _extract(self):
        extract_nix = _import_extract_nix()
        self.path = FLAKE_ROOT / "darwin" / "base" / "default.nix"
        self.r = extract_nix(self.path)

    def test_no_error(self):
        _assert_no_error(self.r, self.path)

    def test_imports_homebrew(self):
        targets = {e["target"] for e in _edges_by_relation(self.r, "imports_from")}
        assert any("homebrew" in t for t in targets), \
            f"expected import to homebrew.nix, got: {targets}"

    def test_rich_node_count(self):
        """Darwin base has many system settings — lots of nodes."""
        assert len(self.r["nodes"]) >= 30, \
            f"expected ≥30 nodes from darwin/base, got {len(self.r['nodes'])}"

    def test_no_dangling(self):
        _assert_no_dangling_sources(self.r, self.path)


# ══════════════════════════════════════════════════════════════════════════════
# 9. FULL FLAKE SWEEP — extract every .nix file, aggregate stats
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
@_needs_flake
class TestFullFlakeSweep:
    """Extract every .nix file in the flake and validate aggregate metrics."""

    @pytest.fixture(autouse=True, scope="class")
    def _extract_all(self, request):
        extract_nix = _import_extract_nix()
        nix_files = sorted(
            p for p in FLAKE_ROOT.rglob("*.nix")
            if not any(skip in str(p) for skip in (
                "_archive", ".direnv", "graphify-out", ".cache", "result"
            ))
        )
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
        """Every .nix file should produce a result."""
        assert len(self.results) >= 50, \
            f"expected ≥50 .nix files, found {len(self.results)}"

    def test_no_extraction_errors(self):
        """No file should produce an error."""
        assert len(self.errors) == 0, \
            f"{len(self.errors)} files had errors:\n" + \
            "\n".join(f"  {p.name}: {e}" for p, e in self.errors)

    def test_total_node_count(self):
        """The full flake should produce a rich graph."""
        total_nodes = sum(len(r["nodes"]) for r in self.results.values())
        assert total_nodes >= 1000, \
            f"expected ≥1000 total nodes across flake, got {total_nodes}"

    def test_total_edge_count(self):
        total_edges = sum(len(r["edges"]) for r in self.results.values())
        assert total_edges >= 1000, \
            f"expected ≥1000 total edges, got {total_edges}"

    def test_no_dangling_edges_anywhere(self):
        """No file in the entire flake should have dangling source edges."""
        dangling = []
        for path, r in self.results.items():
            ids = _node_ids(r)
            for e in r["edges"]:
                if e["source"] not in ids:
                    dangling.append((path.name, e["source"], e["relation"]))
        assert len(dangling) == 0, \
            f"{len(dangling)} dangling edges:\n" + \
            "\n".join(f"  {f}: {s} ({r})" for f, s, r in dangling[:10])

    def test_module_detection_count(self):
        """Should detect a reasonable number of modules."""
        module_files = []
        non_module_files = []
        for path, r in self.results.items():
            labels = _labels(r)
            if any(l.endswith(" module") for l in labels):
                module_files.append(path.name)
            else:
                non_module_files.append(path.name)
        assert len(module_files) >= 10, \
            f"expected ≥10 modules, got {len(module_files)}: {module_files}"
        # constants.nix should NOT be a module
        assert "constants.nix" in non_module_files

    def test_relation_diversity(self):
        """The full flake should exercise multiple relation types."""
        all_relations: set[str] = set()
        for r in self.results.values():
            all_relations |= _relations(r)
        assert "contains" in all_relations
        assert "imports_from" in all_relations

    def test_context_diversity(self):
        """Multiple edge contexts should appear across the flake."""
        all_contexts: Counter[str] = Counter()
        for r in self.results.values():
            for e in r["edges"]:
                ctx = e.get("context")
                if ctx:
                    all_contexts[ctx] += 1
        assert "import" in all_contexts, f"missing 'import'; got: {dict(all_contexts)}"

    def test_builtins_not_in_call_targets(self):
        """No call edge should target a Nix builtin or lib function."""
        from graphify.extract import _NIX_BUILTIN_BLOCKLIST, _NIX_LIB_BLOCKLIST
        blocklist = _NIX_BUILTIN_BLOCKLIST | _NIX_LIB_BLOCKLIST
        node_labels = {}
        for r in self.results.values():
            for n in r["nodes"]:
                node_labels[n["id"]] = n["label"]

        violations = []
        for path, r in self.results.items():
            for e in r["edges"]:
                if e["relation"] == "calls":
                    tgt_label = node_labels.get(e["target"], "")
                    tgt_clean = tgt_label.strip("()").lstrip(".")
                    if tgt_clean in blocklist:
                        violations.append((path.name, tgt_clean))

        assert len(violations) == 0, \
            f"call edges to blocklisted builtins:\n" + \
            "\n".join(f"  {f}: {b}" for f, b in violations[:10])

    def test_node_field_completeness(self):
        """Every node must have all required fields."""
        required = {"id", "label", "file_type", "source_file", "source_location"}
        incomplete = []
        for path, r in self.results.items():
            for n in r["nodes"]:
                missing = required - set(n.keys())
                if missing:
                    incomplete.append((path.name, n.get("id", "?"), missing))
        assert len(incomplete) == 0, \
            f"nodes with missing fields:\n" + \
            "\n".join(f"  {f}/{nid}: {m}" for f, nid, m in incomplete[:10])

    def test_edge_field_completeness(self):
        """Every edge must have all required fields."""
        required = {"source", "target", "relation", "confidence",
                     "source_file", "source_location", "weight"}
        incomplete = []
        for path, r in self.results.items():
            for e in r["edges"]:
                missing = required - set(e.keys())
                if missing:
                    incomplete.append((path.name, e.get("relation", "?"), missing))
        assert len(incomplete) == 0, \
            f"edges with missing fields:\n" + \
            "\n".join(f"  {f} ({rel}): {m}" for f, rel, m in incomplete[:10])

    def test_print_summary(self, capsys):
        """Print a summary of extraction metrics (always passes)."""
        total_nodes = sum(len(r["nodes"]) for r in self.results.values())
        total_edges = sum(len(r["edges"]) for r in self.results.values())
        total_calls = sum(len(r.get("raw_calls", [])) for r in self.results.values())

        all_relations: Counter[str] = Counter()
        all_contexts: Counter[str] = Counter()
        module_count = 0
        for r in self.results.values():
            for e in r["edges"]:
                all_relations[e["relation"]] += 1
                ctx = e.get("context")
                if ctx:
                    all_contexts[ctx] += 1
            if any(l.endswith(" module") for l in _labels(r)):
                module_count += 1

        print("\n" + "=" * 60)
        print("NIX-DARWIN FLAKE EXTRACTION SUMMARY")
        print("=" * 60)
        print(f"Files:       {len(self.results)}")
        print(f"Modules:     {module_count}")
        print(f"Errors:      {len(self.errors)}")
        print(f"Nodes:       {total_nodes}")
        print(f"Edges:       {total_edges}")
        print(f"Raw calls:   {total_calls}")
        print(f"\nRelations:   {dict(all_relations)}")
        print(f"Contexts:    {dict(all_contexts)}")
        print("=" * 60)
