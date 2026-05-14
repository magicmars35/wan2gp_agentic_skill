from pathlib import Path
from uuid import uuid4
from datetime import datetime
import threading
import time
import json
import copy
import random

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from shared.api import init


# =========================================================
# CONFIG
# =========================================================

WAN2GP_ROOT = Path(r"G:\APPS\Wan2GP")

TEMPLATE_T2V_FILE = WAN2GP_ROOT / "ltx2_template_t2v.json"
TEMPLATE_I2V_FILE = WAN2GP_ROOT / "ltx2_template_i2v.json"

OUTPUT_DIR = WAN2GP_ROOT / "api_outputs"
INPUT_DIR = WAN2GP_ROOT / "api_inputs"

API_TOKEN = "HGH7EPBCE51vureBCBUEBCE75678edfv9HUGBC7E"

FIXED_MODEL_TYPE = "ltx2_22B_distilled_1_1"
FIXED_BASE_MODEL_TYPE = "ltx2_22B"
DISPLAY_MODEL_NAME = "LTX-2 2.3 Distilled 1.1 22B"

DEFAULT_RESOLUTION = "1280x720"
DEFAULT_FPS = 24
DEFAULT_DURATION_SECONDS = 3
DEFAULT_STEPS = 8

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# HELPERS
# =========================================================

def now_iso():
    return datetime.now().isoformat()


def check_auth(authorization: str | None):
    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def load_template_settings(template_file: Path) -> dict:
    if not template_file.exists():
        raise RuntimeError(f"Template introuvable : {template_file}")

    with open(template_file, "r", encoding="utf-8") as f:
        exported = json.load(f)

    if not isinstance(exported, list) or not exported:
        raise RuntimeError(f"Template invalide : {template_file}")

    first = exported[0]
    if "params" not in first:
        raise RuntimeError(f"Le template ne contient pas 'params' : {template_file}")

    settings = first["params"]
    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE

    return settings


TEMPLATE_T2V_SETTINGS = load_template_settings(TEMPLATE_T2V_FILE)
TEMPLATE_I2V_SETTINGS = load_template_settings(TEMPLATE_I2V_FILE)


def compute_video_length(duration_seconds: int, fps: int) -> int:
    return int(duration_seconds * fps) + 1


def base_settings(mode: str) -> dict:
    if mode == "t2v":
        settings = copy.deepcopy(TEMPLATE_T2V_SETTINGS)
    elif mode == "i2v":
        settings = copy.deepcopy(TEMPLATE_I2V_SETTINGS)
    else:
        raise ValueError(f"Mode inconnu : {mode}")

    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE
    settings["client_id"] = ""
    settings["output_filename"] = ""

    return settings


def build_t2v_settings(
    prompt: str,
    duration_seconds: int,
    fps: int,
    resolution: str,
    seed: int | None,
    negative_prompt: str | None,
    num_inference_steps: int,
) -> dict:
    settings = base_settings("t2v")

    settings["prompt"] = prompt
    settings["negative_prompt"] = negative_prompt or ""

    settings["resolution"] = resolution
    settings["video_length"] = compute_video_length(duration_seconds, fps)
    settings["duration_seconds"] = 0
    settings["force_fps"] = fps
    settings["num_inference_steps"] = num_inference_steps

    settings["image_start"] = None
    settings["image_end"] = None
    settings["image_refs"] = None
    settings["frames_positions"] = None
    settings["video_source"] = None
    settings["video_guide"] = None
    settings["image_guide"] = None
    settings["video_prompt_type"] = ""
    settings["mode"] = ""
    settings["image_mode"] = 0

    settings["seed"] = seed if seed is not None else random.randint(1, 2_147_483_647)

    return settings


def build_i2v_settings(
    prompt: str,
    image_path: Path,
    duration_seconds: int,
    fps: int,
    resolution: str,
    seed: int | None,
    negative_prompt: str | None,
    num_inference_steps: int,
) -> dict:
    settings = base_settings("i2v")

    settings["prompt"] = prompt
    settings["negative_prompt"] = negative_prompt or ""

    settings["resolution"] = resolution
    settings["video_length"] = compute_video_length(duration_seconds, fps)
    settings["duration_seconds"] = 0
    settings["force_fps"] = fps
    settings["num_inference_steps"] = num_inference_steps

    settings["image_start"] = str(image_path)
    settings["image_end"] = None
    settings["image_refs"] = None
    settings["frames_positions"] = None
    settings["video_source"] = None
    settings["video_guide"] = None
    settings["image_guide"] = None
    settings["video_prompt_type"] = ""
    settings["mode"] = ""
    settings["image_mode"] = 0

    settings["seed"] = seed if seed is not None else random.randint(1, 2_147_483_647)

    return settings


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="Wan2GP LAN API",
    version="2.0",
    description="API LAN pour générer des vidéos via Wan2GP",
)

