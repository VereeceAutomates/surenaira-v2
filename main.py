"""
SureNaira — Main Entry Point
Run with:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/surenaira.log"),
    ],
)

from api.server import app  # noqa: F401 — uvicorn targets this

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
