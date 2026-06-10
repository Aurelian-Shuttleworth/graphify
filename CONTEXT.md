# Graphify

A knowledge graph builder that extracts, clusters, and queries code structure.

## Language

**AST extraction**:
Static analysis of source code via tree-sitter parsers to produce nodes and edges.
No LLM or network calls required.
_Avoid_: code parsing, syntax analysis

**Semantic extraction**:
LLM-powered analysis of documents, papers, and images to produce nodes and edges.
Requires an API key for a supported backend.
_Avoid_: AI extraction, doc extraction

**LSP enrichment**:
Optional post-pass that uses a Language Server (e.g., `nil` for Nix) to add
hierarchical labels and source snippets to AST-extracted nodes.
_Avoid_: LSP extraction, language server parsing

**Update** (`graphify update`):
AST-only rebuild of the graph. No LLM cost. Runs `_rebuild_code` internally.
_Avoid_: refresh, sync

**Extract** (`graphify extract`):
Full pipeline: AST extraction + semantic extraction + clustering.
Requires an LLM backend.
_Avoid_: build, rebuild (ambiguous)

**God node**:
A graph node with disproportionately many connections (high degree centrality).
Changes to god nodes have large blast radius.
_Avoid_: hub, central node

**Community**:
A cluster of densely connected nodes identified by Leiden algorithm.
Algorithmic, not semantic — treat as suggestions for bounded contexts.
_Avoid_: module, group, cluster (overloaded)

**Blast radius**:
The set of nodes and communities potentially affected by changing a specific node.
Proportional to degree and cross-community edge count.
_Avoid_: impact, scope
