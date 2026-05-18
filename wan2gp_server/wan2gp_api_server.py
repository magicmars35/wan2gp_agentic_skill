from pathlib import Path
from uuid import uuid4
from datetime import datetime
import threading
import time
import json
import copy
import random
import html
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
import uvicorn

from shared.api import init


# =========================================================
# CONFIG
# =========================================================

WAN2GP_ROOT = Path(r"G:\APPS\Wan2GP")

# Un seul template universel.
# Il doit contenir la structure complète exportée par Wan2GP :
# [
#   {
#     "id": ...,
#     "params": {
#       ...
#     }
#   }
# ]
#
# Important :
# Ce fichier peut être basé sur n'importe lequel des anciens templates LTX2,
# car les anciens fichiers avaient les mêmes clés.
# Le serveur applique ensuite les différences de mode avec apply_mode_controls().
TEMPLATE_FILE = WAN2GP_ROOT / "ltx2_template_universal.json"

OUTPUT_DIR = WAN2GP_ROOT / "api_outputs"
INPUT_DIR = WAN2GP_ROOT / "api_inputs"

API_TOKEN = "my-super-token-to-change"

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

# LoRA par défaut pour le mode s2v_i2v_lora.
# Tu peux remplacer cette URL par ta LoRA serveur si besoin.
DEFAULT_LORA_URL = (
    "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/"
    "loras/Ltx2.3-Licon-VBVR-I2V-96000-R32.safetensors"
)
DEFAULT_LORA_MULTIPLIER = "1"

# Interface web intégrée.
# La page de monitoring est servie directement par FastAPI.
# Accès :
#   http://IP_DU_SERVEUR:7861/monitor?token=TON_TOKEN
#
# Tu peux mettre un token différent si tu veux séparer l'accès API et l'accès humain.
MONITOR_TOKEN = API_TOKEN
MONITOR_TITLE = "Wan2GP Queue Monitor V2"
MONITOR_AUTO_REFRESH_SECONDS = 5

# Modes API supportés.
# Les anciens fichiers JSON séparés sont remplacés par cette table de contrôle.
MODE_CONTROLS = {
    "t2v": {
        "public_mode": "text_to_video",
        "requires_image_start": False,
        "requires_image_end": False,
        "requires_audio": False,
        "uses_lora": False,
        "image_prompt_type": "",
        "audio_prompt_type": "",
        "multi_prompts_gen_type": "G",
        "prompt_enhancer": "",
    },
    "i2v": {
        "public_mode": "image_to_video",
        "requires_image_start": True,
        "requires_image_end": False,
        "requires_audio": False,
        "uses_lora": False,
        "image_prompt_type": "S",
        "audio_prompt_type": "",
        "multi_prompts_gen_type": "FG",
        "prompt_enhancer": "",
    },
    "i2v_end": {
        "public_mode": "image_to_video_with_end_image",
        "requires_image_start": True,
        "requires_image_end": True,
        "requires_audio": False,
        "uses_lora": False,
        "image_prompt_type": "SE",
        "audio_prompt_type": "",
        "multi_prompts_gen_type": "FG",
        "prompt_enhancer": "T",
    },
    "s2v": {
        "public_mode": "sound_to_video",
        "requires_image_start": False,
        "requires_image_end": False,
        "requires_audio": True,
        "uses_lora": False,
        "image_prompt_type": "",
        "audio_prompt_type": "A",
        "multi_prompts_gen_type": "FG",
        "prompt_enhancer": "T",
    },
    "s2v_i2v": {
        "public_mode": "sound_to_video_with_reference_image",
        "requires_image_start": True,
        "requires_image_end": False,
        "requires_audio": True,
        "uses_lora": False,
        "image_prompt_type": "S",
        "audio_prompt_type": "A",
        "multi_prompts_gen_type": "FG",
        "prompt_enhancer": "T",
    },
    "s2v_i2v_lora": {
        "public_mode": "sound_to_video_with_reference_image_and_lora",
        "requires_image_start": True,
        "requires_image_end": False,
        "requires_audio": True,
        "uses_lora": True,
        "image_prompt_type": "S",
        "audio_prompt_type": "A",
        "multi_prompts_gen_type": "FG",
        "prompt_enhancer": "T",
    },
}

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# HELPERS
# =========================================================

def now_iso() -> str:
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
    - sinon utilise X-Real-IP si présent
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


def validate_mode(mode: str):
    if mode not in MODE_CONTROLS:
        allowed = ", ".join(MODE_CONTROLS.keys())
        raise ValueError(f"Mode inconnu : {mode}. Modes acceptés : {allowed}")


