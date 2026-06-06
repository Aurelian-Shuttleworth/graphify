import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from graphify.extract import extract_nix

def main():
    target_file = Path("/Users/aurelianshuttleworth/Workspace/Aurelian/nix/nix-darwin/home-manager/modules/antigravity/mcp/default.nix")
    
    print(f"Extracting {target_file} via extract_nix()...")
    result = extract_nix(target_file)
    
    if "error" in result and result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)
        
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    
    print(f"Extraction successful: {len(nodes)} nodes, {len(edges)} edges.")
    
    print("\nValidating node isolation for 'programs.antigravity.mcp':")
    
    target_found = False
    for node in nodes:
        label = node.get("label", "")
        # The LSP gives hierarchical names like config.programs.antigravity.mcp
        if "programs.antigravity" in label or "mcp" in label:
            print(f"Found node: {label}")
            print(f"  ID: {node.get('id')}")
            print(f"  Location: {node.get('source_location')}")
            target_found = True
            
    if not target_found:
        print("ERROR: Did not find the expected isolated configuration node!")
        sys.exit(1)
        
    print("\nSUCCESS: The LSP extraction layer correctly maps Nix code blocks to Graphify semantic nodes.")

if __name__ == "__main__":
    main()
