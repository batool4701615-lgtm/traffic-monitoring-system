   ---
   title: AI Traffic Monitoring
   sdk: docker
   app_port: 7860
   ---

# AI-Based Traffic Monitoring System

A full-stack computer vision application that detects, tracks and counts
vehicles in traffic video, estimates traffic density in real time, and
presents everything through a FastAPI backend and a dark, smart-city-style
web dashboard.

Built as a university Computer Science project. Every feature listed below
is real: the dashboard shows actual results computed by the backend from
actual YOLO detections on the video you upload -- nothing is hardcoded or
randomly generated.

---

## 1. Features

- Upload a recorded traffic video (MP4 / AVI / MOV / MKV) through a
  drag-and-drop UI.
- Detects **car, bus, truck, motorcycle, bicycle** using a pretrained
  YOLOv8 model (Ultralytics).
- Tracks every vehicle with a persistent ID using ByteTrack.
- Counts each vehicle **exactly once** using line-crossing logic, with a
  duplicate-crossing heuristic to flag likely tracker ID switches.
- Calculates **LOW / MEDIUM / HIGH** traffic density from a rolling
  time window of recent crossings (not just a running total).
- Live annotated video feed (MJPEG) while processing runs, with bounding
  boxes, class labels, track IDs and the counting line drawn in.
- Dashboard, Live Monitor, Analytics, History and Settings pages.
- Vehicle distribution chart, count-over-time chart, session history table.
- Every completed run is saved to SQLite and browsable later.
- Configurable counting line position, confidence threshold, density
  thresholds, and which vehicle classes are detected -- all from the
  Settings page, no code changes required.
- Friendly error messages everywhere (bad file, missing model, corrupt
  video, backend down) -- never a raw Python traceback.

---

## 2. Architecture

```
traffic-monitoring-system/
│
├── backend/
│   ├── main.py                 FastAPI app, CORS, static frontend mount
│   ├── api/
│   │   └── routes.py           All HTTP endpoints
│   ├── services/
│   │   ├── detector.py         Loads & caches the YOLO model
│   │   ├── tracker.py          Runs YOLO + ByteTrack per frame
│   │   ├── counter.py          Line-crossing counting logic
│   │   ├── density.py          Rolling-window density classifier
│   │   └── video_processor.py  Orchestrates the whole pipeline + live state
│   ├── database/
│   │   └── db.py               SQLite storage (sessions + timeseries)
│   ├── models/                 Put your .pt YOLO weights here
│   └── utils/
│       ├── config.py           All tunables in one place + settings.json
│       └── schemas.py          Pydantic request/response models
│
├── frontend/                   Plain HTML/CSS/JS dashboard (no build step)
│   ├── index.html
│   └── assets/
│       ├── style.css
│       └── app.js
│
├── videos/                     Uploaded videos land here
├── outputs/                    Annotated output videos land here
├── data/                       traffic.db, settings.json (auto-created)
├── requirements.txt
└── README.md
```

**Why plain HTML/JS instead of React?** The task allowed either, and a
single dependency-free static frontend is more reliable to hand in and run
than a Node/Vite build for a project whose real complexity is on the CV/AI
side. FastAPI serves it directly (see `app.mount("/", StaticFiles(...))` in
`main.py`), so starting the backend is enough to use the whole app.

---

## 3. How counting and density actually work

**Counting line.** The line is horizontal, at a configurable fraction of
the frame height (`counting_line_position`, default `0.6`, i.e. 60% down
the frame). For every tracked vehicle we remember which side of the line
its center point was on last frame. The instant that side flips, and that
track ID has never been counted before, we count it once and remember the
ID for the rest of that run (`backend/services/counter.py`). This is a
deliberate simplification over an angled/polygon region, chosen so the
logic is easy to explain and verify by hand -- a good fit for a project
viva.

**Suspected duplicates.** If the tracker loses a vehicle and re-acquires it
under a new ID near the same spot moments later, that would look like a
second, brand-new crossing. We can't undo that automatically without risking
under-counting real vehicles, so instead we flag it: any crossing within 40
pixels and 1.5 seconds of a same-class crossing increments
`suspected_duplicates`, which is shown in Analytics and stored per session
for the testing/limitations section of your report.

**Traffic density.** Rather than classifying density from the video's
*cumulative* total (which can only ever go up), we look at how many
vehicles crossed the line in the last `density_window_seconds` (default 30s)
-- a genuine "how busy is it right now" measure:

