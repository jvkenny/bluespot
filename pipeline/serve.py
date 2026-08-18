#!/usr/bin/env python3
"""Static file server with HTTP Range support (stdlib only).

PMTiles archives are fetched by the browser via HTTP Range requests;
`python -m http.server` ignores the Range header and returns the whole file,
which breaks (and would re-download a multi-hundred-MB archive per tile).
This server honors single byte ranges, follows symlinks (viewer/data is a
symlink into the Google Drive bluespot-data folder), and sends CORS headers
so the viewer works from any local origin.

Usage: serve.py [port] [root]      (default: 8666, repo viewer/)
Then open http://localhost:<port>/
"""
import os, re, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found"); return None
        size = os.fstat(f.fileno()).st_size
        if not m or (not m.group(1) and not m.group(2)):
            f.close(); self.send_error(400, "Bad Range"); return None
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:                                   # suffix range: last N bytes
            start = max(size - int(m.group(2)), 0); end = size - 1
        if start >= size:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers(); return None
        end = min(end, size - 1)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        f.seek(start)
        self._range_remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = getattr(self, "_range_remaining", None)
        if n is None:
            return super().copyfile(source, outputfile)
        self._range_remaining = None
        while n > 0:
            buf = source.read(min(65536, n))
            if not buf:
                break
            outputfile.write(buf); n -= len(buf)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8666
    root = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "viewer")
    os.chdir(root)
    print(f"serving {os.getcwd()} on http://localhost:{port}/ (Range enabled)")
    HTTPServer(("127.0.0.1", port), RangeHandler).serve_forever()
