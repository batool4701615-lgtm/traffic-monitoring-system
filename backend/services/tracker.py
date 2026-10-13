"""
Runs detection + multi-object tracking on a single video frame.

We rely on Ultralytics' built-in `model.track(...)`, which pairs a YOLO
detector with the ByteTrack algorithm and hands back a stable track ID
for every object across frames. That ID is what lets counter.py know
"this is the same vehicle I saw two frames ago" instead of re-counting
it.
"""

from dataclasses import dataclass
from typing import List

from backend.services.detector import get_model, class_name_for_id
from backend.utils.config import VEHICLE_CLASSES


@dataclass
class Detection:
    track_id: int
    class_name: str        # internal key, e.g. "car"
    label: str              # display label, e.g. "Car"
    confidence: float
    box: tuple               # (x1, y1, x2, y2)
    center: tuple             # (cx, cy)


def run_tracking(frame, model_name: str, confidence_threshold: float,
                  enabled_classes: List[str], imgsz: int = 1280) -> List[Detection]:
    """Run one frame through YOLO + ByteTrack and return vehicle detections."""
    model = get_model(model_name)

    results = model.track(
        frame,
        persist=True,
        conf=confidence_threshold,
        imgsz=imgsz,
        tracker="bytetrack.yaml",
        verbose=False,
    )

    detections: List[Detection] = []
    if not results:
        return detections

    result = results[0]
    boxes = result.boxes
    if boxes is None or boxes.id is None:
        return detections

    ids = boxes.id.int().tolist()
    classes = boxes.cls.int().tolist()
    confs = boxes.conf.tolist()
    xyxy = boxes.xyxy.tolist()

    for track_id, cls_id, conf, box in zip(ids, classes, confs, xyxy):
        class_name = class_name_for_id(model, cls_id)
        if class_name not in VEHICLE_CLASSES:
            continue
        if class_name not in enabled_classes:
            continue
        x1, y1, x2, y2 = box
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        detections.append(
            Detection(
                track_id=track_id,
                class_name=class_name,
                label=VEHICLE_CLASSES[class_name],
                confidence=float(conf),
                box=(x1, y1, x2, y2),
                center=center,
            )
        )
    return detections