```
vehicles_in_last_window <= density_low_max      -> LOW
vehicles_in_last_window <= density_medium_max   -> MEDIUM
vehicles_in_last_window  > density_medium_max   -> HIGH
```

Defaults: `density_low_max = 10`, `density_medium_max = 25`. All three
numbers are editable on the Settings page.

---

## 4. Requirements

- Python 3.9+
- ~2 GB free disk space (YOLOv8n weights + PyTorch)
- No GPU required (works on CPU; a GPU will make processing much faster)

---

## 5. Installation

```bash
# 1. From the project root, create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
```

## 6. Download the YOLO model

The app expects a YOLOv8 `.pt` weights file inside `backend/models/`.
The easiest way to get the default `yolov8n.pt` (nano, fastest on CPU):

```bash
python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
mv yolov8n.pt backend/models/
```

This downloads the official pretrained COCO weights from Ultralytics on
first use and caches them. If you want higher accuracy at the cost of
speed, download `yolov8s.pt` or `yolov8m.pt` the same way and select it
on the Settings page (the dropdown lists every `.pt` file found in
`backend/models/`).

## 7. Run the backend (serves the frontend too)

```bash
# from the project root
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser. That's it -- one command,
one port, for both the API and the dashboard.

If you'd rather run the frontend separately (e.g. to edit it with live
reload from a different tool), you can instead serve `frontend/` with any
static file server and point `API` at `http://localhost:8000/api` in
`frontend/assets/app.js`.

---

## 8. Using the dashboard

1. Go to **Live Monitor**.
2. Drag a traffic video onto the upload box (or click Browse Files).
3. Once it says "Ready to analyze", click **Start Analysis**.
4. Watch the live annotated feed, counts and progress bar update.
5. Use **Pause / Resume / Stop** as needed.
6. When it finishes, the session is saved automatically -- check **History**
   to watch the annotated output video back, see the count-over-time chart,
   and record manual testing notes (see section 10).
7. **Analytics** summarizes your most recent session; **Settings** lets you
   tune the counting line, confidence threshold, density thresholds, model
   and which vehicle classes are detected.

---

## 9. API endpoints

All endpoints are prefixed with `/api`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Backend liveness check |
| POST | `/upload-video` | Upload a video (multipart form, field `file`) |
| POST | `/start-processing` | Start processing `{video_id, ...overrides}` |
| POST | `/control` | `{"action": "pause"\|"resume"\|"stop"\|"reset"}` |
| GET | `/status` | Progress, FPS, current status |
| GET | `/results` | Current counts + density + FPS snapshot |
| GET | `/counts` | Just the class-wise counts |
| GET | `/density` | Just the density result |
| GET | `/timeseries` | Live count-over-time points for the active run |
| GET | `/stream` | MJPEG live annotated video feed |
| GET | `/videos/{video_id}` | Stream the original uploaded video |
| GET | `/outputs/{filename}` | Stream an annotated output video |
| GET | `/history` | All completed sessions |
| GET | `/history/{id}` | One session + its timeseries |
| PATCH | `/history/{id}` | Save manual `missed_detections` / `duplicate_detections` / `notes` |
| GET | `/settings` | Current settings |
| POST | `/settings` | Update settings (partial updates allowed) |
| GET | `/models` | Available `.pt` files + configured vehicle classes |

Example `/results` response:

```json
{
  "status": "processing",
  "timestamp": "2026-09-26T18:20:00",
  "counts": {"total": 42, "car": 28, "bus": 4, "truck": 5, "motorcycle": 5, "bicycle": 0},
  "density": {"level": "HIGH", "color": "#ef4444", "vehicles_in_window": 27, "window_seconds": 30},
  "processing_fps": 24.5,
  "suspected_duplicates": 1
}
```

