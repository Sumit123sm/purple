from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelineSettings:
    data_dir: Path = Path("data")
    clips_dir: Path = Path("data/clips")
    layout_path: Path = Path("data/store_layout.json")
    output_path: Path = Path("data/events/output.jsonl")
    yolo_model: str = "yolov8n.pt"
    # Device string passed to the inference model, e.g. 'cpu' or 'cuda:0'
    device: str = "cpu"
    dwell_emit_interval_ms: int = 30_000
    reentry_window_seconds: int = 1800
    staff_uniform_hue_range: tuple[int, int] = (20, 45)
    min_detection_confidence: float = 0.25
    default_fps: float = 15.0