def load_universal_template_settings(template_file: Path) -> dict:
    if not template_file.exists():
        raise RuntimeError(f"Template universel introuvable : {template_file}")

    with open(template_file, "r", encoding="utf-8") as f:
        exported = json.load(f)

    if not isinstance(exported, list) or not exported:
        raise RuntimeError(f"Template universel invalide : {template_file}")

    first = exported[0]

    if not isinstance(first, dict) or "params" not in first:
        raise RuntimeError(f"Le template universel ne contient pas 'params' : {template_file}")

    settings = first["params"]

    if not isinstance(settings, dict):
        raise RuntimeError(f"Le champ 'params' du template universel n'est pas un objet JSON : {template_file}")

    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE

    return settings


UNIVERSAL_TEMPLATE_SETTINGS = load_universal_template_settings(TEMPLATE_FILE)


def compute_video_length(duration_seconds: int, fps: int) -> int:
    # Wan2GP attend souvent un nombre de frames sous la forme durée * fps + 1.
    return int(duration_seconds * fps) + 1


def base_settings() -> dict:
    """
    Retourne une copie profonde du template universel.

    Le template n'est jamais modifié directement en mémoire.
    Chaque job reçoit sa propre copie, puis les contrôles de mode sont appliqués.
    """
    settings = copy.deepcopy(UNIVERSAL_TEMPLATE_SETTINGS)

    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE
    settings["client_id"] = ""
    settings["output_filename"] = ""

    return settings


def reset_control_fields(settings: dict) -> dict:
    """
    Nettoie tous les champs qui peuvent provoquer un effet de bord entre les modes.

    Cette fonction est volontairement stricte :
    - pas d'image résiduelle sur un t2v
    - pas d'audio résiduel sur un i2v
    - pas de LoRA résiduelle si le mode ne l'utilise pas
    - pas de source vidéo ou guide multimodal caché
    """
    # Fichiers de référence et guides
    settings["image_start"] = None
    settings["image_end"] = None
    settings["audio_guide"] = None
    settings["audio_guide2"] = None
    settings["custom_guide"] = None
    settings["audio_source"] = None
    settings["video_source"] = None
    settings["video_guide"] = None
    settings["image_guide"] = None
    settings["image_refs"] = None
    settings["frames_positions"] = None

    # Types de prompts et contrôles
    settings["image_prompt_type"] = ""
    settings["audio_prompt_type"] = ""
    settings["video_prompt_type"] = ""
    settings["multi_prompts_gen_type"] = "G"
    settings["multi_images_gen_type"] = 0
    settings["image_mode"] = 0
    settings["mode"] = ""

    # LoRA
    settings["activated_loras"] = []
    settings["loras_multipliers"] = ""

    # Champs de compatibilité conservés neutres
    settings["keep_frames_video_source"] = ""
    settings["keep_frames_video_guide"] = ""
    settings["video_guide_outpainting"] = "#"
    settings["video_guide_outpainting_ratio"] = ""

    return settings