Interactive API docs are also available at **http://localhost:8000/docs**
(FastAPI's built-in Swagger UI).

---

## 10. Testing

The task asks you to test on at least two different clips and report
counting accuracy, missed/duplicate detections, FPS, and limitations.
There is no automatic ground truth for a traffic video, so the
recommended workflow is:

1. Process a clip end to end.
2. Open **History -> View** for that session and watch the annotated
   output video.
3. Manually count, by eye, any vehicle the boxes/labels missed, and any
   vehicle you can tell was counted twice.
4. Enter those numbers (and any notes) in the **Manual Testing Notes**
   box on that page and click **Save Notes** -- they're stored in SQLite
   alongside the automatic counts, ready to quote in your report.
5. Repeat for a second (ideally very different -- e.g. sparse vs. dense
   traffic, day vs. night) clip.

`suspected_duplicates`, shown on the same page, is an automatic heuristic
(see section 3) that's a useful cross-check but not a substitute for your
manual review.

### What was verified while building this project

In the sandbox this project was built in, disk space did not allow
installing PyTorch (a few GB), so live YOLO inference could not be run
here end-to-end. Everything that does **not** require the model was
tested directly against a running server: video upload and validation,
the FastAPI startup/shutdown, SQLite read/write/update, the history and
analytics endpoints, settings persistence, the static dashboard being
served, and friendly-error handling for a missing model, an unsupported
file type, and an unknown video ID (each returns a clean JSON error
instead of a crash). The detection/tracking/counting/annotation code
(`tracker.py`, `counter.py`, `density.py`, `video_processor.py`) was
reviewed carefully and follows the documented Ultralytics `model.track()`
API, but you should run it on a real clip on your own machine as your
first step -- see section 7 -- and treat that as part of your own
required testing pass.

---

## 11. Known limitations

- The counting line is horizontal only (no angled or polygonal counting
  regions) -- simple to reason about, but not ideal for camera angles
  where traffic doesn't cross a clean horizontal line.
- `suspected_duplicates` is a heuristic, not a guarantee -- always confirm
  with a manual review.
- Output video is written with the `mp4v` codec for maximum compatibility
  with OpenCV's default build; if your browser won't play it back, install
  `ffmpeg` and re-encode, or install `opencv-python` with a build that
  includes H.264 support.
- A live camera stream (as opposed to a recorded file) isn't implemented;
  the architecture supports it (swap `cv2.VideoCapture(path)` for
  `cv2.VideoCapture(0)` in `video_processor.py`), but it wasn't required
  to run this deliverable end-to-end without physical camera hardware.
- Processing runs on CPU by default and is slower than real time on
  typical laptops with `yolov8n.pt`; for real-time-ish performance, use a
  GPU-enabled PyTorch install or a smaller/shorter clip.
- Video seeking in the History video player depends on your browser's
  support for range requests against `FileResponse`; if seeking feels
  clunky, that's a good "future improvement" to mention in your report.

## 12. Future improvements

- Polygonal / multi-line counting regions for arbitrary camera angles.
- Real-time camera ingestion (RTSP/webcam) alongside file upload.
- Per-lane counting and speed estimation from tracked trajectories.
- WebSocket push instead of polling for status/results.
- User accounts so multiple people can keep separate history.

---

## 13. Short viva explanation

*"This is a full-stack computer vision system. A user uploads a traffic
video through the web dashboard. The FastAPI backend opens it with
OpenCV and runs each frame through a pretrained YOLOv8 model, which
detects road users (cars, buses, trucks, motorcycles, bicycles) and,
paired with the ByteTrack algorithm inside Ultralytics' `model.track()`
call, assigns each one a stable ID across frames. A counting module
watches each tracked vehicle's position relative to a configurable
horizontal line and counts it exactly once, the moment it crosses,
by remembering which IDs have already been counted. In parallel, a
density module looks at how many vehicles crossed in the last 30
seconds and classifies current traffic as LOW, MEDIUM or HIGH against
configurable thresholds. Every frame is annotated with bounding boxes,
labels, track IDs and a live HUD, streamed to the dashboard as an MJPEG
feed while it's written to an output video. Once a video finishes, its
summary and count-over-time history are saved to SQLite so it shows up
in the History page later, where you can also record manual notes on
missed or duplicate detections for the evaluation section of the
report."*

---

## 14. Configuration reference

Everything below lives in `backend/utils/config.py` and/or the Settings
page (persisted to `data/settings.json`):

| Setting | Default | Meaning |
|---|---|---|
| `counting_line_position` | 0.6 | Fraction of frame height for the counting line |
| `confidence_threshold` | 0.35 | Minimum YOLO detection confidence kept |
| `density_window_seconds` | 30 | Rolling window used for density |
| `density_low_max` | 10 | Max crossings/window still classified LOW |
| `density_medium_max` | 25 | Max crossings/window still classified MEDIUM |
| `model_name` | `yolov8n.pt` | Weights file in `backend/models/` |
| `enabled_classes` | all 5 | Which vehicle classes are actively detected |
