#!/usr/bin/env python3
"""Benchmark nil LSP symbol extraction for Nix files.

Usage:
    python scripts/benchmark_lsp_nix.py [FILE_PATH]
    python scripts/benchmark_lsp_nix.py --batch DIR_PATH   # shared-session benchmark
"""
import sys
import os
import time
from pathlib import Path

# Add graphify to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graphify.lsp_client import LspClient


def print_symbols(symbols, level=0):
    for sym in symbols:
        name = sym.get("name", "Unknown")
        kind = sym.get("kind", 0)
        rng = sym.get("range", {}).get("start", {}).get("line", 0)
        print("  " * level + f"- {name} (kind: {kind}, line: {rng})")
        if "children" in sym and sym["children"]:
            print_symbols(sym["children"], level + 1)


def count_symbols(symbols):
    count = len(symbols)
    for sym in symbols:
        if "children" in sym:
            count += count_symbols(sym["children"])
    return count


def benchmark_single(target_file):
    """Benchmark a single file with a fresh nil process."""
    if not os.path.exists(target_file):
        print(f"File not found: {target_file}")
        sys.exit(1)

    with open(target_file, "r") as f:
        content = f.read()

    print("Starting LSP Client (nil)...")

    try:
        start_time = time.time()
        with LspClient("nil") as client:
            # Initialize
            print("Initializing...")
            root_uri = f"file://{Path(target_file).parent}"
            client.initialize(root_uri)

            # Open file
            print("Opening document...")
            uri = f"file://{target_file}"
            client.did_open(uri, content)

            # Request symbols
            print("Requesting document symbols...")
            symbol_start = time.time()
            symbols = client.document_symbol(uri)
            symbol_end = time.time()

            client.did_close(uri)

        end_time = time.time()

        total_symbols = count_symbols(symbols)

        print("\n--- Benchmark Results ---")
        print(f"Total time (including spawn & init): {(end_time - start_time)*1000:.2f} ms")
        print(f"Symbol request time: {(symbol_end - symbol_start)*1000:.2f} ms")
        print(f"Total symbols extracted: {total_symbols}")
        print("\n--- Symbol Tree (First 2 Levels) ---")

        for sym in symbols:
            name = sym.get("name", "Unknown")
            rng = sym.get("range", {}).get("start", {}).get("line", 0)
            print(f"- {name} (line: {rng})")
            if "children" in sym and sym["children"]:
                for child in sym["children"]:
                    cname = child.get("name", "Unknown")
                    crng = child.get("range", {}).get("start", {}).get("line", 0)
                    print(f"  - {cname} (line: {crng})")
                    if "children" in child and child["children"]:
                        print(f"    - ... ({len(child['children'])} more children)")

    except Exception as e:
        print(f"Error: {e}")


def benchmark_batch(dir_path):
    """Benchmark multiple .nix files with a shared nil session."""
    nix_files = sorted(Path(dir_path).rglob("*.nix"))
    if not nix_files:
        print(f"No .nix files found in {dir_path}")
        sys.exit(1)

    print(f"Found {len(nix_files)} .nix files in {dir_path}")

    # --- Shared session ---
    print("\n--- Shared Session Benchmark ---")
    start_shared = time.time()
    total_symbols_shared = 0

    try:
        with LspClient("nil") as client:
            workspace_root = Path(dir_path).absolute()
            client.initialize(f"file://{workspace_root}")

            for nix_file in nix_files:
                content = nix_file.read_text(encoding="utf-8", errors="replace")
                uri = f"file://{nix_file.absolute()}"
                client.did_open(uri, content)
                symbols = client.document_symbol(uri)
                total_symbols_shared += count_symbols(symbols)
                client.did_close(uri)

    except Exception as e:
        print(f"Shared session error: {e}")

    end_shared = time.time()
    shared_ms = (end_shared - start_shared) * 1000

    # --- Individual spawns ---
    print("\n--- Individual Spawn Benchmark ---")
    start_individual = time.time()
    total_symbols_individual = 0

    for nix_file in nix_files:
        try:
            content = nix_file.read_text(encoding="utf-8", errors="replace")
            with LspClient("nil") as client:
                client.initialize(f"file://{nix_file.parent.absolute()}")
                uri = f"file://{nix_file.absolute()}"
                client.did_open(uri, content)
                symbols = client.document_symbol(uri)
                total_symbols_individual += count_symbols(symbols)
                client.did_close(uri)
        except Exception:
            pass

    end_individual = time.time()
    individual_ms = (end_individual - start_individual) * 1000

    print(f"\n--- Comparison ---")
    print(f"Files:             {len(nix_files)}")
    print(f"Shared session:    {shared_ms:.0f} ms ({total_symbols_shared} symbols)")
    print(f"Individual spawns: {individual_ms:.0f} ms ({total_symbols_individual} symbols)")
    print(f"Speedup:           {individual_ms / shared_ms:.1f}x")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--batch":
        benchmark_batch(sys.argv[2])
    elif len(sys.argv) >= 2:
        benchmark_single(sys.argv[1])
    else:
        print(__doc__.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
