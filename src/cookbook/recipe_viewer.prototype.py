"""Throwaway recipe UI. Run: python3 src/cookbook/recipe_viewer.prototype.py"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import os


class PrototypeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        prototypes = {
            "/everyday-recipe.prototype": "everyday_recipe.prototype.html",
            "/everyday-recipe-widget.prototype": "everyday_recipe_widget.prototype.html",
        }
        route = self.path.split("?", 1)[0]
        if route in prototypes:
            content = Path(__file__).with_name(prototypes[route]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path.split("?", 1)[0] == "/recipe-compare.prototype":
            content = Path(__file__).with_name("recipe_compare.prototype.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path.split("?", 1)[0] == "/emp.prototype.json":
            fixture = Path(os.environ.get("RECIPE_PROTOTYPE_EMP", str(
                Path.home() / "cookbook-mcp-data/prototypes/recipe-display/emp-recipe.json"
            )))
            if not fixture.exists():
                self.send_error(404, "Private EMP prototype fixture not installed")
                return
            content = fixture.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path.split("?", 1)[0] == "/recipe-v1.prototype":
            content = Path(__file__).with_name("recipe_viewer.v1.prototype.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path.split("?", 1)[0] not in ("/", "/recipe.prototype"):
            self.send_error(404)
            return
        content = Path(__file__).with_suffix(".html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    print("Recipe prototype: http://127.0.0.1:8766/everyday-recipe.prototype?variant=B", flush=True)
    HTTPServer(("127.0.0.1", 8766), PrototypeHandler).serve_forever()
