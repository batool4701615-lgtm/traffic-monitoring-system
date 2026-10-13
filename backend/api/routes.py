"""All HTTP endpoints for the AI Traffic Monitoring System."""

import json
import os
import time
import uuid

import cv2
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse

from backend.database import db
from backend.services import video_processor
from backend.services.video_processor import STATE
from backend.utils import config
from backend.utils.schemas import (
    ControlRequest,
    SessionUpdate,
    SettingsUpdate,
    StartProcessingRequest,
)

router = APIRouter()


def _load_registry() -> dict:
    if not os.path.exists(config.VIDEO_REGISTRY_PATH):
        return {}
    try:
        with open(config.VIDEO_REGISTRY_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry: dict):
    with open(config.VIDEO_REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in config.ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Allowed: "
            f"{', '.join(sorted(config.ALLOWED_VIDEO_EXTENSIONS))}",
        )

    video_id = uuid.uuid4().hex[:12]
    safe_name = f"{video_id}{ext}"
    dest_path = os.path.join(config.VIDEOS_DIR, safe_name)

    size = 0
    try:
        with open(dest_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(400, "Video exceeds the 500 MB upload limit.")
                out.write(chunk)
    except HTTPException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    except OSError as exc:
        raise HTTPException(500, f"Could not save the uploaded file: {exc}")

    cap = cv2.VideoCapture(dest_path)
    if not cap.isOpened():
        os.remove(dest_path)
        raise HTTPException(
            400, "The video could not be opened. It may be corrupt or use an "
            "unsupported codec. Try re-exporting it as H.264 MP4."
        )
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = (total_frames / fps) if fps else 0.0
    cap.release()

    registry = _load_registry()
    registry[video_id] = {
        "path": dest_path,
        "filename": file.filename,
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "total_frames": total_frames,
    }
    _save_registry(registry)

    return {
        "video_id": video_id,
        "filename": file.filename,
        "duration_seconds": round(duration, 2),
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "total_frames": total_frames,
    }


# ---------------------------------------------------------------------------
# Processing control
# ---------------------------------------------------------------------------
@router.post("/start-processing")
def start_processing(payload: StartProcessingRequest):
    registry = _load_registry()
    entry = registry.get(payload.video_id)
    if entry is None:
        raise HTTPException(404, "Unknown video_id. Upload a video first.")
    if not os.path.exists(entry["path"]):
        raise HTTPException(404, "The uploaded video file is missing on disk.")

    overrides = {
        "counting_line_position": payload.counting_line_position,
        "confidence_threshold": payload.confidence_threshold,
        "model_name": payload.model_name,
    }
    try:
        video_processor.start_processing(
            video_id=payload.video_id,
            video_path=entry["path"],
            video_name=entry["filename"],
            overrides=overrides,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return STATE.snapshot()


@router.post("/control")
def control(payload: ControlRequest):
    try:
        video_processor.control(payload.action)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return STATE.snapshot()


@router.get("/status")
def get_status():
    return STATE.snapshot()


@router.get("/results")
def get_results():
    return STATE.results_snapshot()


@router.get("/counts")
def get_counts():
    return STATE.results_snapshot()["counts"]


@router.get("/density")
def get_density():
    return STATE.results_snapshot()["density"]


@router.get("/timeseries")
def get_timeseries():
    """Live count-over-time points for the currently processing/most
    recently processed video (in-memory, refreshed every ~2s)."""
    return STATE.timeseries_snapshot()


@router.get("/stream")
def stream():
    """MJPEG live feed of the annotated frames as they're produced."""

    def generator():
        boundary = b"--frame\r\n"
        while True:
            frame = STATE.latest_jpeg()
            if frame is not None:
                yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.08)

    return StreamingResponse(
        generator(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ---------------------------------------------------------------------------
# Video files
# ---------------------------------------------------------------------------
@router.get("/videos/{video_id}")
def get_source_video(video_id: str):
    registry = _load_registry()
    entry = registry.get(video_id)
    if entry is None or not os.path.exists(entry["path"]):
        raise HTTPException(404, "Video not found.")
    return FileResponse(entry["path"], media_type="video/mp4")


@router.get("/outputs/{filename}")
def get_output_video(filename: str):
    safe_name = os.path.basename(filename)
    path = os.path.join(config.OUTPUTS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(404, "Output video not found.")
    return FileResponse(path, media_type="video/mp4")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@router.get("/history")
def get_history():
    return db.get_history()


@router.get("/history/{session_id}")
def get_history_detail(session_id: int):
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found.")
    timeseries = db.get_timeseries(session_id)
    return {"session": session, "timeseries": timeseries}


@router.patch("/history/{session_id}")
def patch_history(session_id: int, payload: SessionUpdate):
    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Session not found.")
    fields = {k: v for k, v in payload.dict().items() if v is not None}
    db.update_session(session_id, fields)
    return db.get_session(session_id)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/settings")
def get_settings():
    return config.get_settings()


@router.post("/settings")
def update_settings(payload: SettingsUpdate):
    fields = {k: v for k, v in payload.dict().items() if v is not None}
    return config.save_settings(fields)


@router.get("/models")
def list_models():
    return {"models": config.available_models(), "vehicle_classes": config.VEHICLE_CLASS_KEYS}
