"""
Entry point for the AI Traffic Monitoring backend.

Run with:
    uvicorn backend.main:app --reload --port 8000

(run this command from the project root, so the `backend` package
resolves correctly)
"""

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.database.db import init_db
from backend.utils.config import BASE_DIR

app = FastAPI(
    title="AI Traffic Monitoring System",
    description="Detects, tracks, counts and analyzes vehicles in traffic video using YOLO.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak a raw Python traceback to the frontend -- always return
    # a friendly, structured error message instead.
    return JSONResponse(
        status_code=500,
        content={"detail": f"Something went wrong on the server: {exc}"},
    )


app.include_router(router, prefix="/api")

# Serve the static frontend (index.html, style.css, app.js) directly from
# FastAPI so the whole project can be run with a single command. The
# frontend can also be served separately (see README) if you prefer.
frontend_dir = os.path.join(BASE_DIR, "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
