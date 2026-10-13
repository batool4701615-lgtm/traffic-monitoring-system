"""Pydantic models used across the FastAPI endpoints."""

from typing import Optional, List
from pydantic import BaseModel


class UploadVideoResponse(BaseModel):
    video_id: str
    filename: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    total_frames: int


class StartProcessingRequest(BaseModel):
    video_id: str
    counting_line_position: Optional[float] = None
    confidence_threshold: Optional[float] = None
    model_name: Optional[str] = None


class ControlRequest(BaseModel):
    action: str  # "pause" | "resume" | "stop" | "reset"


class CountsResponse(BaseModel):
    total: int
    car: int
    bus: int
    truck: int
    motorcycle: int
    bicycle: int


class DensityResponse(BaseModel):
    level: str
    color: str
    vehicles_in_window: int
    window_seconds: int


class StatusResponse(BaseModel):
    status: str  # idle | processing | paused | completed | stopped | error
    session_id: Optional[int] = None
    video_id: Optional[str] = None
    video_name: Optional[str] = None
    progress_percent: float
    current_frame: int
    total_frames: int
    processing_fps: float
    elapsed_seconds: float
    error_message: Optional[str] = None
    output_ready: bool = False


class ResultsResponse(BaseModel):
    status: str
    timestamp: Optional[str] = None
    counts: CountsResponse
    density: DensityResponse
    processing_fps: float
    suspected_duplicates: int


class SessionSummary(BaseModel):
    id: int
    created_at: str
    video_name: str
    total: int
    car: int
    bus: int
    truck: int
    motorcycle: int
    bicycle: int
    density: str
    fps: float
    duration_seconds: float
    suspected_duplicates: int
    missed_detections: Optional[int] = None
    duplicate_detections: Optional[int] = None
    notes: Optional[str] = None
    output_video: Optional[str] = None


class SessionUpdate(BaseModel):
    missed_detections: Optional[int] = None
    duplicate_detections: Optional[int] = None
    notes: Optional[str] = None


class TimeseriesPoint(BaseModel):
    timestamp: str
    total: int


class SessionDetail(BaseModel):
    session: SessionSummary
    timeseries: List[TimeseriesPoint]


class SettingsModel(BaseModel):
    counting_line_position: float
    confidence_threshold: float
    density_window_seconds: int
    density_low_max: int
    density_medium_max: int
    model_name: str
    enabled_classes: List[str]


class SettingsUpdate(BaseModel):
    counting_line_position: Optional[float] = None
    confidence_threshold: Optional[float] = None
    density_window_seconds: Optional[int] = None
    density_low_max: Optional[int] = None
    density_medium_max: Optional[int] = None
    model_name: Optional[str] = None
    enabled_classes: Optional[List[str]] = None
