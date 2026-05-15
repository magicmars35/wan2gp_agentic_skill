from pathlib import Path
from uuid import uuid4
from datetime import datetime
import threading
import time
import json
import copy
import random

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from shared.api import init


# =========================================================
# CONFIG
# =========================================================

WAN2GP_ROOT = Path(r"G:\APPS\Wan2GP")

TEMPLATE_FILES = {
    "t2v": WAN2GP_ROOT / "ltx2_template_t2v.json",
    "i2v": WAN2GP_ROOT / "ltx2_template_i2v.json",
    "i2v_end": WAN2GP_ROOT / "ltx2_template_i2v_end.json",
    "s2v": WAN2GP_ROOT / "ltx2_template_s2v.json",
    "s2v_i2v": WAN2GP_ROOT / "ltx2_template_s2v_i2v.json",
    "s2v_i2v_lora": WAN2GP_ROOT / "ltx2_template_s2v_i2v_lora.json",
}

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

MAX_DURATION_SECONDS = 60
MAX_FPS = 60
MAX_STEPS = 100

ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]
ALLOWED_AUDIO_EXTENSIONS = [".mp3", ".wav", ".ogg", ".m4a", ".flac"]

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


def get_requester_info(request: Request) -> dict:
    """
    Retourne les informations réseau du client qui a demandé le job.

    requester_ip :
    - utilise X-Forwarded-For si présent
    - sinon utilise request.client.host

    requester_user_agent :
    - utile pour distinguer OpenClaw, Hermes, curl, Python requests, navigateur, etc.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    user_agent = request.headers.get("user-agent", "")

    if forwarded_for:
        requester_ip = forwarded_for.split(",")[0].strip()
    elif real_ip:
        requester_ip = real_ip.strip()
    elif request.client:
        requester_ip = request.client.host
    else:
        requester_ip = ""

    return {
        "requester_ip": requester_ip,
        "requester_user_agent": user_agent,
    }


def validate_common_params(duration_seconds: int, fps: int, num_inference_steps: int):
    if duration_seconds < 1 or duration_seconds > MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"duration_seconds doit être entre 1 et {MAX_DURATION_SECONDS}",
        )

    if fps < 1 or fps > MAX_FPS:
        raise HTTPException(
            status_code=400,
            detail=f"fps doit être entre 1 et {MAX_FPS}",
        )

    if num_inference_steps < 1 or num_inference_steps > MAX_STEPS:
        raise HTTPException(
            status_code=400,
            detail=f"num_inference_steps doit être entre 1 et {MAX_STEPS}",
        )


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


TEMPLATE_SETTINGS = {
    mode: load_template_settings(path)
    for mode, path in TEMPLATE_FILES.items()
}


def compute_video_length(duration_seconds: int, fps: int) -> int:
    return int(duration_seconds * fps) + 1


def base_settings(mode: str) -> dict:
    if mode not in TEMPLATE_SETTINGS:
        raise ValueError(f"Mode inconnu : {mode}")

    settings = copy.deepcopy(TEMPLATE_SETTINGS[mode])

    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE
    settings["client_id"] = ""
    settings["output_filename"] = ""

    return settings


def save_upload_path(
    upload: UploadFile,
    job_id: str,
    prefix: str,
    allowed_extensions: list[str],
) -> Path:
    original_name = Path(upload.filename or f"{prefix}.bin").name
    extension = Path(original_name).suffix.lower()

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Format non accepté pour {prefix}. Formats acceptés : {', '.join(allowed_extensions)}",
        )

    filename = f"{job_id}_{prefix}_{original_name}"
    return INPUT_DIR / filename


async def write_upload_to_disk(upload: UploadFile, destination: Path):
    file_bytes = await upload.read()

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Fichier vide : {upload.filename}",
        )

    with open(destination, "wb") as f:
        f.write(file_bytes)


def build_v2_settings(
    mode: str,
    prompt: str,
    duration_seconds: int,
    fps: int,
    resolution: str,
    seed: int | None,
    negative_prompt: str | None,
    num_inference_steps: int,
    image_start: Path | None = None,
    image_end: Path | None = None,
    audio_guide: Path | None = None,
) -> dict:
    settings = base_settings(mode)

    settings["prompt"] = prompt
    settings["negative_prompt"] = negative_prompt or ""

    settings["resolution"] = resolution
    settings["video_length"] = compute_video_length(duration_seconds, fps)
    settings["duration_seconds"] = 0
    settings["force_fps"] = fps
    settings["num_inference_steps"] = num_inference_steps

    settings["seed"] = seed if seed is not None else random.randint(1, 2_147_483_647)

    settings["image_start"] = str(image_start) if image_start else None
    settings["image_end"] = str(image_end) if image_end else None
    settings["audio_guide"] = str(audio_guide) if audio_guide else None
    settings["audio_guide2"] = None

    settings["image_refs"] = None
    settings["frames_positions"] = None
    settings["video_source"] = None
    settings["video_guide"] = None
    settings["image_guide"] = None
    settings["custom_guide"] = None
    settings["audio_source"] = None
    settings["video_prompt_type"] = ""
    settings["mode"] = ""
    settings["image_mode"] = 0

    if mode == "t2v":
        settings["image_prompt_type"] = ""
        settings["audio_prompt_type"] = ""
        settings["image_start"] = None
        settings["image_end"] = None
        settings["audio_guide"] = None
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

    elif mode == "i2v":
        settings["image_prompt_type"] = "S"
        settings["audio_prompt_type"] = ""
        settings["image_end"] = None
        settings["audio_guide"] = None
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

    elif mode == "i2v_end":
        settings["image_prompt_type"] = "SE"
        settings["audio_prompt_type"] = ""
        settings["audio_guide"] = None
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

    elif mode == "s2v":
        settings["image_prompt_type"] = ""
        settings["audio_prompt_type"] = "A"
        settings["image_start"] = None
        settings["image_end"] = None
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

    elif mode == "s2v_i2v":
        settings["image_prompt_type"] = "S"
        settings["audio_prompt_type"] = "A"
        settings["image_end"] = None
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

    elif mode == "s2v_i2v_lora":
        settings["image_prompt_type"] = "S"
        settings["audio_prompt_type"] = "A"
        settings["image_end"] = None
        # On conserve activated_loras et loras_multipliers depuis le template.

    else:
        raise ValueError(f"Mode inconnu : {mode}")

    return settings


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="Wan2GP LAN API",
    version="2.1",
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
    duration_seconds: int = Field(DEFAULT_DURATION_SECONDS, ge=1, le=MAX_DURATION_SECONDS)
    fps: int = Field(DEFAULT_FPS, ge=1, le=MAX_FPS)
    resolution: str = DEFAULT_RESOLUTION
    seed: int | None = None
    negative_prompt: str | None = None
    num_inference_steps: int = Field(DEFAULT_STEPS, ge=1, le=MAX_STEPS)


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


def create_job_record(
    job_id: str,
    mode: str,
    prompt: str,
    settings: dict,
    duration_seconds: int,
    fps: int,
    resolution: str,
    requester_info: dict,
    extra: dict | None = None,
):
    data = {
        "job_id": job_id,
        "status": "queued",
        "mode": mode,
        "created_at": now_iso(),
        "prompt": prompt,
        "duration_seconds": duration_seconds,
        "fps": fps,
        "resolution": resolution,
        "seed": settings["seed"],
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "requester_ip": requester_info.get("requester_ip", ""),
        "requester_user_agent": requester_info.get("requester_user_agent", ""),
        "progress": 0,
        "phase": "queued",
        "message": "Job queued",
        "current_step": None,
        "total_steps": None,
        "files": [],
        "download_urls": [],
        "errors": [],
    }

    if extra:
        data.update(extra)

    register_job(data)


def start_generation_thread(job_id: str, settings: dict):
    thread = threading.Thread(
        target=run_generation,
        args=(job_id, settings),
        daemon=True,
    )
    thread.start()


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
                        update_job(
                            job_id,
                            message=str(event.data),
                        )

                    elif event.kind == "preview":
                        update_job(
                            job_id,
                            message="Preview received",
                        )

                    elif event.kind == "stream":
                        line = event.data
                        update_job(
                            job_id,
                            last_log=f"[{line.stream}] {line.text}",
                        )

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
            errors=[
                {
                    "message": str(e),
                    "stage": "runtime",
                }
            ],
            finished_at=now_iso(),
        )


# =========================================================
# ROUTES GENERALES
# =========================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "wan2gp-api",
        "version": "2.1",
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "modes": list(TEMPLATE_FILES.keys()),
    }


@app.get("/model")
def model_info(authorization: str | None = Header(default=None)):
    check_auth(authorization)

    return {
        "fixed_model": True,
        "display_name": DISPLAY_MODEL_NAME,
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "templates": {
            mode: str(path)
            for mode, path in TEMPLATE_FILES.items()
        },
        "default_resolution": DEFAULT_RESOLUTION,
        "default_fps": DEFAULT_FPS,
        "default_duration_seconds": DEFAULT_DURATION_SECONDS,
        "default_steps": DEFAULT_STEPS,
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


# =========================================================
# ROUTES GENERATION V2.1
# =========================================================

@app.post("/generate/t2v")
def generate_t2v(
    req: TextToVideoRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    settings = build_v2_settings(
        mode="t2v",
        prompt=req.prompt,
        duration_seconds=req.duration_seconds,
        fps=req.fps,
        resolution=req.resolution,
        seed=req.seed,
        negative_prompt=req.negative_prompt,
        num_inference_steps=req.num_inference_steps,
    )

    create_job_record(
        job_id=job_id,
        mode="text_to_video",
        prompt=req.prompt,
        settings=settings,
        duration_seconds=req.duration_seconds,
        fps=req.fps,
        resolution=req.resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "t2v",
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "text_to_video",
        "api_mode": "t2v",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/i2v")
async def generate_i2v(
    request: Request,
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
    validate_common_params(duration_seconds, fps, num_inference_steps)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    image_path = save_upload_path(
        upload=image,
        job_id=job_id,
        prefix="image_start",
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
    )

    await write_upload_to_disk(image, image_path)

    settings = build_v2_settings(
        mode="i2v",
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        image_start=image_path,
    )

    create_job_record(
        job_id=job_id,
        mode="image_to_video",
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "i2v",
            "input_image": str(image_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "image_to_video",
        "api_mode": "i2v",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/i2v_end")
async def generate_i2v_end(
    request: Request,
    prompt: str = Form(...),
    image_start: UploadFile = File(...),
    image_end: UploadFile = File(...),
    duration_seconds: int = Form(DEFAULT_DURATION_SECONDS),
    fps: int = Form(DEFAULT_FPS),
    resolution: str = Form(DEFAULT_RESOLUTION),
    seed: int | None = Form(None),
    negative_prompt: str | None = Form(None),
    num_inference_steps: int = Form(DEFAULT_STEPS),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)
    validate_common_params(duration_seconds, fps, num_inference_steps)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    image_start_path = save_upload_path(
        upload=image_start,
        job_id=job_id,
        prefix="image_start",
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
    )

    image_end_path = save_upload_path(
        upload=image_end,
        job_id=job_id,
        prefix="image_end",
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
    )

    await write_upload_to_disk(image_start, image_start_path)
    await write_upload_to_disk(image_end, image_end_path)

    settings = build_v2_settings(
        mode="i2v_end",
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        image_start=image_start_path,
        image_end=image_end_path,
    )

    create_job_record(
        job_id=job_id,
        mode="image_to_video_with_end_image",
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "i2v_end",
            "input_image_start": str(image_start_path),
            "input_image_end": str(image_end_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "image_to_video_with_end_image",
        "api_mode": "i2v_end",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/s2v")
async def generate_s2v(
    request: Request,
    prompt: str = Form(...),
    audio: UploadFile = File(...),
    duration_seconds: int = Form(DEFAULT_DURATION_SECONDS),
    fps: int = Form(DEFAULT_FPS),
    resolution: str = Form(DEFAULT_RESOLUTION),
    seed: int | None = Form(None),
    negative_prompt: str | None = Form(None),
    num_inference_steps: int = Form(DEFAULT_STEPS),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)
    validate_common_params(duration_seconds, fps, num_inference_steps)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    audio_path = save_upload_path(
        upload=audio,
        job_id=job_id,
        prefix="audio",
        allowed_extensions=ALLOWED_AUDIO_EXTENSIONS,
    )

    await write_upload_to_disk(audio, audio_path)

    settings = build_v2_settings(
        mode="s2v",
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        audio_guide=audio_path,
    )

    create_job_record(
        job_id=job_id,
        mode="sound_to_video",
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v",
            "input_audio": str(audio_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "sound_to_video",
        "api_mode": "s2v",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/s2v_i2v")
async def generate_s2v_i2v(
    request: Request,
    prompt: str = Form(...),
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    duration_seconds: int = Form(DEFAULT_DURATION_SECONDS),
    fps: int = Form(DEFAULT_FPS),
    resolution: str = Form(DEFAULT_RESOLUTION),
    seed: int | None = Form(None),
    negative_prompt: str | None = Form(None),
    num_inference_steps: int = Form(DEFAULT_STEPS),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)
    validate_common_params(duration_seconds, fps, num_inference_steps)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    image_path = save_upload_path(
        upload=image,
        job_id=job_id,
        prefix="image_start",
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
    )

    audio_path = save_upload_path(
        upload=audio,
        job_id=job_id,
        prefix="audio",
        allowed_extensions=ALLOWED_AUDIO_EXTENSIONS,
    )

    await write_upload_to_disk(image, image_path)
    await write_upload_to_disk(audio, audio_path)

    settings = build_v2_settings(
        mode="s2v_i2v",
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        image_start=image_path,
        audio_guide=audio_path,
    )

    create_job_record(
        job_id=job_id,
        mode="sound_to_video_with_reference_image",
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v_i2v",
            "input_image": str(image_path),
            "input_audio": str(audio_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "sound_to_video_with_reference_image",
        "api_mode": "s2v_i2v",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


@app.post("/generate/s2v_i2v_lora")
async def generate_s2v_i2v_lora(
    request: Request,
    prompt: str = Form(...),
    image: UploadFile = File(...),
    audio: UploadFile = File(...),
    duration_seconds: int = Form(DEFAULT_DURATION_SECONDS),
    fps: int = Form(DEFAULT_FPS),
    resolution: str = Form(DEFAULT_RESOLUTION),
    seed: int | None = Form(None),
    negative_prompt: str | None = Form(None),
    num_inference_steps: int = Form(DEFAULT_STEPS),
    authorization: str | None = Header(default=None),
):
    check_auth(authorization)
    validate_common_params(duration_seconds, fps, num_inference_steps)

    job_id = str(uuid4())
    requester_info = get_requester_info(request)

    image_path = save_upload_path(
        upload=image,
        job_id=job_id,
        prefix="image_start",
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
    )

    audio_path = save_upload_path(
        upload=audio,
        job_id=job_id,
        prefix="audio",
        allowed_extensions=ALLOWED_AUDIO_EXTENSIONS,
    )

    await write_upload_to_disk(image, image_path)
    await write_upload_to_disk(audio, audio_path)

    settings = build_v2_settings(
        mode="s2v_i2v_lora",
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        seed=seed,
        negative_prompt=negative_prompt,
        num_inference_steps=num_inference_steps,
        image_start=image_path,
        audio_guide=audio_path,
    )

    create_job_record(
        job_id=job_id,
        mode="sound_to_video_with_reference_image_and_lora",
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v_i2v_lora",
            "input_image": str(image_path),
            "input_audio": str(audio_path),
            "activated_loras": settings.get("activated_loras", []),
            "loras_multipliers": settings.get("loras_multipliers", ""),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": "sound_to_video_with_reference_image_and_lora",
        "api_mode": "s2v_i2v_lora",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
    }


# =========================================================
# DOWNLOAD
# =========================================================

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

    safe_filename = Path(filename).name

    for file_path in job.get("files", []):
        path = Path(file_path)

        if path.name == safe_filename and path.exists():
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
