import subprocess
import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

class LspClient:
    """A lightweight, zero-dependency JSON-RPC client for interacting with Language Servers via stdio."""
    
    def __init__(self, binary="nil"):
        self.binary = binary
        self.process = None
        self._request_id = 1
        self._responses = {}
        self._read_thread = None
        self._running = False
        
    def start(self):
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
        while self._running and self.process.poll() is None:
            # Read headers
            content_length = None
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.decode('utf-8').strip()
                if line == "":
                    # End of headers
                    break
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())
            
            if content_length is None:
                continue
                
            # Read body
            body = self.process.stdout.read(content_length)
            if not body:
                continue
                
            try:
                response = json.loads(body.decode('utf-8'))
                if "id" in response:
                    self._responses[response["id"]] = response
                elif "method" in response:
                    # Ignore notifications from server for now
                    pass
            except json.JSONDecodeError:
                logger.error("Failed to decode LSP response")
                
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
        
    def stop(self):
        self._running = False
        if self.process:
            try:
                self.request("shutdown", timeout_sec=1.0)
                self.notify("exit")
                self.process.terminate()
            except Exception:
                pass