def apply_mode_controls(
    settings: dict,
    mode: str,
    image_start: Path | None = None,
    image_end: Path | None = None,
    audio_guide: Path | None = None,
    lora_url: str | None = None,
    lora_multiplier: str | None = None,
) -> dict:
    """
    Applique la couche de contrôle du mode.

    C'est ici que l'ancien comportement des 6 templates séparés est reproduit :
    - t2v : texte seul
    - i2v : image de départ
    - i2v_end : image de départ + image de fin
    - s2v : audio seul
    - s2v_i2v : audio + image
    - s2v_i2v_lora : audio + image + LoRA
    """
    validate_mode(mode)
    control = MODE_CONTROLS[mode]

    settings = reset_control_fields(settings)

    requires_image_start = control["requires_image_start"]
    requires_image_end = control["requires_image_end"]
    requires_audio = control["requires_audio"]
    uses_lora = control["uses_lora"]

    if requires_image_start and image_start is None:
        raise ValueError(f"Le mode {mode} nécessite une image de départ")

    if requires_image_end and image_end is None:
        raise ValueError(f"Le mode {mode} nécessite une image de fin")

    if requires_audio and audio_guide is None:
        raise ValueError(f"Le mode {mode} nécessite un fichier audio")

    if image_start is not None and not requires_image_start:
        raise ValueError(f"Le mode {mode} ne doit pas recevoir d'image de départ")

    if image_end is not None and not requires_image_end:
        raise ValueError(f"Le mode {mode} ne doit pas recevoir d'image de fin")

    if audio_guide is not None and not requires_audio:
        raise ValueError(f"Le mode {mode} ne doit pas recevoir de fichier audio")

    settings["image_prompt_type"] = control["image_prompt_type"]
    settings["audio_prompt_type"] = control["audio_prompt_type"]
    settings["multi_prompts_gen_type"] = control["multi_prompts_gen_type"]
    settings["prompt_enhancer"] = control["prompt_enhancer"]

    if requires_image_start:
        settings["image_start"] = str(image_start)

    if requires_image_end:
        settings["image_end"] = str(image_end)

    if requires_audio:
        settings["audio_guide"] = str(audio_guide)

    if uses_lora:
        final_lora_url = (lora_url or DEFAULT_LORA_URL or "").strip()
        final_lora_multiplier = (lora_multiplier or DEFAULT_LORA_MULTIPLIER or "1").strip()

        if not final_lora_url:
            raise ValueError(f"Le mode {mode} nécessite une LoRA")

        settings["activated_loras"] = [final_lora_url]
        settings["loras_multipliers"] = final_lora_multiplier
    else:
        settings["activated_loras"] = []
        settings["loras_multipliers"] = ""

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
    lora_url: str | None = None,
    lora_multiplier: str | None = None,
) -> dict:
    validate_common_params(duration_seconds, fps, num_inference_steps)

    settings = base_settings()

    settings["prompt"] = prompt
    settings["negative_prompt"] = negative_prompt or ""

    settings["resolution"] = resolution
    settings["video_length"] = compute_video_length(duration_seconds, fps)
    settings["duration_seconds"] = 0
    settings["force_fps"] = fps
    settings["num_inference_steps"] = num_inference_steps

    settings["seed"] = seed if seed is not None else random.randint(1, 2_147_483_647)

    settings["model_type"] = FIXED_MODEL_TYPE
    settings["base_model_type"] = FIXED_BASE_MODEL_TYPE

    settings = apply_mode_controls(
        settings=settings,
        mode=mode,
        image_start=image_start,
        image_end=image_end,
        audio_guide=audio_guide,
        lora_url=lora_url,
        lora_multiplier=lora_multiplier,
    )

    return settings


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="Wan2GP LAN API",
    version="2.2",
    description="API LAN pour générer des vidéos via Wan2GP avec un template universel",
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
# MONITOR WEB HTML
# =========================================================

def check_monitor_access(
    authorization: str | None = None,
    token: str | None = None,
):
    """
    Autorise l'accès au monitor de deux façons :
    - header Authorization: Bearer ...
    - paramètre d'URL ?token=...

    Pour un navigateur, le paramètre token est le plus pratique.
    """
    expected_header = f"Bearer {MONITOR_TOKEN}"

    if authorization == expected_header:
        return

    if token == MONITOR_TOKEN:
        return

    raise HTTPException(status_code=401, detail="Unauthorized monitor access")


def h(value) -> str:
    return html.escape(str(value), quote=True)


def status_badge_class(status: str) -> str:
    return {
        "queued": "badge queued",
        "running": "badge running",
        "completed": "badge completed",
        "failed": "badge failed",
    }.get(status, "badge unknown")


def mode_badge_class(api_mode: str) -> str:
    return {
        "t2v": "mode-badge t2v",
        "i2v": "mode-badge i2v",
        "i2v_end": "mode-badge i2v-end",
        "s2v": "mode-badge s2v",
        "s2v_i2v": "mode-badge s2v-i2v",
        "s2v_i2v_lora": "mode-badge s2v-i2v-lora",
    }.get(api_mode, "mode-badge unknown")


def format_mode_label(job: dict) -> str:
    api_mode = job.get("api_mode", "")

    return {
        "t2v": "Texte → Vidéo",
        "i2v": "Image → Vidéo",
        "i2v_end": "Image début + fin",
        "s2v": "Audio → Vidéo",
        "s2v_i2v": "Audio + Image",
        "s2v_i2v_lora": "Audio + Image + LoRA",
    }.get(api_mode, job.get("mode", "Mode inconnu"))


def parse_iso_datetime(value: str | None):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def format_date_value(value: str | None) -> str:
    dt = parse_iso_datetime(value)

    if not dt:
        return str(value or "")

    return dt.strftime("%d/%m/%Y %H:%M:%S")


