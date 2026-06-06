import sys
import os
import time
import json
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

def main():
    target_file = "/Users/aurelianshuttleworth/Workspace/Aurelian/nix/nix-darwin/home-manager/modules/antigravity/mcp/default.nix"
    
    if not os.path.exists(target_file):
        print(f"File not found: {target_file}")
        sys.exit(1)
        
    with open(target_file, "r") as f:
        content = f.read()
        
    print("Starting LSP Client (nil)...")
    client = LspClient("nil")
    
    try:
        start_time = time.time()
        client.start()
        
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
        
        end_time = time.time()
        
        total_symbols = count_symbols(symbols)
        
        print("\n--- Benchmark Results ---")
        print(f"Total time (including spawn & init): {(end_time - start_time)*1000:.2f} ms")
        print(f"Symbol request time: {(symbol_end - symbol_start)*1000:.2f} ms")
        print(f"Total symbols extracted: {total_symbols}")
        print("\n--- Symbol Tree (First 2 Levels) ---")
        
        # Only print first two levels to avoid overwhelming output
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
    finally:
        print("\nStopping LSP client...")
        client.stop()

if __name__ == "__main__":
    main()
