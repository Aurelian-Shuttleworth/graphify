import subprocess
import json
import logging
import shutil
import threading
import time

logger = logging.getLogger(__name__)

class LspClient:
    """A lightweight, zero-dependency JSON-RPC client for interacting with Language Servers via stdio.
    
    Supports context manager usage for shared sessions::

        with LspClient("nil") as client:
            client.initialize(root_uri)
            for path in nix_files:
                client.did_open(uri, text)
                symbols = client.document_symbol(uri)
                client.did_close(uri)
    """
    
    def __init__(self, binary="nil"):
        self.binary = binary
        self.process = None
        self._request_id = 1
        self._responses = {}
        self._read_thread = None
        self._running = False
        self.resync_count = 0
        self._decode_errors = 0

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        
    def start(self):
        if not shutil.which(self.binary):
            raise RuntimeError(f"LSP binary '{self.binary}' not found on PATH.")
        try:
            self.process = subprocess.Popen(
                [self.binary],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
            self._running = True
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
        except FileNotFoundError:
            raise RuntimeError(f"LSP binary '{self.binary}' not found on PATH.")
            
    def _read_loop(self):
        """Read LSP JSON-RPC messages from stdout with defensive re-sync.

        Uses a rolling buffer instead of trusting ``Content-Length`` byte
        counts exactly.  If a message fails to decode, the reader scans
        forward for the next ``Content-Length:`` header to re-align the
        stream.  This handles CR/LF mismatches and interleaved server
        diagnostics that would otherwise corrupt all subsequent reads.
        """
        buf = b""
        HEADER_RE = b"Content-Length:"
        stdout = self.process.stdout

        while self._running and self.process.poll() is None:
            # Non-blocking buffered read — read1 returns whatever is
            # available (up to 8 KiB) without blocking for the full
            # amount.  Falls back to read(1) for unbuffered streams.
            try:
                chunk = stdout.read1(8192)  # type: ignore[attr-defined]
            except AttributeError:
                chunk = stdout.read(1)
            if not chunk:
                break
            buf += chunk

            # Process all complete messages in the buffer.
            while HEADER_RE in buf:
                header_start = buf.index(HEADER_RE)

                # ── Re-sync: discard bytes before the header ──
                if header_start > 0:
                    discarded = buf[:header_start]
                    buf = buf[header_start:]
                    self.resync_count += 1
                    logger.debug(
                        "LSP stream resync: discarded %d bytes, "
                        "fragment: %.200s",
                        len(discarded),
                        discarded.decode("utf-8", errors="replace"),
                    )

                # ── Find the header/body separator ──
                sep = b"\r\n\r\n"
                sep_len = 4
                header_end = buf.find(sep)
                if header_end == -1:
                    sep = b"\n\n"  # fallback for LF-only servers
                    sep_len = 2
                    header_end = buf.find(sep)
                if header_end == -1:
                    break  # incomplete header — wait for more data

                # ── Parse Content-Length from the header block ──
                header_block = buf[:header_end].decode("utf-8", errors="replace")
                content_length = None
                for line in header_block.split("\n"):
                    line = line.strip()
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except (ValueError, IndexError):
                            pass

                if content_length is None:
                    # Malformed header block — skip past the separator.
                    buf = buf[header_end + sep_len:]
                    continue

                body_start = header_end + sep_len
                body_end = body_start + content_length

                if len(buf) < body_end:
                    break  # incomplete body — wait for more data

                body = buf[body_start:body_end]
                buf = buf[body_end:]

                try:
                    response = json.loads(body.decode("utf-8"))
                    if "id" in response:
                        self._responses[response["id"]] = response
                    elif "method" in response:
                        # Silently ignore server notifications.
                        pass
                except json.JSONDecodeError:
                    self._decode_errors += 1
                    logger.debug(
                        "LSP stream: skipped non-JSON body (%d bytes), resync will recover",
                        len(body),
                    )
                
    def _send(self, message):
        body = json.dumps(message).encode('utf-8')
        header = f"Content-Length: {len(body)}\r\n\r\n".encode('utf-8')
        self.process.stdin.write(header + body)
        self.process.stdin.flush()
        
    def request(self, method, params=None, timeout_sec=5.0):
        req_id = self._request_id
        self._request_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        self._send(message)
        
        # Blocking wait for response
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            if req_id in self._responses:
                return self._responses.pop(req_id)
            time.sleep(0.01)
            
        raise TimeoutError(f"LSP request {method} timed out after {timeout_sec}s")
        
    def notify(self, method, params=None):
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        self._send(message)
        
    def initialize(self, root_uri):
        res = self.request("initialize", {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True
                    }
                }
            }
        })
        self.notify("initialized", {})
        return res
        
    def did_open(self, uri, text, language_id="nix"):
        self.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": text
            }
        })
        
    def document_symbol(self, uri):
        res = self.request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri}
        })
        return res.get("result", [])

    def did_close(self, uri):
        """Notify the server that a document was closed (frees server-side resources)."""
        self.notify("textDocument/didClose", {
            "textDocument": {"uri": uri}
        })

    def references(self, uri, line, character, include_declaration=False):
        """Find all references to the symbol at the given position.

        Returns a list of ``Location`` objects or ``[]`` on timeout/error.
        """
        try:
            res = self.request("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            })
            return res.get("result") or []
        except TimeoutError:
            return []

    def definition(self, uri, line, character):
        """Go to definition of the symbol at the given position.

        Returns a flat list of ``{"uri": str, "range": {...}}`` dicts,
        normalising both ``Location`` and ``LocationLink`` responses.
        """
        try:
            res = self.request("textDocument/definition", {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            })
            result = res.get("result")
            if result is None:
                return []
            # Normalise: could be Location, Location[], or LocationLink[]
            if isinstance(result, dict):
                result = [result]
            locations = []
            for item in result:
                if "targetUri" in item:  # LocationLink
                    locations.append({
                        "uri": item["targetUri"],
                        "range": item.get("targetRange", item.get("targetSelectionRange", {})),
                    })
                elif "uri" in item:  # Location
                    locations.append({"uri": item["uri"], "range": item.get("range", {})})
            return locations
        except TimeoutError:
            return []
        
    def stop(self):
        self._running = False
        if self.process:
            try:
                self.request("shutdown", timeout_sec=1.0)
                self.notify("exit")
                self.process.terminate()
            except Exception:
                pass