def format_duration_seconds(seconds: int | float | None) -> str:
    if seconds is None:
        return ""

    seconds = int(seconds)

    if seconds < 0:
        return ""

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"

    if minutes > 0:
        return f"{minutes}m {secs:02d}s"

    return f"{secs}s"


def generation_duration(job: dict) -> str:
    started = job.get("started_at")
    finished = job.get("finished_at")

    started_dt = parse_iso_datetime(started)

    if not started_dt:
        return ""

    if job.get("status") == "running":
        diff = datetime.now() - started_dt
        return f"{format_duration_seconds(diff.total_seconds())} en cours"

    finished_dt = parse_iso_datetime(finished)

    if not finished_dt:
        return ""

    diff = finished_dt - started_dt
    return format_duration_seconds(diff.total_seconds())


def first_download_url(job: dict) -> str | None:
    download_urls = job.get("download_urls")

    if not isinstance(download_urls, list) or not download_urls:
        return None

    return download_urls[0]


def is_active_job(job: dict) -> bool:
    return job.get("status") in ("queued", "running")


def is_completed_job(job: dict) -> bool:
    return job.get("status") == "completed"


def is_failed_job(job: dict) -> bool:
    return job.get("status") == "failed"


def get_requester_ip_from_job(job: dict) -> str:
    return (
        job.get("requester_ip")
        or job.get("client_ip")
        or job.get("remote_addr")
        or ""
    )


def basename_or_empty(value) -> str:
    if not value:
        return ""

    return Path(str(value)).name


def prompt_excerpt(text: str | None, limit: int = 500) -> str:
    text = str(text or "")

    if len(text) > limit:
        return text[:limit] + "..."

    return text


def count_by_mode(jobs_list: list[dict], mode: str) -> int:
    return sum(1 for job in jobs_list if job.get("api_mode") == mode)


def build_monitor_download_href(job: dict, download_url: str | None, token: str | None) -> str | None:
    if not download_url:
        return None

    job_id = job.get("job_id", "")
    filename = Path(str(download_url)).name

    if not job_id or not filename:
        return None

    token_to_use = token or MONITOR_TOKEN

    return (
        f"/monitor/download/{quote(str(job_id))}/{quote(filename)}"
        f"?token={quote(str(token_to_use))}"
    )


def render_error_block(title: str, message: str) -> str:
    return f"""
    <div class="error">
        <strong>{h(title)}</strong><br>
        {h(message)}
    </div>
    """


def render_input_list(job: dict) -> str:
    rows = []

    if job.get("input_image"):
        rows.append(f'Image : <span class="mono">{h(basename_or_empty(job.get("input_image")))}</span>')

    if job.get("input_image_start"):
        rows.append(f'Début : <span class="mono">{h(basename_or_empty(job.get("input_image_start")))}</span>')

    if job.get("input_image_end"):
        rows.append(f'Fin : <span class="mono">{h(basename_or_empty(job.get("input_image_end")))}</span>')

    if job.get("input_audio"):
        rows.append(f'Audio : <span class="mono">{h(basename_or_empty(job.get("input_audio")))}</span>')

    activated_loras = job.get("activated_loras")
    if isinstance(activated_loras, list) and activated_loras:
        lora_rows = "".join(
            f'<div class="mono">{h(basename_or_empty(lora))}</div>'
            for lora in activated_loras
        )
        rows.append(f"LoRA : {lora_rows}")
        rows.append(f'Multiplier : <span class="mono">{h(job.get("loras_multipliers", ""))}</span>')

    if not rows:
        return '<span class="small">Aucune entrée fichier</span>'

    return "".join(f"<div>{row}</div>" for row in rows)


def render_errors(job: dict) -> str:
    errors = job.get("errors")

    if not errors:
        return ""

    try:
        errors_json = json.dumps(errors, ensure_ascii=False, indent=2)
    except Exception:
        errors_json = str(errors)

    return f"""
    <div class="small ko" style="margin-top: 8px;">
        Erreurs :
        <pre>{h(errors_json)}</pre>
    </div>
    """