jobs = {}
jobs_lock = threading.Lock()
queue_lock = threading.Lock()
job_sequence_counter = 0


# =========================================================
# WAN2GP INIT
# =========================================================

print("Initialisation Wan2GP...")
session = init(
    root=WAN2GP_ROOT,
    output_dir=OUTPUT_DIR,
    cli_args=["--attention", "sdpa", "--profile", "4"],
    console_output=True,
)
print("Wan2GP prêt.")


# =========================================================
# REQUEST MODELS
# =========================================================

class TextToVideoRequest(BaseModel):
    prompt: str = Field(..., min_length=3)
    duration_seconds: int = Field(DEFAULT_DURATION_SECONDS, ge=1, le=30)
    fps: int = Field(DEFAULT_FPS, ge=1, le=60)
    resolution: str = DEFAULT_RESOLUTION
    seed: int | None = None
    negative_prompt: str | None = None
    num_inference_steps: int = Field(DEFAULT_STEPS, ge=1, le=100)


# =========================================================
# JOB HELPERS
# =========================================================

def register_job(job_data: dict) -> dict:
    global job_sequence_counter

    with jobs_lock:
        job_sequence_counter += 1
        job_data["sequence"] = job_sequence_counter
        job_data["updated_at"] = now_iso()
        jobs[job_data["job_id"]] = job_data
        return copy.deepcopy(job_data)


def update_job(job_id: str, **fields):
    with jobs_lock:
        if job_id not in jobs:
            return
        jobs[job_id].update(fields)
        jobs[job_id]["updated_at"] = now_iso()


def get_job_raw(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def get_active_jobs_sorted():
    with jobs_lock:
        active = [
            copy.deepcopy(j)
            for j in jobs.values()
            if j["status"] in ("queued", "running")
        ]
    active.sort(key=lambda x: x["sequence"])
    return active


def add_runtime_fields(job: dict | None):
    if not job:
        return None

    active = get_active_jobs_sorted()

    queue_position = None
    for idx, item in enumerate(active):
        if item["job_id"] == job["job_id"]:
            queue_position = idx
            break

    job["queue_position"] = queue_position

    if job["status"] == "queued":
        job["short_status"] = "Q"
    elif job["status"] == "running":
        job["short_status"] = "R"
    elif job["status"] == "completed":
        job["short_status"] = "C"
    elif job["status"] == "failed":
        job["short_status"] = "F"
    else:
        job["short_status"] = "?"

    return job


# =========================================================
# GENERATION RUNNER
# =========================================================

def run_generation(job_id: str, settings: dict):
    try:
        with queue_lock:
            update_job(
                job_id,
                status="running",
                started_at=now_iso(),
                progress=0,
                phase="starting",
                message="Generation started",
            )

            job = session.submit_task(settings)

            while not job.done:
                for event in job.events.iter(timeout=0.2):
                    if event.kind == "progress":
                        progress = event.data
                        update_job(
                            job_id,
                            progress=getattr(progress, "progress", 0),
                            phase=str(getattr(progress, "phase", "")),
                            current_step=getattr(progress, "current_step", None),
                            total_steps=getattr(progress, "total_steps", None),
                            message="Generation in progress",
                        )

                    elif event.kind == "status":
                        update_job(job_id, message=str(event.data))

                    elif event.kind == "preview":
                        update_job(job_id, message="Preview received")

                    elif event.kind == "stream":
                        line = event.data
                        update_job(job_id, last_log=f"[{line.stream}] {line.text}")

                time.sleep(0.2)

            result = job.result()

            if result.success:
                files = [str(f) for f in result.generated_files]
                download_urls = [
                    f"/download/{job_id}/{Path(f).name}"
                    for f in files
                ]

                update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    phase="done",
                    message="Generation completed",
                    files=files,
                    download_urls=download_urls,
                    finished_at=now_iso(),
                )
            else:
                errors = [
                    {
                        "message": err.message,
                        "stage": err.stage,
                        "task_index": err.task_index,
                    }
                    for err in result.errors
                ]

                update_job(
                    job_id,
                    status="failed",
                    phase="error",
                    message="Generation failed",
                    errors=errors,
                    finished_at=now_iso(),
                )

    except Exception as e:
        update_job(
            job_id,
            status="failed",
            phase="exception",
            message="Unhandled exception",
            errors=[{"message": str(e), "stage": "runtime"}],
            finished_at=now_iso(),
        )


# =========================================================
# ROUTES
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "wan2gp-api",
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
    }


