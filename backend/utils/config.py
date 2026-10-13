"""
Central configuration for the AI Traffic Monitoring System.

Everything a beginner might want to tweak lives in this one file:
which vehicle classes to detect, the default counting line, the
traffic density thresholds, and where files are stored on disk.

User-adjustable values (the ones exposed on the Settings page) are
persisted to data/settings.json so they survive a server restart.
They are layered on top of the DEFAULT_SETTINGS below.
"""

import json
import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# BASE_DIR = the project root (one level up from backend/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "backend", "models")

for _d in (VIDEOS_DIR, OUTPUTS_DIR, DATA_DIR, MODELS_DIR):
    os.makedirs(_d, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "traffic.db")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
VIDEO_REGISTRY_PATH = os.path.join(DATA_DIR, "video_registry.json")

# ---------------------------------------------------------------------------
# Vehicle classes
# ---------------------------------------------------------------------------
# Maps a COCO class name (as reported by the YOLO model) to the
# human-readable label used everywhere in the API and dashboard.
# Add/remove entries here to change which road users are tracked.
VEHICLE_CLASSES = {
    "car": "Car",
    "bus": "Bus",
    "truck": "Truck",
    "motorcycle": "Motorcycle",
    "bicycle": "Bicycle",
}

# Stable, sorted list of the internal class keys, used whenever we need
# a fixed ordering (chart series, DB columns, API responses).
VEHICLE_CLASS_KEYS = list(VEHICLE_CLASSES.keys())

# ---------------------------------------------------------------------------
# Allowed upload types
# ---------------------------------------------------------------------------
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB

# ---------------------------------------------------------------------------
# Default, user-adjustable settings
# ---------------------------------------------------------------------------
# counting_line_position: fraction (0.0-1.0) of the frame height where the
#   horizontal counting line is drawn. A vehicle is counted the moment its
#   center point crosses this line.
# confidence_threshold: minimum YOLO detection confidence to keep a box.
# density_window_seconds: only crossings inside this rolling time window
#   are used to decide the CURRENT traffic density (so density reflects
#   "traffic right now", not the whole video's cumulative total).
# density_low_max / density_medium_max: thresholds (vehicle count within
#   the rolling window) used to classify LOW / MEDIUM / HIGH density.
#   Anything above density_medium_max is HIGH.
# model_name: filename of the .pt weights file inside backend/models/.
# enabled_classes: subset of VEHICLE_CLASS_KEYS actually being detected.
DEFAULT_SETTINGS = {   
    "imgsz": 640,
    "counting_line_position": 0.6,
    "confidence_threshold": 0.35,
    "density_window_seconds": 30,
    "density_low_max": 10,
    "density_medium_max": 25,
    "model_name": "yolov8n.pt",
    "enabled_classes": VEHICLE_CLASS_KEYS,
}

DENSITY_COLORS = {
    "LOW": "#22c55e",
    "MEDIUM": "#f59e0b",
    "HIGH": "#ef4444",
}


def get_settings() -> dict:
    """Load current settings, seeding the file with defaults if missing."""
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r") as f:
            stored = json.load(f)
    except (json.JSONDecodeError, OSError):
        stored = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def save_settings(settings: dict) -> dict:
    """Persist settings to disk, merged on top of current values."""
    current = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            current = {}
    current.update(settings)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(current, f, indent=2)
    return current


def available_models() -> list:
    """List .pt weight files present in backend/models/."""
    if not os.path.isdir(MODELS_DIR):
        return []
    return sorted(f for f in os.listdir(MODELS_DIR) if f.endswith(".pt"))