def render_jobs_table(jobs_list: list[dict], token: str | None) -> str:
    if not jobs_list:
        return '<div class="card">Aucun job connu pour le moment.</div>'

    rows = []

    for job in jobs_list:
        status = job.get("status", "unknown")
        api_mode = job.get("api_mode", "")
        progress = float(job.get("progress", 0) or 0)
        progress = max(0, min(100, progress))

        download_url = first_download_url(job)
        download_href = build_monitor_download_href(job, download_url, token)

        real_duration = generation_duration(job)
        requester_ip = get_requester_ip_from_job(job)

        queue_position_html = (
            f'<strong>#{h(job.get("queue_position"))}</strong>'
            if job.get("queue_position") is not None
            else '<span class="small">hors file</span>'
        )

        lora_flag_html = ""
        if job.get("activated_loras"):
            lora_flag_html = '<div class="small warn" style="margin-top: 6px;">LoRA actif</div>'

        requester_html = (
            f'<span class="mono">{h(requester_ip)}</span>'
            if requester_ip
            else """
            <span class="small warn">Non renseignée</span>
            <div class="small">Ajoute requester_ip côté API pour afficher l’IP cliente.</div>
            """
        )

        download_html = '<span class="small">Pas encore prêt</span>'
        if download_href:
            download_html = f"""
            <a class="button-link" href="{h(download_href)}" target="_blank">
                Télécharger MP4
            </a>
            """

        files_html = ""
        files = job.get("files")
        if isinstance(files, list) and files:
            files_html = """
            <div class="small" style="margin-top: 8px;">
            """ + "".join(f'<div class="mono">{h(file)}</div>' for file in files) + """
            </div>
            """

        rows.append(f"""
        <tr>
            <td>
                <span class="{h(status_badge_class(status))}">
                    {h(status)}
                </span>
                <div class="small">{h(job.get("short_status", ""))}</div>
            </td>

            <td>{queue_position_html}</td>

            <td>
                <span class="{h(mode_badge_class(api_mode))}">
                    {h(api_mode or "legacy")}
                </span>
                <div class="small" style="margin-top: 6px;">
                    {h(format_mode_label(job))}
                </div>
                <div class="small">{h(job.get("mode", ""))}</div>
                {lora_flag_html}
            </td>

            <td>
                <div class="progress-wrap">
                    <div class="progress-bar" style="width: {h(progress)}%;"></div>
                </div>
                <div class="progress-text">{h(progress)}%</div>
                <div class="small">
                    Phase : {h(job.get("phase", ""))}<br>
                    Étape : {h(job.get("current_step", ""))}/{h(job.get("total_steps", ""))}<br>
                    Message : {h(job.get("message", ""))}
                </div>
            </td>

            <td>
                <div class="small">
                    Résolution : <strong>{h(job.get("resolution", ""))}</strong><br>
                    Vidéo demandée : <strong>{h(job.get("duration_seconds", ""))}s</strong><br>
                    FPS : <strong>{h(job.get("fps", ""))}</strong><br>
                    Seed : <span class="mono">{h(job.get("seed", ""))}</span><br>
                    Job ID : <span class="mono">{h(job.get("job_id", ""))}</span>
                </div>
            </td>

            <td>{requester_html}</td>

            <td>
                <div class="prompt">
                    {h(prompt_excerpt(job.get("prompt", ""), 500)).replace(chr(10), "<br>")}
                </div>
            </td>

            <td>
                <div class="input-list small">
                    {render_input_list(job)}
                </div>
                {render_errors(job)}
            </td>

            <td>
                <div class="small">
                    Créé : {h(format_date_value(job.get("created_at")))}<br>
                    Début : {h(format_date_value(job.get("started_at")))}<br>
                    Fin : {h(format_date_value(job.get("finished_at")))}<br>
                    MAJ : {h(format_date_value(job.get("updated_at")))}<br>
                    <br>
                    Durée réelle :
                    {"<strong>" + h(real_duration) + "</strong>" if real_duration else '<span class="small">non disponible</span>'}
                </div>
            </td>

            <td>
                {download_html}
                {files_html}
            </td>
        </tr>
        """)

    return f"""
    <table>
        <thead>
            <tr>
                <th>Statut</th>
                <th>Queue</th>
                <th>Type</th>
                <th>Progression</th>
                <th>Demande</th>
                <th>Machine</th>
                <th>Prompt</th>
                <th>Entrées</th>
                <th>Temps</th>
                <th>Résultat</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def render_monitor_page(token: str | None, auto_refresh_seconds: int) -> str:
    with jobs_lock:
        jobs_list = [copy.deepcopy(j) for j in jobs.values()]

    jobs_list.sort(key=lambda x: x.get("sequence", 0), reverse=True)
    jobs_list = [add_runtime_fields(j) for j in jobs_list]

    active_jobs = [job for job in jobs_list if is_active_job(job)]
    completed_jobs = [job for job in jobs_list if is_completed_job(job)]
    failed_jobs = [job for job in jobs_list if is_failed_job(job)]

    mode_counts = {
        "t2v": count_by_mode(jobs_list, "t2v"),
        "i2v": count_by_mode(jobs_list, "i2v"),
        "i2v_end": count_by_mode(jobs_list, "i2v_end"),
        "s2v": count_by_mode(jobs_list, "s2v"),
        "s2v_i2v": count_by_mode(jobs_list, "s2v_i2v"),
        "s2v_i2v_lora": count_by_mode(jobs_list, "s2v_i2v_lora"),
    }

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    model_templates_or_template = str(TEMPLATE_FILE)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>{h(MONITOR_TITLE)}</title>
    <meta http-equiv="refresh" content="{h(auto_refresh_seconds)}">
    <style>
        :root {{
            --bg: #0f1117;
            --panel: #171a23;
            --panel2: #202431;
            --panel3: #11141c;
            --text: #f3f4f6;
            --muted: #9ca3af;
            --border: #2d3342;

            --queued: #f59e0b;
            --running: #38bdf8;
            --completed: #22c55e;
            --failed: #ef4444;
            --unknown: #94a3b8;

            --t2v: #a78bfa;
            --i2v: #60a5fa;
            --i2v-end: #34d399;
            --s2v: #f472b6;
            --s2v-i2v: #fbbf24;
            --s2v-i2v-lora: #fb7185;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            padding: 24px;
            background: radial-gradient(circle at top, #1d2230, var(--bg));
            color: var(--text);
            font-family: Arial, Helvetica, sans-serif;
        }}

        h1 {{
            margin: 0 0 8px;
            font-size: 28px;
        }}

        .subtitle {{
            color: var(--muted);
            margin-bottom: 24px;
            line-height: 1.5;
        }}

        .top-grid {{
            display: grid;
            grid-template-columns: repeat(5, minmax(150px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}

        .mode-grid {{
            display: grid;
            grid-template-columns: repeat(6, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }}

        .card {{
            background: rgba(23, 26, 35, 0.92);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 12px 28px rgba(0,0,0,0.25);
        }}

        .card-title {{
            color: var(--muted);
            font-size: 13px;
            margin-bottom: 8px;
        }}

        .card-value {{
            font-size: 26px;
            font-weight: bold;
        }}

        .section {{
            margin-top: 28px;
        }}

        .section h2 {{
            font-size: 20px;
            margin-bottom: 12px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(23, 26, 35, 0.92);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
        }}

        th, td {{
            padding: 12px 10px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
            text-align: left;
            font-size: 14px;
        }}

        th {{
            background: var(--panel2);
            color: #d1d5db;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            position: sticky;
            top: 0;
            z-index: 2;
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        tr:hover td {{
            background: rgba(255,255,255,0.025);
        }}

        .badge,
        .mode-badge {{
            display: inline-block;
            padding: 5px 9px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: bold;
            color: #050505;
            white-space: nowrap;
        }}

        .badge.queued {{
            background: var(--queued);
        }}

        .badge.running {{
            background: var(--running);
        }}

        .badge.completed {{
            background: var(--completed);
        }}

        .badge.failed {{
            background: var(--failed);
            color: white;
        }}

        .badge.unknown {{
            background: var(--unknown);
        }}

        .mode-badge.t2v {{
            background: var(--t2v);
        }}

        .mode-badge.i2v {{
            background: var(--i2v);
        }}

        .mode-badge.i2v-end {{
            background: var(--i2v-end);
        }}

        .mode-badge.s2v {{
            background: var(--s2v);
        }}

        .mode-badge.s2v-i2v {{
            background: var(--s2v-i2v);
        }}

        .mode-badge.s2v-i2v-lora {{
            background: var(--s2v-i2v-lora);
            color: #111827;
        }}

        .mode-badge.unknown {{
            background: var(--unknown);
        }}

        .progress-wrap {{
            width: 160px;
            height: 12px;
            background: #0b0d12;
            border-radius: 999px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}

        .progress-bar {{
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #22c55e);
            width: 0%;
        }}

        .progress-text {{
            color: var(--muted);
            font-size: 12px;
            margin-top: 4px;
        }}

        .prompt {{
            max-width: 460px;
            color: #e5e7eb;
            line-height: 1.35;
            white-space: normal;
        }}

        .small {{
            color: var(--muted);
            font-size: 12px;
            line-height: 1.45;
        }}

        .mono {{
            font-family: Consolas, Monaco, monospace;
            font-size: 12px;
            color: #cbd5e1;
            word-break: break-all;
        }}

        .input-list {{
            margin-top: 6px;
            padding: 8px;
            background: var(--panel3);
            border-radius: 10px;
            border: 1px solid var(--border);
        }}

        .input-list div {{
            margin-bottom: 4px;
        }}

        .input-list div:last-child {{
            margin-bottom: 0;
        }}

        a {{
            color: #93c5fd;
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}

        .button-link {{
            display: inline-block;
            padding: 8px 11px;
            background: #2563eb;
            color: white;
            border-radius: 10px;
            text-decoration: none;
            font-weight: bold;
            font-size: 13px;
        }}

        .button-link:hover {{
            background: #1d4ed8;
            text-decoration: none;
        }}

        .error {{
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.45);
            color: #fecaca;
            padding: 16px;
            border-radius: 14px;
            margin-bottom: 20px;
        }}

        .ok {{
            color: #86efac;
        }}

        .ko {{
            color: #fca5a5;
        }}

        .warn {{
            color: #fde68a;
        }}

        .footer {{
            margin-top: 24px;
            color: var(--muted);
            font-size: 12px;
        }}

        pre {{
            white-space: pre-wrap;
            word-break: break-word;
            background: #0b0d12;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 8px;
            color: #fecaca;
        }}

        @media (max-width: 1300px) {{
            .top-grid {{
                grid-template-columns: repeat(2, minmax(160px, 1fr));
            }}

            .mode-grid {{
                grid-template-columns: repeat(2, minmax(140px, 1fr));
            }}

            table {{
                display: block;
                overflow-x: auto;
            }}
        }}
    </style>
</head>
<body>

<h1>{h(MONITOR_TITLE)}</h1>

<div class="subtitle">
    Serveur : <span class="mono">FastAPI intégré sur port 7861</span><br>
    Rafraîchissement automatique : {h(auto_refresh_seconds)} s |
    Page générée à {h(generated_at)}
</div>

<div class="top-grid">
    <div class="card">
        <div class="card-title">API</div>
        <div class="card-value ok">OK</div>
    </div>

    <div class="card">
        <div class="card-title">Total jobs</div>
        <div class="card-value">{h(len(jobs_list))}</div>
    </div>

    <div class="card">
        <div class="card-title">Jobs actifs</div>
        <div class="card-value">{h(len(active_jobs))}</div>
    </div>

    <div class="card">
        <div class="card-title">Terminés</div>
        <div class="card-value">{h(len(completed_jobs))}</div>
    </div>

    <div class="card">
        <div class="card-title">Échecs</div>
        <div class="card-value">{h(len(failed_jobs))}</div>
    </div>
</div>

<div class="mode-grid">
    <div class="card">
        <div class="card-title">t2v</div>
        <div class="card-value">{h(mode_counts["t2v"])}</div>
    </div>
    <div class="card">
        <div class="card-title">i2v</div>
        <div class="card-value">{h(mode_counts["i2v"])}</div>
    </div>
    <div class="card">
        <div class="card-title">i2v_end</div>
        <div class="card-value">{h(mode_counts["i2v_end"])}</div>
    </div>
    <div class="card">
        <div class="card-title">s2v</div>
        <div class="card-value">{h(mode_counts["s2v"])}</div>
    </div>
    <div class="card">
        <div class="card-title">s2v_i2v</div>
        <div class="card-value">{h(mode_counts["s2v_i2v"])}</div>
    </div>
    <div class="card">
        <div class="card-title">s2v_i2v_lora</div>
        <div class="card-value">{h(mode_counts["s2v_i2v_lora"])}</div>
    </div>
</div>

<div class="card">
    <div class="card-title">Modèle</div>
    <div>
        <strong>{h(DISPLAY_MODEL_NAME)}</strong><br>
        <span class="mono">{h(FIXED_MODEL_TYPE)}</span>
    </div>
    <div class="small" style="margin-top: 8px;">
        Template universel :
        <span class="mono">{h(model_templates_or_template)}</span>
    </div>
</div>

<div class="section">
    <h2>File d’attente et historique</h2>
    {render_jobs_table(jobs_list, token)}
</div>

<div class="footer">
    Wan2GP Queue Monitor intégré |
    Page générée à {h(generated_at)} |
    Jobs en mémoire uniquement côté API.
</div>

</body>
</html>"""


