from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from rss.app.routes.auth import router as auth_router
from rss.app.routes.rss import router as rss_router
from rss.app.api.endpoints import feed
import uvicorn
import logging
import sys
import os
from pathlib import Path
from utils.log_config import setup_logging



root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))


# Get logger
logger = logging.getLogger(__name__)

app = FastAPI(title="TG Forwarder RSS")

# Register routes
app.include_router(auth_router)
app.include_router(rss_router)
app.include_router(feed.router)

# Template configuration
templates = Jinja2Templates(directory="rss/app/templates")

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the RSS server"""
    uvicorn.run(app, host=host, port=port)

# Add direct run support
if __name__ == "__main__":
    # Only set up logging when running directly (not when imported)
    setup_logging()
    run_server()
