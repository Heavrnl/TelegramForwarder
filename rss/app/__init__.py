"""
TG Forwarder RSS Application
"""

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from .routes.auth import router as auth_router

app = FastAPI(title="TG Forwarder RSS")


# Register routes
app.include_router(auth_router)

# Template configuration
templates = Jinja2Templates(directory="rss/app/templates")
