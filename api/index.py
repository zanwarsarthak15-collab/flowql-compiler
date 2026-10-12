"""
Vercel Serverless Function Entrypoint for FastAPI.
Exposes the FlowQL compiler and AI assistant API endpoints.
"""
import sys
from pathlib import Path

# Add project root to sys.path so modules like dslc and server can be imported
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server import app
