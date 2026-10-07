import asyncio
import io
import logging
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import cv2
import numpy as np
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Body
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spikes" / "s1-primer-detection" / "src"))

from camera import read_latest_frame, StaleFrameError
from camera_identity import CameraIdentityResolver
from runtime_state import read_alarm_state, request_ack
from setup_config import (
    load_config,
    save_config,
    SetupConfig,
)

logger = logging.getLogger("recap.setup")

# Constants
BASE_DIR = Path(__file__).parent.absolute()
STATE_DIR = BASE_DIR / "setup_state"
CONFIG_PATH = STATE_DIR / "config.json"
TEMPLATES_DIR = STATE_DIR / "templates"
SNAPSHOTS_DIR = STATE_DIR / "snapshots"
AUDIT_SCRIPT_PATH = BASE_DIR.parent / "spikes" / "s0-camera-path-stability" / "audit_paths.py"
ROI_ID_PATTERN = re.compile(r"^[A-Za-z0-9_+-]+$")

SETUP_TOKEN = os.environ.get("RECAP_SETUP_TOKEN")
if not SETUP_TOKEN:
    raise RuntimeError(
        "RECAP_SETUP_TOKEN environment variable must be set to a shared secret "
        "before starting the setup server (it is exposed on the network)."
    )

# Guards the config file's read-modify-write cycle against concurrent requests.
config_lock = asyncio.Lock()

app = FastAPI(title="ReCap Setup API")


async def verify_token(x_setup_token: str = Header(...)) -> None:
    if not secrets.compare_digest(x_setup_token, SETUP_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing token")

# Ensure directories exist
STATE_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Initialize resolver
resolver = CameraIdentityResolver(AUDIT_SCRIPT_PATH)

@app.on_event("startup")
async def startup_event():
    # Check if config exists, if not create a default one
    if not CONFIG_PATH.exists():
        print(f"No config found at {CONFIG_PATH}. Please create one.")

@app.get("/api/cameras", dependencies=[Depends(verify_token)])
async def get_cameras():
    result = resolver.list_cameras()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.get("/api/config", dependencies=[Depends(verify_token)])
async def get_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        return load_config(CONFIG_PATH).to_dict()
    except (FileNotFoundError, ValueError, KeyError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Failed to load config")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/config", dependencies=[Depends(verify_token)])
async def update_config(config_data: Dict[str, Any] = Body(...)):
    try:
        # We use the from_dict method from SetupConfig
        config = SetupConfig.from_dict(config_data)
        config.validate()
        async with config_lock:
            save_config(CONFIG_PATH, config)
        return {"status": "success"}
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to update config")
        raise HTTPException(status_code=500, detail="Internal server error")

def _capture_frame(video_index: int) -> np.ndarray:
    """Prefers camera.py's broker (see its module docstring) so this process
    never opens the camera directly -- opening it here would contend with
    main.py or the broker itself for the same physical device, which is
    exactly the multi-owner bug that produced three different, none-current
    images during live testing 2026-09-06. Falls back
    to opening the camera directly by video_index only when the broker
    isn't running, e.g. local Windows dev without a Pi/camera.py at all."""
    try:
        return read_latest_frame()
    except (FileNotFoundError, StaleFrameError):
        pass

    cap = cv2.VideoCapture(video_index)
    if not cap.isOpened():
        raise HTTPException(status_code=500, detail="Could not open camera")

    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise HTTPException(status_code=500, detail="Failed to capture frame")

    return frame

@app.get("/api/snapshot", dependencies=[Depends(verify_token)])
async def get_snapshot(by_path: Optional[str] = None, video_index: Optional[int] = None):
    """
    Captures a single frame from the specified camera.
    """
    # In a real Pi environment, we'd use by_path.
    # On Windows, we'll use the index if provided.
    if video_index is None:
        if by_path:
            # This is a placeholder for Pi-side logic
            # On Windows, we can't easily use by_path
            raise HTTPException(status_code=400, detail="by_path not supported on Windows")
        raise HTTPException(status_code=400, detail="Must provide video_index or by_path")

    frame = await run_in_threadpool(_capture_frame, video_index)

    # Encode to JPEG
    _, buffer = cv2.imencode(".jpg", frame)

    return StreamingResponse(io.BytesIO(buffer.tobytes()), media_type="image/jpeg")

@app.post("/api/capture-template", dependencies=[Depends(verify_token)])
async def capture_template(
    by_path: str = Body(..., embed=True),
    roi_id: str = Body(..., embed=True, pattern=ROI_ID_PATTERN.pattern),
    kind: Literal["present", "absent"] = Body(..., embed=True)
):
    """
    Captures a frame, crops it to the ROI, and saves it as a template.
    """
    async with config_lock:
        # 1. Load config to get ROI and camera info
        if not CONFIG_PATH.exists():
            raise HTTPException(status_code=404, detail="Config not found")

        config = load_config(CONFIG_PATH)

        # 2. Find camera by path
        if config.camera.by_path != by_path:
             raise HTTPException(status_code=400, detail=f"Config is for {config.camera.by_path}, not {by_path}")

        # 3. Find ROI
        roi = next((r for r in config.rois if r.id == roi_id), None)
        if not roi:
            raise HTTPException(status_code=404, detail=f"ROI {roi_id} not found")

        # 4. Capture frame
        frame = await run_in_threadpool(_capture_frame, config.camera.video_index)

        # 5. Crop to ROI
        crop = frame[roi.y1:roi.y2, roi.x1:roi.x2]
        if crop.size == 0:
            frame_h, frame_w = frame.shape[:2]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"ROI '{roi_id}' ({roi.x1},{roi.y1})-({roi.x2},{roi.y2}) doesn't fit the "
                    f"captured frame ({frame_w}x{frame_h}). Adjust the ROI to fit within the frame."
                ),
            )

        # 6. Save canonical template
        template_filename = f"{roi_id}_{kind}.png"
        template_path = TEMPLATES_DIR / template_filename
        cv2.imwrite(str(template_path), crop)

        # 7. Save timestamped archive
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_filename = f"{timestamp}_{roi_id}_{kind}.png"
        archive_path = SNAPSHOTS_DIR / archive_filename
        cv2.imwrite(str(archive_path), crop)

        # 8. Update config with the relative path to the template
        rel_path = template_path.relative_to(BASE_DIR)

        from setup_config import TemplateEntry
        existing_entry = next((t for t in config.templates if t.roi_id == roi_id and t.kind == kind), None)

        if existing_entry:
            existing_entry.rel = str(rel_path)
        else:
            config.templates.append(TemplateEntry(roi_id=roi_id, kind=kind, rel=str(rel_path)))

        save_config(CONFIG_PATH, config)

    return {
        "status": "success",
        "canonical_path": str(template_path),
        "archive_path": str(archive_path),
        "template_rel_path": str(rel_path)
    }

@app.get("/api/alarm-state", dependencies=[Depends(verify_token)])
async def get_alarm_state():
    return read_alarm_state()

@app.post("/api/alarm-ack", dependencies=[Depends(verify_token)])
async def post_alarm_ack():
    request_ack()
    return {"status": "success"}

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")

# Mount static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

