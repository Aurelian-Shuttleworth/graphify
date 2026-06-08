#!/usr/bin/env python3
"""Verify that the hybrid LSP + tree-sitter extraction produces both
LSP-enriched labels and tree-sitter semantic edges. Includes accuracy
metrics comparing pure tree-sitter vs hybrid output.

Usage:
    python scripts/verify_lsp_graphify.py FILE_PATH
    python scripts/verify_lsp_graphify.py --batch DIR_PATH
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphify.extract import extract_nix, _batch_lsp_enrich_nix


def analyse_single(target_file: Path):
    """Analyse a single file: compare tree-sitter-only vs hybrid."""
    # Phase 1: tree-sitter extraction
    print(f"Extracting {target_file.name} via tree-sitter...")
    result = extract_nix(target_file)

    if "error" in result and result["error"]:
        print(f"  Error: {result['error']}")
        return None

    ts_nodes = len(result.get("nodes", []))
    ts_edges = len(result.get("edges", []))
    ts_raw_calls = len(result.get("raw_calls", []))
    ts_relations = {e["relation"] for e in result.get("edges", [])}
    ts_labels = {n["id"]: n["label"] for n in result.get("nodes", [])}

    # Phase 2: LSP enrichment
    if not shutil.which("nil"):
        print("  nil not on PATH — skipping LSP enrichment.")
        return None

    import copy
    result_copy = copy.deepcopy(result)  # preserve original for comparison

    per_file = [result_copy]
    n_enriched = _batch_lsp_enrich_nix([0], [target_file], per_file)

    if n_enriched == 0:
        print("  LSP enrichment returned 0 — nil may have failed on this file.")
        return None

    hybrid_nodes = len(result_copy.get("nodes", []))
    hybrid_edges = len(result_copy.get("edges", []))
    hybrid_labels = {n["id"]: n["label"] for n in result_copy.get("nodes", [])}
    snippets = [n for n in result_copy["nodes"] if n.get("snippet")]

    # Compare
    labels_changed = 0
    for nid, ts_label in ts_labels.items():
        hybrid_label = hybrid_labels.get(nid)
        if hybrid_label and hybrid_label != ts_label:
            labels_changed += 1

    lsp_only_nodes = hybrid_nodes - ts_nodes

    return {
        "file": target_file.name,
        "ts_nodes": ts_nodes,
        "ts_edges": ts_edges,
        "ts_raw_calls": ts_raw_calls,
        "ts_relations": ts_relations,
        "hybrid_nodes": hybrid_nodes,
        "hybrid_edges": hybrid_edges,
        "labels_changed": labels_changed,
        "lsp_only_nodes": lsp_only_nodes,
        "snippets": len(snippets),
        "ts_nodes_with_snippets": len([n for n in result["nodes"] if n.get("snippet")]),
    }


def print_single_report(stats):
    """Print a comparison report for a single file."""
    print(f"\n{'─' * 60}")
    print(f"  {stats['file']}")
    print(f"{'─' * 60}")
    print(f"                        Tree-sitter   Hybrid    Delta")
    print(f"  Nodes                 {stats['ts_nodes']:>10}   {stats['hybrid_nodes']:>6}   {stats['lsp_only_nodes']:>+5}")
    print(f"  Edges                 {stats['ts_edges']:>10}   {stats['hybrid_edges']:>6}   {stats['hybrid_edges'] - stats['ts_edges']:>+5}")
    print(f"  Raw calls             {stats['ts_raw_calls']:>10}")
    print(f"  Labels enriched                      {stats['labels_changed']:>6}")
    print(f"  LSP-only nodes                       {stats['lsp_only_nodes']:>6}")
    print(f"  Nodes with snippets   {stats['ts_nodes_with_snippets']:>10}   {stats['snippets']:>6}")
    print(f"  Edge types: {sorted(stats['ts_relations'])}")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    if sys.argv[1] == "--batch" and len(sys.argv) >= 3:
        dir_path = Path(sys.argv[2])
        nix_files = sorted(dir_path.rglob("*.nix"))
        if not nix_files:
            print(f"No .nix files found in {dir_path}")
            sys.exit(1)

        print(f"Analysing {len(nix_files)} .nix files in {dir_path}\n")

        totals = {
            "files": 0,
            "ts_nodes": 0, "hybrid_nodes": 0,
            "ts_edges": 0, "hybrid_edges": 0,
            "labels_changed": 0, "lsp_only_nodes": 0,
            "snippets": 0,
        }

        for nix_file in nix_files:
            stats = analyse_single(nix_file)
            if stats is None:
                continue
            print_single_report(stats)
            totals["files"] += 1
            for key in ("ts_nodes", "hybrid_nodes", "ts_edges", "hybrid_edges",
                        "labels_changed", "lsp_only_nodes", "snippets"):
                totals[key] += stats[key]

        print(f"\n{'═' * 60}")
        print(f"  TOTALS ({totals['files']} files)")
        print(f"{'═' * 60}")
        print(f"                        Tree-sitter   Hybrid    Delta")
        print(f"  Nodes                 {totals['ts_nodes']:>10}   {totals['hybrid_nodes']:>6}   {totals['lsp_only_nodes']:>+5}")
        print(f"  Edges                 {totals['ts_edges']:>10}   {totals['hybrid_edges']:>6}   {totals['hybrid_edges'] - totals['ts_edges']:>+5}")
        print(f"  Labels enriched                      {totals['labels_changed']:>6}")
        print(f"  LSP-only nodes                       {totals['lsp_only_nodes']:>6}")
        print(f"  Nodes with snippets                  {totals['snippets']:>6}")

        if totals["ts_nodes"] > 0:
            coverage = totals["labels_changed"] / totals["ts_nodes"] * 100
            print(f"\n  Enrichment coverage: {coverage:.1f}% of tree-sitter nodes got LSP labels")

    else:
        target = Path(sys.argv[1])
        if not target.exists():
            print(f"File not found: {target}")
            sys.exit(1)

        stats = analyse_single(target)
        if stats:
            print_single_report(stats)

            # Correctness assertions
            assert stats["hybrid_edges"] == stats["ts_edges"], \
                f"Edge count changed! {stats['ts_edges']} -> {stats['hybrid_edges']}"
            assert stats["snippets"] > 0, \
                "No snippets — LSP enrichment didn't attach source"

            print(f"\n  ✅ Correctness: edges preserved, snippets attached.")


if __name__ == "__main__":
    main()
