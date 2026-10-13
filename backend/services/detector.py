"""
Loads and caches the Ultralytics YOLO model.

The model is expensive to load (reads weights from disk onto CPU/GPU),
so we keep a single cached instance and only reload it when the
requested weights file actually changes (e.g. the user picks a
different model on the Settings page).
"""

import os
import threading

from backend.utils.config import MODELS_DIR

_lock = threading.Lock()
_cache = {"model": None, "model_name": None}


class ModelNotFoundError(Exception):
    pass


def get_model(model_name: str):
    """Return a cached YOLO model instance for the given weights file."""
    from ultralytics import YOLO  # imported lazily so the API can start
    # up and report a friendly error even if ultralytics/torch are
    # missing or still installing.

    model_path = os.path.join(MODELS_DIR, model_name)
    if not os.path.exists(model_path):
        raise ModelNotFoundError(
            f"YOLO weights '{model_name}' were not found in {MODELS_DIR}. "
            f"See the README for how to download a model."
        )

    with _lock:
        if _cache["model"] is None or _cache["model_name"] != model_name:
            _cache["model"] = YOLO(model_path)
            _cache["model_name"] = model_name
        return _cache["model"]


def class_name_for_id(model, class_id: int) -> str:
    """Look up a COCO class name from a model's names mapping."""
    return model.names.get(class_id, str(class_id))
