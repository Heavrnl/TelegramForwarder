from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
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

logger = logging.getLogger(__name__)

app = FastAPI(title="TG Forwarder RSS")

# Allow Telegram Mini App iframe and direct browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://web.telegram.org",
        "https://telegram.org",
        "null",  # Telegram WebApp sends Origin: null in some clients
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(auth_router)
app.include_router(rss_router)
app.include_router(feed.router)

# Template config
templates = Jinja2Templates(directory="rss/app/templates")

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the RSS server"""
    uvicorn.run(app, host=host, port=port)

# Support direct execution
if __name__ == "__main__":
    # Only set up logging when run directly (not when imported)
    setup_logging()
    run_server() 