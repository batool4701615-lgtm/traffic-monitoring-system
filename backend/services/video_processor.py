"""
Orchestrates the end-to-end pipeline for one video:

    open video -> per frame: detect+track -> count line crossings ->
    update density -> draw annotations -> write output video ->
    publish live progress/counts/JPEG frame for the dashboard to poll

Processing runs on a background thread so the FastAPI event loop stays
responsive to /status, /counts, /stream, etc. while a video (which can
take much longer than real time on a CPU) is being processed.

IMPORTANT: all traffic logic (density window, duplicate heuristic,
count-over-time chart) uses VIDEO time (frame_index / video fps), not
the computer's clock. Otherwise a slow CPU (e.g. 2 FPS on a 24 FPS
video) would make a "30 second window" cover only ~2.5 seconds of
real traffic.
"""

import os
import threading
import time
from datetime import datetime

import cv2

from backend.database import db
from backend.services.counter import LineCounter
from backend.services.density import DensityCalculator
from backend.services.tracker import run_tracking
from backend.utils.config import (
    OUTPUTS_DIR,
    VEHICLE_CLASS_KEYS,
    DENSITY_COLORS,
    get_settings,
)

# ---------------------------------------------------------------------------
# Colors (BGR, since OpenCV draws in BGR) matching the dashboard's palette
# ---------------------------------------------------------------------------
COLOR_BOX = (255, 209, 0)        # electric cyan
COLOR_LINE = (255, 255, 255)
COLOR_TEXT_BG = (38, 20, 10)
COLOR_TEXT = (255, 255, 255)
DENSITY_BGR = {
    "LOW": (86, 201, 34),
    "MEDIUM": (11, 158, 245),
    "HIGH": (68, 68, 239),
}

# How often (in seconds of VIDEO time) a point is added to the
# count-over-time chart.
TIMESERIES_INTERVAL = 2.0


def _format_video_time(seconds: float) -> str:
    """Turn 75.3 seconds into '01:15' for chart labels."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


class ProcessingState:
    """Thread-safe holder for everything the API needs to report live."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.status = "idle"
            self.session_id = None
            self.video_id = None
            self.video_name = None
            self.video_path = None
            self.output_path = None
            self.progress_percent = 0.0
            self.current_frame = 0
            self.total_frames = 0
            self.processing_fps = 0.0
            self.elapsed_seconds = 0.0
            self.error_message = None
            self.counts = {k: 0 for k in VEHICLE_CLASS_KEYS}
            self.counts["total"] = 0
            self.density_level = "LOW"
            self.density_window_count = 0
            self.density_window_seconds = 30
            self.suspected_duplicates = 0
            self.last_frame_jpeg = None
            self.pause_flag = False
            self.stop_flag = False
            self.output_ready = False
            self.timeseries_buffer = []

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "session_id": self.session_id,
                "video_id": self.video_id,
                "video_name": self.video_name,
                "progress_percent": round(self.progress_percent, 1),
                "current_frame": self.current_frame,
                "total_frames": self.total_frames,
                "processing_fps": round(self.processing_fps, 1),
                "elapsed_seconds": round(self.elapsed_seconds, 1),
                "error_message": self.error_message,
                "output_ready": self.output_ready,
            }

    def results_snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "counts": {k: self.counts.get(k, 0) for k in VEHICLE_CLASS_KEYS + ["total"]},
                "density": {
                    "level": self.density_level,
                    "color": DENSITY_COLORS[self.density_level],
                    "vehicles_in_window": self.density_window_count,
                    "window_seconds": self.density_window_seconds,
                },
                "processing_fps": round(self.processing_fps, 1),
                "suspected_duplicates": self.suspected_duplicates,
            }

    def latest_jpeg(self):
        with self._lock:
            return self.last_frame_jpeg

    def timeseries_snapshot(self) -> list:
        with self._lock:
            return list(self.timeseries_buffer)


STATE = ProcessingState()