@app.get("/model")
def model_info(authorization: str | None = Header(default=None)):
    check_auth(authorization)

    return {
        "fixed_model": True,
        "display_name": DISPLAY_MODEL_NAME,
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "template_t2v_file": str(TEMPLATE_T2V_FILE),
        "template_i2v_file": str(TEMPLATE_I2V_FILE),
        "default_resolution": DEFAULT_RESOLUTION,
        "default_fps": DEFAULT_FPS,
        "default_duration_seconds": DEFAULT_DURATION_SECONDS,
    }


@app.get("/jobs")
def list_jobs(authorization: str | None = Header(default=None)):
    check_auth(authorization)

    with jobs_lock:
        data = [copy.deepcopy(j) for j in jobs.values()]

    data.sort(key=lambda x: x["sequence"], reverse=True)
    data = [add_runtime_fields(j) for j in data]

    return {
        "count": len(data),
        "jobs": data,
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)):
    check_auth(authorization)

    job = get_job_raw(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return add_runtime_fields(job)


@app.post("/generate/t2v")
def generate_t2v(
    req: TextToVideoRequest,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)

    job_id = str(uuid4())

    settings = build_t2v_settings(
        prompt=req.prompt,
        duration_seconds=req.duration_seconds,
        fps=req.fps,
        resolution=req.resolution,
        seed=req.seed,
        negative_prompt=req.negative_prompt,
        num_inference_steps=req.num_inference_steps,
    )

    register_job({
        "job_id": job_id,
        "status": "queued",
        "mode": "text_to_video",
        "created_at": now_iso(),
        "prompt": req.prompt,
        "duration_seconds": req.duration_seconds,
        "fps": req.fps,
        "resolution": req.resolution,
        "seed": settings["seed"],
        "model_type": FIXED_MODEL_TYPE,
        "progress": 0,
        "phase": "queued",
        "message": "Job queued",
        "current_step": None,
        "total_steps": None,
        "files": [],
        "download_urls": [],
        "errors": [],
    })

    thread = threading.Thread(
        target=run_generation,
        args=(job_id, settings),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "text_to_video",
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/i2v")
async def generate_i2v(
    prompt: str = Form(...),
    image: UploadFile = File(...),
    duration_seconds: int = Form(DEFAULT_DURATION_SECONDS),
    fps: int = Form(DEFAULT_FPS),
    resolution: str = Form(DEFAULT_RESOLUTION),
    seed: int | None = Form(None),
    negative_prompt: str | None = Form(None),
    num_inference_steps: int = Form(DEFAULT_STEPS),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)

    if duration_seconds < 1 or duration_seconds > 30:
        raise HTTPException(status_code=400, detail="duration_seconds doit être entre 1 et 30")

    if fps < 1 or fps > 60:
        raise HTTPException(status_code=400, detail="fps doit être entre 1 et 60")

    if num_inference_steps < 1 or num_inference_steps > 100:
        raise HTTPException(status_code=400, detail="num_inference_steps doit être entre 1 et 100")

    original_name = Path(image.filename or "image.png").name
    extension = Path(original_name).suffix.lower()

    if extension not in [".png", ".jpg", ".jpeg", ".webp"]:
        raise HTTPException(status_code=400, detail="Format image accepté : png, jpg, jpeg, webp")

    job_id = str(uuid4())
    image_filename = f"{job_id}_{original_name}"
    image_path = INPUT_DIR / image_filename

    file_bytes = await image.read()
    with open(image_path, "wb") as f:
        f.write(file_bytes)

    settings = build_i2v_settings(
        prompt=prompt,
        image_path=image_path,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
    )

    register_job({
        "job_id": job_id,
        "status": "queued",
        "mode": "image_to_video",
        "created_at": now_iso(),
        "prompt": prompt,
        "input_image": str(image_path),
        "duration_seconds": duration_seconds,
        "fps": fps,
        "resolution": resolution,
        "seed": settings["seed"],
        "model_type": FIXED_MODEL_TYPE,
        "progress": 0,
        "phase": "queued",
        "message": "Job queued",
        "current_step": None,
        "total_steps": None,
        "files": [],
        "download_urls": [],
        "errors": [],
    })

    thread = threading.Thread(
        target=run_generation,
        args=(job_id, settings),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "image_to_video",
        "status_url": f"/jobs/{job_id}",
    }


@app.get("/download/{job_id}/{filename}")
def download(
    job_id: str,
    filename: str,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)

    job = get_job_raw(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    for file_path in job.get("files", []):
        path = Path(file_path)
        if path.name == filename and path.exists():
            return FileResponse(
                path,
                media_type="video/mp4",
                filename=path.name,
            )

    raise HTTPException(status_code=404, detail="File not found")


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    uvicorn.run(
        "wan2gp_api_server:app",
        host="0.0.0.0",
        port=7861,
        reload=False,
    )