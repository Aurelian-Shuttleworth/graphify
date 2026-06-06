"""Multi-flake integration test: run the Nix extractor against three real flakes.

Validates that extract_nix correctly handles diverse real-world Nix patterns
across multiple production flakes: nix-darwin (~60 files), common-modules (~88),
and standards (~44).

Run with:
    uv run pytest tests/test_nix_real_flakes.py -v -s

Requires:
    - tree-sitter-nix (pip install graphify[nix])
    - At least one flake directory present on disk
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import importlib.util
import os
import pytest

# ── Configuration ────────────────────────────────────────────────────────────

FLAKES = {
    "nix-darwin": Path("/Users/aurelianshuttleworth/Workspace/Aurelian/nix/nix-darwin"),
    "common-modules": Path("/Users/aurelianshuttleworth/Workspace/Aurelian/shuttleworth-tech/nix/common-modules"),
    "standards": Path("/Users/aurelianshuttleworth/Workspace/Aurelian/shuttleworth-tech/company"),
}

_SKIP_DIRS = {"_archive", ".direnv", "graphify-out", ".cache", "result", ".git", ".opencode"}

_needs_nix = pytest.mark.skipif(
    importlib.util.find_spec("tree_sitter_nix") is None
    and not os.environ.get("GRAPHIFY_TREE_SITTER_NIX_PATH"),
    reason="tree-sitter-nix not available",
)


def _import_extract_nix():
    from graphify.extract import extract_nix
    return extract_nix


def _discover_nix_files(root: Path) -> list[Path]:
    """Find all .nix files under root, excluding build artifacts and caches."""
    return sorted(
        p for p in root.rglob("*.nix")
        if not any(skip in part for part in p.parts for skip in _SKIP_DIRS)
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _labels(r: dict) -> list[str]:
    return [n["label"] for n in r["nodes"]]


def _node_ids(r: dict) -> set[str]:
    return {n["id"] for n in r["nodes"]}


def _relations(r: dict) -> set[str]:
    return {e["relation"] for e in r["edges"]}


# ── Module-scoped extraction cache ──────────────────────────────────────────

_CACHE: dict[str, dict[Path, dict]] = {}
_ERRORS: dict[str, list[tuple[Path, str]]] = {}


def _get_flake_results(flake_name: str) -> dict[Path, dict]:
    """Extract all .nix files for a flake, caching results module-wide."""
    if flake_name in _CACHE:
        return _CACHE[flake_name]

    root = FLAKES[flake_name]
    if not (root / "flake.nix").exists():
        pytest.skip(f"Flake not found at {root}")

    extract_nix = _import_extract_nix()
    nix_files = _discover_nix_files(root)
    results = {}
    errors = []
    for f in nix_files:
        r = extract_nix(f)
        results[f] = r
        if "error" in r:
            errors.append((f, r["error"]))

    _CACHE[flake_name] = results
    _ERRORS[flake_name] = errors
    return results


def _get_flake_errors(flake_name: str) -> list[tuple[Path, str]]:
    _get_flake_results(flake_name)  # ensure populated
    return _ERRORS.get(flake_name, [])


# ══════════════════════════════════════════════════════════════════════════════
# 1. PER-FLAKE TESTS — parametrized over each flake
# ══════════════════════════════════════════════════════════════════════════════


@_needs_nix
@pytest.mark.parametrize("flake_name", FLAKES.keys())
class TestPerFlake:
    """Validate extraction quality for each individual flake."""

    def test_no_extraction_errors(self, flake_name: str):
        """Every .nix file should parse without error."""
        errors = _get_flake_errors(flake_name)
        assert len(errors) == 0, (
            f"{flake_name}: {len(errors)} files had errors:\n"
            + "\n".join(f"  {p.name}: {e}" for p, e in errors)
        )

    def test_no_dangling_source_edges(self, flake_name: str):
        """Every edge source should resolve to a real node."""
        results = _get_flake_results(flake_name)
        dangling = []
        for path, r in results.items():
            ids = _node_ids(r)
            for e in r["edges"]:
                if e["source"] not in ids:
                    dangling.append((path.name, e["source"], e["relation"]))
        assert len(dangling) == 0, (
            f"{flake_name}: {len(dangling)} dangling edges:\n"
            + "\n".join(f"  {f}: {s} ({rel})" for f, s, rel in dangling[:10])
        )

    def test_node_field_completeness(self, flake_name: str):
        """Every node must have all required fields."""
        required = {"id", "label", "file_type", "source_file", "source_location"}
        results = _get_flake_results(flake_name)
        incomplete = []
        for path, r in results.items():
            for n in r["nodes"]:
                missing = required - set(n.keys())
                if missing:
                    incomplete.append((path.name, n.get("id", "?"), missing))
        assert len(incomplete) == 0, (
            f"{flake_name}: nodes with missing fields:\n"
            + "\n".join(f"  {f}/{nid}: {m}" for f, nid, m in incomplete[:10])
        )

    def test_edge_field_completeness(self, flake_name: str):
        """Every edge must have all required fields."""
        required = {"source", "target", "relation", "confidence",
                     "source_file", "source_location", "weight"}
        results = _get_flake_results(flake_name)
        incomplete = []
        for path, r in results.items():
            for e in r["edges"]:
                missing = required - set(e.keys())
                if missing:
                    incomplete.append((path.name, e.get("relation", "?"), missing))
        assert len(incomplete) == 0, (
            f"{flake_name}: edges with missing fields:\n"
            + "\n".join(f"  {f} ({rel}): {m}" for f, rel, m in incomplete[:10])
        )

    def test_has_contains_and_imports(self, flake_name: str):
        """At least `contains` and `imports_from` relations should be present."""
        results = _get_flake_results(flake_name)
        all_relations: set[str] = set()
        for r in results.values():
            all_relations |= _relations(r)
        assert "contains" in all_relations, f"{flake_name}: missing 'contains'"
        assert "imports_from" in all_relations, f"{flake_name}: missing 'imports_from'"

    def test_flake_nix_not_module(self, flake_name: str):
        """flake.nix should NOT be detected as a NixOS module."""
        results = _get_flake_results(flake_name)
        root = FLAKES[flake_name]
        flake_path = root / "flake.nix"
        if flake_path not in results:
            pytest.skip("flake.nix not in results")
        r = results[flake_path]
        labels = _labels(r)
        assert not any(l.endswith(" module") for l in labels), (
            f"{flake_name}: flake.nix was incorrectly detected as a module"
        )

    def test_has_modules(self, flake_name: str):
        """Each flake should have at least some modules detected."""
        results = _get_flake_results(flake_name)
        module_files = [
            path.name for path, r in results.items()
            if any(l.endswith(" module") for l in _labels(r))
        ]
        # standards flake has mostly quality-gate configs, not NixOS modules
        min_modules = 2 if flake_name == "standards" else 5
        assert len(module_files) >= min_modules, (
            f"{flake_name}: expected ≥{min_modules} modules, got {len(module_files)}: {module_files}"
        )

    def test_no_blocklisted_call_targets(self, flake_name: str):
        """No call edge should target a Nix builtin or lib function."""
        from graphify.extract import _NIX_BUILTIN_BLOCKLIST, _NIX_LIB_BLOCKLIST
        blocklist = _NIX_BUILTIN_BLOCKLIST | _NIX_LIB_BLOCKLIST

        results = _get_flake_results(flake_name)
        node_labels = {}
        for r in results.values():
            for n in r["nodes"]:
                node_labels[n["id"]] = n["label"]

        violations = []
        for path, r in results.items():
            for e in r["edges"]:
                if e["relation"] == "calls":
                    tgt_label = node_labels.get(e["target"], "")
                    tgt_clean = tgt_label.strip("()").lstrip(".")
                    if tgt_clean in blocklist:
                        violations.append((path.name, tgt_clean))

        assert len(violations) == 0, (
            f"{flake_name}: call edges to blocklisted builtins:\n"
            + "\n".join(f"  {f}: {b}" for f, b in violations[:10])
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. CROSS-FLAKE TESTS — aggregate assertions
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
class TestCrossFlake:
    """Aggregate assertions across all available flakes."""

    @pytest.fixture(autouse=True, scope="class")
    def _extract_all(self, request):
        """Extract all flakes and store aggregate results."""
        all_results = {}
        for name in FLAKES:
            if (FLAKES[name] / "flake.nix").exists():
                all_results[name] = _get_flake_results(name)
        if not all_results:
            pytest.skip("No flake directories found")
        request.cls.all_results = all_results

    def test_total_file_coverage(self):
        """Should extract files from at least 150 .nix files total."""
        total = sum(len(results) for results in self.all_results.values())
        assert total >= 150, f"expected ≥150 total files, got {total}"

    def test_total_node_count(self):
        """Aggregate node count should be rich."""
        total = sum(
            len(r["nodes"])
            for results in self.all_results.values()
            for r in results.values()
        )
        assert total >= 2000, f"expected ≥2000 total nodes, got {total}"

    def test_total_import_edges(self):
        """Should have substantial import edge coverage."""
        total = sum(
            sum(1 for e in r["edges"] if e["relation"] == "imports_from")
            for results in self.all_results.values()
            for r in results.values()
        )
        assert total >= 100, f"expected ≥100 total import edges, got {total}"

    def test_function_body_walking_works(self):
        """At least one flake's flake.nix should have >20 nodes.

        Before function body walking, flake.nix only had 16 nodes.
        With function body walking, it should have 30+.
        """
        max_flake_nodes = 0
        for name, results in self.all_results.items():
            flake_path = FLAKES[name] / "flake.nix"
            if flake_path in results:
                count = len(results[flake_path]["nodes"])
                max_flake_nodes = max(max_flake_nodes, count)
        assert max_flake_nodes > 20, (
            f"expected >20 nodes in at least one flake.nix (proving function "
            f"body walking works), best was {max_flake_nodes}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. SUMMARY DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@_needs_nix
class TestSummary:
    """Print a summary dashboard of extraction metrics (always passes)."""

    def test_print_summary(self, capsys):
        # Collect stats per flake
        stats = []
        for name, root in FLAKES.items():
            if not (root / "flake.nix").exists():
                continue
            results = _get_flake_results(name)
            errors = _get_flake_errors(name)
            files = len(results)
            modules = sum(
                1 for r in results.values()
                if any(l.endswith(" module") for l in _labels(r))
            )
            nodes = sum(len(r["nodes"]) for r in results.values())
            edges = sum(len(r["edges"]) for r in results.values())
            imports = sum(
                sum(1 for e in r["edges"] if e["relation"] == "imports_from")
                for r in results.values()
            )
            stats.append({
                "name": name,
                "files": files,
                "modules": modules,
                "nodes": nodes,
                "edges": edges,
                "imports": imports,
                "errors": len(errors),
            })

        if not stats:
            pytest.skip("No flakes found")

        # Print dashboard
        sep = "═" * 63
        thin = "─" * 63
        header = f"{'Flake':<22} {'Files':>5}  {'Modules':>7}  {'Nodes':>5}  {'Edges':>5}  {'Imports':>7}  {'Errors':>6}"

        with capsys.disabled():
            print(f"\n{sep}")
            print("MULTI-FLAKE EXTRACTION SUMMARY")
            print(sep)
            print(header)
            for s in stats:
                print(
                    f"{s['name']:<22} {s['files']:>5}  {s['modules']:>7}  "
                    f"{s['nodes']:>5}  {s['edges']:>5}  {s['imports']:>7}  {s['errors']:>6}"
                )
            print(thin)
            print(
                f"{'TOTAL':<22} {sum(s['files'] for s in stats):>5}  "
                f"{sum(s['modules'] for s in stats):>7}  "
                f"{sum(s['nodes'] for s in stats):>5}  "
                f"{sum(s['edges'] for s in stats):>5}  "
                f"{sum(s['imports'] for s in stats):>7}  "
                f"{sum(s['errors'] for s in stats):>6}"
            )
            print(sep)