# =========================================================
# ROUTES GENERALES
# =========================================================


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/monitor")


@app.get("/monitor", response_class=HTMLResponse)
def monitor_page(
    token: str | None = None,
    refresh: int = MONITOR_AUTO_REFRESH_SECONDS,
    authorization: str | None = Header(default=None),
):
    check_monitor_access(authorization=authorization, token=token)

    refresh = max(1, min(3600, int(refresh)))

    html_body = render_monitor_page(
        token=token,
        auto_refresh_seconds=refresh,
    )

    return HTMLResponse(content=html_body)


@app.get("/ui", response_class=HTMLResponse)
def monitor_page_alias(
    token: str | None = None,
    refresh: int = MONITOR_AUTO_REFRESH_SECONDS,
    authorization: str | None = Header(default=None),
):
    return monitor_page(
        token=token,
        refresh=refresh,
        authorization=authorization,
    )


@app.get("/monitor/download/{job_id}/{filename}")
def monitor_download(
    job_id: str,
    filename: str,
    token: str | None = None,
    authorization: str | None = Header(default=None),
):
    check_monitor_access(authorization=authorization, token=token)

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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "wan2gp-api",
        "version": "2.2",
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "template_file": str(TEMPLATE_FILE),
        "monitor_url": "/monitor",
        "modes": list(MODE_CONTROLS.keys()),
    }