def _draw_hud(frame, counter: LineCounter, density_level: str, line_y: int,
              width: int, fps: float, video_name: str):
    h, w = frame.shape[:2]
    cv2.line(frame, (0, line_y), (width, line_y), COLOR_LINE, 2)
    cv2.putText(frame, "COUNTING LINE", (10, line_y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_LINE, 1, cv2.LINE_AA)

    # Top overlay bar
    cv2.rectangle(frame, (0, 0), (w, 70), COLOR_TEXT_BG, -1)
    cv2.putText(frame, "LIVE", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 140), 2, cv2.LINE_AA)
    cv2.putText(frame, f"FPS: {fps:.1f}", (16, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)
    cv2.putText(frame, f"CAM: {video_name[:24]}", (160, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)
    cv2.putText(frame, "DETECTION: ACTIVE", (160, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 140), 1, cv2.LINE_AA)
    cv2.putText(frame, f"TOTAL: {counter.counts['total']}", (w - 260, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_TEXT, 2, cv2.LINE_AA)
    cv2.putText(frame, f"DENSITY: {density_level}", (w - 260, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, DENSITY_BGR[density_level], 2,
                cv2.LINE_AA)


def _draw_detection(frame, det):
    x1, y1, x2, y2 = [int(v) for v in det.box]
    cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_BOX, 2)
    label = f"{det.label} #{det.track_id} {det.confidence:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), COLOR_BOX, -1)
    cv2.putText(frame, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (10, 10, 10), 1, cv2.LINE_AA)


def start_processing(video_id: str, video_path: str, video_name: str,
                      overrides: dict):
    if STATE.status == "processing":
        raise RuntimeError("A video is already being processed. Stop it first.")

    settings = get_settings()
    settings.update({k: v for k, v in overrides.items() if v is not None})

    STATE.reset()
    with STATE._lock:
        STATE.status = "processing"
        STATE.video_id = video_id
        STATE.video_name = video_name
        STATE.video_path = video_path
        STATE.density_window_seconds = settings["density_window_seconds"]

    thread = threading.Thread(
        target=_process_video, args=(video_path, video_name, settings), daemon=True
    )
    thread.start()


def control(action: str):
    if action == "pause":
        with STATE._lock:
            if STATE.status == "processing":
                STATE.pause_flag = True
                STATE.status = "paused"
    elif action == "resume":
        with STATE._lock:
            if STATE.status == "paused":
                STATE.pause_flag = False
                STATE.status = "processing"
    elif action == "stop":
        with STATE._lock:
            STATE.stop_flag = True
    elif action == "reset":
        if STATE.status == "processing":
            raise RuntimeError("Stop processing before resetting.")
        STATE.reset()
    else:
        raise ValueError(f"Unknown action '{action}'")


def _process_video(video_path: str, video_name: str, settings: dict):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        with STATE._lock:
            STATE.status = "error"
            STATE.error_message = "Could not open the video file. It may be corrupt or an unsupported codec."
        return

    fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    with STATE._lock:
        STATE.total_frames = total_frames

    line_y = int(height * settings["counting_line_position"])
    counter = LineCounter(line_y=line_y)
    density_calc = DensityCalculator(
        window_seconds=settings["density_window_seconds"],
        low_max=settings["density_low_max"],
        medium_max=settings["density_medium_max"],
    )

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    output_filename = f"output_{int(time.time())}.mp4"
    output_path = os.path.join(OUTPUTS_DIR, output_filename)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps_in, (width, height))

    start_time = time.time()          # wall clock: only used to measure processing FPS
    frame_index = 0
    video_time = 0.0                  # seconds into the VIDEO (drives all traffic logic)
    last_timeseries_video_time = -TIMESERIES_INTERVAL

    try:
        while True:
            with STATE._lock:
                if STATE.stop_flag:
                    break
                paused = STATE.pause_flag

            if paused:
                time.sleep(0.2)
                continue

            ok, frame = cap.read()
            if not ok:
                break
            frame_index += 1
            video_time = frame_index / fps_in

            try:
                detections = run_tracking(
                    frame,
                    model_name=settings["model_name"],
                    confidence_threshold=settings["confidence_threshold"],
                    enabled_classes=settings["enabled_classes"],
                    imgsz=settings.get("imgsz", 1280),
                )
            except Exception as exc:  # model missing, bad weights, etc.
                with STATE._lock:
                    STATE.status = "error"
                    STATE.error_message = f"Detection failed: {exc}"
                break

            for det in detections:
                event = counter.update(det.track_id, det.class_name, det.center, video_time)
                if event is not None:
                    density_calc.add_event(video_time)
                _draw_detection(frame, det)

            density_result = density_calc.current(video_time)
            elapsed = time.time() - start_time
            processing_fps = frame_index / elapsed if elapsed > 0 else 0.0

            _draw_hud(frame, counter, density_result.level, line_y, width,
                      processing_fps, video_name)
            writer.write(frame)

            ok_jpeg, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            jpeg_bytes = buf.tobytes() if ok_jpeg else None

            with STATE._lock:
                STATE.current_frame = frame_index
                STATE.progress_percent = (
                    (frame_index / total_frames * 100.0) if total_frames else 0.0
                )
                STATE.processing_fps = processing_fps
                STATE.elapsed_seconds = elapsed
                STATE.counts = dict(counter.counts)
                STATE.density_level = density_result.level
                STATE.density_window_count = density_result.vehicles_in_window
                STATE.suspected_duplicates = counter.suspected_duplicates
                STATE.last_frame_jpeg = jpeg_bytes

            # Count-over-time chart: one point every TIMESERIES_INTERVAL
            # seconds of VIDEO time, labeled mm:ss into the video. A session
            # row (and its DB rows) is only created once processing finishes,
            # so while running we buffer points in memory (GET /timeseries).
            if video_time - last_timeseries_video_time >= TIMESERIES_INTERVAL:
                with STATE._lock:
                    STATE.timeseries_buffer.append({
                        "timestamp": _format_video_time(video_time),
                        "total": counter.counts["total"],
                    })
                last_timeseries_video_time = video_time

    finally:
        cap.release()
        writer.release()

    with STATE._lock:
        stopped_early = STATE.stop_flag
        errored = STATE.status == "error"

    if errored:
        return

    density_final = density_calc.current(video_time)

    record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "video_name": video_name,
        "total": counter.counts["total"],
        "car": counter.counts.get("car", 0),
        "bus": counter.counts.get("bus", 0),
        "truck": counter.counts.get("truck", 0),
        "motorcycle": counter.counts.get("motorcycle", 0),
        "bicycle": counter.counts.get("bicycle", 0),
        "density": density_final.level,
        "fps": round(STATE.processing_fps, 2),
        # Length of video analyzed (not processing time), so that
        # "average vehicles / minute" in Analytics is meaningful.
        "duration_seconds": round(video_time, 2),
        "suspected_duplicates": counter.suspected_duplicates,
        "output_video": output_filename,
    }
    session_id = db.save_session(record)
    points = STATE.timeseries_snapshot()
    for point in points:
        db.save_timeseries_point(session_id, point["timestamp"], point["total"])
    if not points:
        db.save_timeseries_point(session_id, _format_video_time(video_time),
                                 counter.counts["total"])

    with STATE._lock:
        STATE.session_id = session_id
        STATE.output_path = output_path
        STATE.output_ready = True
        STATE.status = "stopped" if stopped_early else "completed"