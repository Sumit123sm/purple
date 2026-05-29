import json
from pathlib import Path
from typing import Any


def load_store_layout(path: str | Path) -> dict[str, Any]:
    layout_path = Path(path)
    if not layout_path.exists():
        raise FileNotFoundError(f"store layout not found: {layout_path}")
    return json.loads(layout_path.read_text(encoding="utf-8"))


def get_store_config(layout: dict[str, Any], store_id: str) -> dict[str, Any]:
    for store in layout.get("stores", []):
        if store["store_id"] == store_id:
            return store
    raise KeyError(f"store not found in layout: {store_id}")


def get_camera_config(store: dict[str, Any], camera_id: str) -> dict[str, Any]:
    for camera in store.get("cameras", []):
        if camera["camera_id"] == camera_id:
            return camera
    raise KeyError(f"camera not found: {camera_id}")


def infer_store_camera_from_filename(filename: str) -> tuple[str | None, str | None]:
    """Parse STORE_XXX_YYY_CAM_ENTRY_01.mp4 style filenames."""
    stem = Path(filename).stem.upper()
    parts = stem.split("_")
    store_id = None
    camera_id = None

    if stem.startswith("STORE"):
        for index in range(len(parts) - 1):
            if parts[index] == "STORE" and index + 2 < len(parts):
                store_id = f"{parts[index]}_{parts[index + 1]}_{parts[index + 2]}"
                break

    for index, part in enumerate(parts):
        if part == "CAM" and index + 2 < len(parts):
            camera_id = f"CAM_{parts[index + 1]}_{parts[index + 2]}"
            break

    return store_id, camera_id