@app.get("/model")
def model_info(authorization: str | None = Header(default=None)):
    check_auth(authorization)

    return {
        "fixed_model": True,
        "display_name": DISPLAY_MODEL_NAME,
        "model_type": FIXED_MODEL_TYPE,
        "base_model_type": FIXED_BASE_MODEL_TYPE,
        "template_file": str(TEMPLATE_FILE),
        "default_resolution": DEFAULT_RESOLUTION,
        "default_fps": DEFAULT_FPS,
        "default_duration_seconds": DEFAULT_DURATION_SECONDS,
        "default_steps": DEFAULT_STEPS,
        "modes": {
            mode: {
                "public_mode": control["public_mode"],
                "requires_image_start": control["requires_image_start"],
                "requires_image_end": control["requires_image_end"],
                "requires_audio": control["requires_audio"],
                "uses_lora": control["uses_lora"],
                "image_prompt_type": control["image_prompt_type"],
                "audio_prompt_type": control["audio_prompt_type"],
                "multi_prompts_gen_type": control["multi_prompts_gen_type"],
                "prompt_enhancer": control["prompt_enhancer"],
            }
            for mode, control in MODE_CONTROLS.items()
        },
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
# ROUTES GENERATION V2.2
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

    public_mode = MODE_CONTROLS["t2v"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=req.prompt,
        settings=settings,
        duration_seconds=req.duration_seconds,
        fps=req.fps,
        resolution=req.resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "t2v",
            "template_file": str(TEMPLATE_FILE),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": public_mode,
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

    public_mode = MODE_CONTROLS["i2v"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "i2v",
            "template_file": str(TEMPLATE_FILE),
            "input_image": str(image_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": public_mode,
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

    public_mode = MODE_CONTROLS["i2v_end"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "i2v_end",
            "template_file": str(TEMPLATE_FILE),
            "input_image_start": str(image_start_path),
            "input_image_end": str(image_end_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": public_mode,
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

    public_mode = MODE_CONTROLS["s2v"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v",
            "template_file": str(TEMPLATE_FILE),
            "input_audio": str(audio_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": public_mode,
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

    public_mode = MODE_CONTROLS["s2v_i2v"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v_i2v",
            "template_file": str(TEMPLATE_FILE),
            "input_image": str(image_path),
            "input_audio": str(audio_path),
        },
    )

    start_generation_thread(job_id, settings)

    return {
        "job_id": job_id,
        "status": "queued",
        "mode": public_mode,
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
    lora_url: str | None = Form(None),
    lora_multiplier: str | None = Form(None),
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
        lora_url=lora_url,
        lora_multiplier=lora_multiplier,
    )

    public_mode = MODE_CONTROLS["s2v_i2v_lora"]["public_mode"]

    create_job_record(
        job_id=job_id,
        mode=public_mode,
        prompt=prompt,
        settings=settings,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        requester_info=requester_info,
        extra={
            "api_mode": "s2v_i2v_lora",
            "template_file": str(TEMPLATE_FILE),
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
        "mode": public_mode,
        "api_mode": "s2v_i2v_lora",
        "requester_ip": requester_info.get("requester_ip", ""),
        "status_url": f"/jobs/{job_id}",
        "activated_loras": settings.get("activated_loras", []),
        "loras_multipliers": settings.get("loras_multipliers", ""),
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
