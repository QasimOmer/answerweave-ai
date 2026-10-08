import sys
import os

# Ensure the root project directory is in the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Request
from app.main import app

@app.get("/api/index.py")
def debug_route(request: Request):
    return {
        "url_path": request.url.path,
        "headers": dict(request.headers),
        "raw_scope_path": request.scope.get("path")
    }
