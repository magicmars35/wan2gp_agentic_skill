"""
Wan2GP Video Skill for OpenClaw, Hermes, and coding agents.

This module talks to the Wan2GP LAN API server.
It supports the universal-template Wan2GP API server with built-in monitor page.

Main features:
- Health, model and job monitoring
- Text to video
- Image to video
- Start image + end image to video
- Sound or audio to video
- Sound or audio + reference image to video
- Sound or audio + reference image + optional LoRA to video
- Automatic mode selection
- Job submission without waiting
- Job waiting with progress formatting
- MP4 download
- Monitor URL helper

Recommended environment variables:
- WAN2GP_URL=http://192.168.1.53:7861
- WAN2GP_TOKEN=your-secret-token
"""

from __future__ import annotations

import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple
from urllib.parse import quote

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================================================
# CONFIG
# =========================================================

WAN2GP_URL = os.getenv("WAN2GP_URL", "http://192.168.1.53:7861").rstrip("/")
WAN2GP_TOKEN = os.getenv("WAN2GP_TOKEN", "my-super-token-to-change")

DEFAULT_RESOLUTION = os.getenv("WAN2GP_DEFAULT_RESOLUTION", "1280x720")
DEFAULT_FPS = int(os.getenv("WAN2GP_DEFAULT_FPS", "24"))
DEFAULT_DURATION_SECONDS = int(os.getenv("WAN2GP_DEFAULT_DURATION_SECONDS", "3"))
DEFAULT_STEPS = int(os.getenv("WAN2GP_DEFAULT_STEPS", "8"))
DEFAULT_POLL_SECONDS = int(os.getenv("WAN2GP_DEFAULT_POLL_SECONDS", "5"))

MAX_DURATION_SECONDS = int(os.getenv("WAN2GP_MAX_DURATION_SECONDS", "60"))
MAX_FPS = int(os.getenv("WAN2GP_MAX_FPS", "60"))
MAX_STEPS = int(os.getenv("WAN2GP_MAX_STEPS", "100"))

DEFAULT_REQUEST_TIMEOUT = int(os.getenv("WAN2GP_REQUEST_TIMEOUT", "60"))
DEFAULT_UPLOAD_TIMEOUT = int(os.getenv("WAN2GP_UPLOAD_TIMEOUT", "180"))
DEFAULT_DOWNLOAD_TIMEOUT = int(os.getenv("WAN2GP_DOWNLOAD_TIMEOUT", "600"))

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}

VideoMode = Literal[
    "t2v",
    "i2v",
    "i2v_end",
    "s2v",
    "s2v_i2v",
    "s2v_i2v_lora",
]

MODE_LABELS: Dict[str, str] = {
    "t2v": "Texte vers vidéo",
    "i2v": "Image vers vidéo",
    "i2v_end": "Image début + fin vers vidéo",
    "s2v": "Audio vers vidéo",
    "s2v_i2v": "Audio + image vers vidéo",
    "s2v_i2v_lora": "Audio + image + LoRA vers vidéo",
}

MODE_ENDPOINTS: Dict[str, str] = {
    "t2v": "/generate/t2v",
    "i2v": "/generate/i2v",
    "i2v_end": "/generate/i2v_end",
    "s2v": "/generate/s2v",
    "s2v_i2v": "/generate/s2v_i2v",
    "s2v_i2v_lora": "/generate/s2v_i2v_lora",
}


# =========================================================
# HTTP SESSION
# =========================================================

def _build_session() -> Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_SESSION = _build_session()


# =========================================================
# HEADERS AND URLS
# =========================================================

def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {WAN2GP_TOKEN}"}


def _json_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WAN2GP_TOKEN}",
        "Content-Type": "application/json",
    }


def _url(endpoint: str) -> str:
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return f"{WAN2GP_URL}{endpoint}"


def monitor_url() -> str:
    """
    Returns the built-in browser monitor URL.
    The monitor endpoint accepts token query auth for simple browser usage.
    """
    return f"{WAN2GP_URL}/monitor?token={quote(WAN2GP_TOKEN)}"


def ui_url() -> str:
    """
    Alias of monitor_url().
    """
    return f"{WAN2GP_URL}/ui?token={quote(WAN2GP_TOKEN)}"


# =========================================================
# ERRORS AND RESPONSE HANDLING
# =========================================================

class Wan2GPError(RuntimeError):
    """Base error for Wan2GP skill failures."""


class Wan2GPJobFailed(Wan2GPError):
    """Raised when a Wan2GP job ends with status failed."""


def _safe_json(response: Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _raise_for_response(response: Response) -> None:
    if 200 <= response.status_code < 300:
        return

    body = _safe_json(response)
    raise Wan2GPError(
        f"Wan2GP HTTP {response.status_code} on {response.url}: {body}"
    )


def _request_json(
    method: str,
    endpoint: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = _SESSION.request(
        method=method,
        url=_url(endpoint),
        headers=headers,
        timeout=timeout,
        **kwargs,
    )
    _raise_for_response(response)
    data = _safe_json(response)
    if not isinstance(data, dict):
        raise Wan2GPError(f"Réponse JSON inattendue depuis {endpoint}: {data}")
    return data


# =========================================================
# VALIDATION HELPERS
# =========================================================

def _validate_prompt(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if len(prompt) < 3:
        raise ValueError("prompt doit contenir au moins 3 caractères.")
    return prompt


def _validate_common_params(
    duration_seconds: int,
    fps: int,
    resolution: str,
    num_inference_steps: int,
) -> None:
    if duration_seconds < 1 or duration_seconds > MAX_DURATION_SECONDS:
        raise ValueError(f"duration_seconds doit être entre 1 et {MAX_DURATION_SECONDS}.")

    if fps < 1 or fps > MAX_FPS:
        raise ValueError(f"fps doit être entre 1 et {MAX_FPS}.")

    if num_inference_steps < 1 or num_inference_steps > MAX_STEPS:
        raise ValueError(f"num_inference_steps doit être entre 1 et {MAX_STEPS}.")

    if not resolution or "x" not in resolution.lower():
        raise ValueError("resolution doit être au format largeurxhauteur, exemple 1280x720.")


def _ensure_file_exists(file_path: str | Path, label: str) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{label} introuvable : {path}")
    if not path.is_file():
        raise FileNotFoundError(f"{label} n'est pas un fichier : {path}")
    return path


def _validate_extension(path: Path, allowed: Iterable[str], label: str) -> None:
    suffix = path.suffix.lower()
    if suffix not in set(allowed):
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Extension non acceptée pour {label}: {suffix}. Accepté : {allowed_text}")


def _ensure_image(file_path: str | Path, label: str = "Image") -> Path:
    path = _ensure_file_exists(file_path, label)
    _validate_extension(path, ALLOWED_IMAGE_EXTENSIONS, label)
    return path


def _ensure_audio(file_path: str | Path, label: str = "Audio") -> Path:
    path = _ensure_file_exists(file_path, label)
    _validate_extension(path, ALLOWED_AUDIO_EXTENSIONS, label)
    return path


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _base_form_data(
    prompt: str,
    duration_seconds: int,
    fps: int,
    resolution: str,
    num_inference_steps: int,
    seed: Optional[int],
    negative_prompt: Optional[str],
) -> Dict[str, str]:
    _validate_common_params(duration_seconds, fps, resolution, num_inference_steps)

    data = {
        "prompt": _validate_prompt(prompt),
        "duration_seconds": str(duration_seconds),
        "fps": str(fps),
        "resolution": resolution,
        "num_inference_steps": str(num_inference_steps),
    }

    if seed is not None:
        data["seed"] = str(seed)

    if negative_prompt:
        data["negative_prompt"] = negative_prompt

    return data


def choose_mode(
    *,
    mode: Optional[str] = None,
    image_path: Optional[str] = None,
    image_start_path: Optional[str] = None,
    image_end_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    use_lora: bool = False,
) -> VideoMode:
    """
    Chooses a generation mode from explicit mode or provided files.
    Explicit mode always wins.
    """
    if mode:
        if mode not in MODE_ENDPOINTS:
            allowed = ", ".join(MODE_ENDPOINTS)
            raise ValueError(f"mode invalide : {mode}. Modes acceptés : {allowed}")
        return mode  # type: ignore[return-value]

    has_image = bool(image_path)
    has_start = bool(image_start_path)
    has_end = bool(image_end_path)
    has_audio = bool(audio_path)

    if has_start or has_end:
        if not has_start or not has_end:
            raise ValueError("image_start_path et image_end_path doivent être fournis ensemble pour i2v_end.")
        if has_audio:
            raise ValueError("Le mode image_start + image_end + audio n'est pas supporté par cette API.")
        return "i2v_end"

    if has_audio and has_image:
        return "s2v_i2v_lora" if use_lora else "s2v_i2v"

    if has_audio:
        return "s2v"

    if has_image:
        return "i2v"

    return "t2v"


# =========================================================
# BASIC API
# =========================================================

def health() -> Dict[str, Any]:
    """Checks that the Wan2GP server responds."""
    return _request_json("GET", "/health", timeout=30)


def model_info() -> Dict[str, Any]:
    """Returns model, universal template and mode information from the server."""
    return _request_json("GET", "/model", headers=_auth_headers(), timeout=30)


def list_jobs() -> Dict[str, Any]:
    """Lists jobs known by the server. Jobs are stored in server memory."""
    return _request_json("GET", "/jobs", headers=_auth_headers(), timeout=30)


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Returns detailed status for one job."""
    if not job_id:
        raise ValueError("job_id est obligatoire.")
    return _request_json("GET", f"/jobs/{job_id}", headers=_auth_headers(), timeout=30)


def active_jobs() -> List[Dict[str, Any]]:
    """Returns queued and running jobs sorted by queue order as reported by the server."""
    jobs = list_jobs().get("jobs", [])
    active = [job for job in jobs if job.get("status") in {"queued", "running"}]
    return sorted(active, key=lambda j: (j.get("queue_position") is None, j.get("queue_position") or 999999))


def format_job_status(job: Dict[str, Any]) -> str:
    """Formats one job status for chat, logs, Discord, Telegram or WhatsApp."""
    status = job.get("status", "unknown")
    short_status = job.get("short_status", "?")
    queue_position = job.get("queue_position")
    progress = job.get("progress", 0)
    phase = job.get("phase", "")
    current_step = job.get("current_step")
    total_steps = job.get("total_steps")
    message = job.get("message", "")
    api_mode = job.get("api_mode") or job.get("mode") or "unknown"
    job_id = job.get("job_id", "")

    queue_text = "hors file" if queue_position is None else f"#{queue_position}"
    step_text = "" if current_step is None and total_steps is None else f"\nÉtape : {current_step}/{total_steps}"

    return (
        f"Job : {job_id}\n"
        f"Mode : {api_mode}\n"
        f"Statut : {status} ({short_status})\n"
        f"Position file : {queue_text}\n"
        f"Progression : {progress}%\n"
        f"Phase : {phase}"
        f"{step_text}\n"
        f"Message : {message}"
    )


def print_job_status(job: Dict[str, Any]) -> None:
    print(format_job_status(job))


# =========================================================
# SUBMIT HELPERS
# =========================================================

def _post_multipart(
    endpoint: str,
    data: Dict[str, str],
    files: Dict[str, Tuple[str, Any, str]],
    timeout: int = DEFAULT_UPLOAD_TIMEOUT,
) -> Dict[str, Any]:
    response = _SESSION.post(
        _url(endpoint),
        data=data,
        files=files,
        headers=_auth_headers(),
        timeout=timeout,
    )
    _raise_for_response(response)
    result = _safe_json(response)
    if not isinstance(result, dict):
        raise Wan2GPError(f"Réponse inattendue depuis {endpoint}: {result}")
    return result


def _submit_json(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request_json(
        "POST",
        endpoint,
        json=payload,
        headers=_json_headers(),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )


# =========================================================
# SUBMIT FUNCTIONS
# =========================================================

def submit_text_to_video(
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Submits text to video and returns immediately with job_id."""
    _validate_common_params(duration_seconds, fps, resolution, num_inference_steps)

    payload: Dict[str, Any] = {
        "prompt": _validate_prompt(prompt),
        "duration_seconds": duration_seconds,
        "fps": fps,
        "resolution": resolution,
        "num_inference_steps": num_inference_steps,
    }

    if seed is not None:
        payload["seed"] = seed

    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    return _submit_json("/generate/t2v", payload)


def submit_image_to_video(
    image_path: str,
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Submits image to video and returns immediately with job_id."""
    image_file = _ensure_image(image_path, "Image")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    with open(image_file, "rb") as image_handle:
        files = {
            "image": (image_file.name, image_handle, _guess_mime(image_file)),
        }
        return _post_multipart("/generate/i2v", data=data, files=files)


def submit_image_to_video_with_end_image(
    image_start_path: str,
    image_end_path: str,
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Submits start image + end image to video and returns immediately with job_id."""
    image_start_file = _ensure_image(image_start_path, "Image de début")
    image_end_file = _ensure_image(image_end_path, "Image de fin")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    with open(image_start_file, "rb") as start_handle, open(image_end_file, "rb") as end_handle:
        files = {
            "image_start": (image_start_file.name, start_handle, _guess_mime(image_start_file)),
            "image_end": (image_end_file.name, end_handle, _guess_mime(image_end_file)),
        }
        return _post_multipart("/generate/i2v_end", data=data, files=files)


def submit_sound_to_video(
    audio_path: str,
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Submits audio to video and returns immediately with job_id."""
    audio_file = _ensure_audio(audio_path, "Audio")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    with open(audio_file, "rb") as audio_handle:
        files = {
            "audio": (audio_file.name, audio_handle, _guess_mime(audio_file)),
        }
        return _post_multipart("/generate/s2v", data=data, files=files)


def submit_sound_to_video_with_image(
    image_path: str,
    audio_path: str,
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Submits audio + reference image to video and returns immediately with job_id."""
    image_file = _ensure_image(image_path, "Image")
    audio_file = _ensure_audio(audio_path, "Audio")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    with open(image_file, "rb") as image_handle, open(audio_file, "rb") as audio_handle:
        files = {
            "image": (image_file.name, image_handle, _guess_mime(image_file)),
            "audio": (audio_file.name, audio_handle, _guess_mime(audio_file)),
        }
        return _post_multipart("/generate/s2v_i2v", data=data, files=files)


def submit_sound_to_video_with_image_and_lora(
    image_path: str,
    audio_path: str,
    prompt: str,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    lora_url: Optional[str] = None,
    lora_multiplier: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submits audio + reference image + LoRA to video and returns immediately with job_id.
    If lora_url is omitted, the server default LoRA is used.
    """
    image_file = _ensure_image(image_path, "Image")
    audio_file = _ensure_audio(audio_path, "Audio")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    if lora_url:
        data["lora_url"] = lora_url

    if lora_multiplier:
        data["lora_multiplier"] = lora_multiplier

    with open(image_file, "rb") as image_handle, open(audio_file, "rb") as audio_handle:
        files = {
            "image": (image_file.name, image_handle, _guess_mime(image_file)),
            "audio": (audio_file.name, audio_handle, _guess_mime(audio_file)),
        }
        return _post_multipart("/generate/s2v_i2v_lora", data=data, files=files)


# =========================================================
# GENERIC SUBMISSION
# =========================================================

def submit_video_job(
    prompt: str,
    mode: Optional[str] = None,
    image_path: Optional[str] = None,
    image_start_path: Optional[str] = None,
    image_end_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    use_lora: bool = False,
    lora_url: Optional[str] = None,
    lora_multiplier: Optional[str] = None,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submits a video generation job and returns immediately.

    If mode is omitted, the function chooses the mode from the provided files:
    - prompt only: t2v
    - image_path: i2v
    - image_start_path + image_end_path: i2v_end
    - audio_path: s2v
    - image_path + audio_path: s2v_i2v
    - image_path + audio_path + use_lora: s2v_i2v_lora
    """
    selected_mode = choose_mode(
        mode=mode,
        image_path=image_path,
        image_start_path=image_start_path,
        image_end_path=image_end_path,
        audio_path=audio_path,
        use_lora=use_lora,
    )

    if selected_mode == "t2v":
        return submit_text_to_video(
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    if selected_mode == "i2v":
        if not image_path:
            raise ValueError("image_path est obligatoire en mode i2v.")
        return submit_image_to_video(
            image_path=image_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    if selected_mode == "i2v_end":
        if not image_start_path or not image_end_path:
            raise ValueError("image_start_path et image_end_path sont obligatoires en mode i2v_end.")
        return submit_image_to_video_with_end_image(
            image_start_path=image_start_path,
            image_end_path=image_end_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    if selected_mode == "s2v":
        if not audio_path:
            raise ValueError("audio_path est obligatoire en mode s2v.")
        return submit_sound_to_video(
            audio_path=audio_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    if selected_mode == "s2v_i2v":
        if not image_path or not audio_path:
            raise ValueError("image_path et audio_path sont obligatoires en mode s2v_i2v.")
        return submit_sound_to_video_with_image(
            image_path=image_path,
            audio_path=audio_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    if selected_mode == "s2v_i2v_lora":
        if not image_path or not audio_path:
            raise ValueError("image_path et audio_path sont obligatoires en mode s2v_i2v_lora.")
        return submit_sound_to_video_with_image_and_lora(
            image_path=image_path,
            audio_path=audio_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
            lora_url=lora_url,
            lora_multiplier=lora_multiplier,
        )

    raise ValueError(f"Mode non géré : {selected_mode}")


# =========================================================
# WAIT AND DOWNLOAD
# =========================================================

def wait_for_job(
    job_id: str,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    verbose: bool = False,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Waits for job completion.
    Raises Wan2GPJobFailed on failed jobs.
    Raises TimeoutError if timeout_seconds is reached.
    """
    start = time.monotonic()
    last_status_line = None

    while True:
        job = get_job_status(job_id)
        status = job.get("status")

        if verbose:
            status_line = format_job_status(job)
            if status_line != last_status_line:
                print(status_line)
                print("")
                last_status_line = status_line

        if status == "completed":
            return job

        if status == "failed":
            raise Wan2GPJobFailed(str(job.get("errors") or job.get("message") or "Generation failed"))

        if timeout_seconds is not None and time.monotonic() - start > timeout_seconds:
            raise TimeoutError(f"Timeout après {timeout_seconds}s pour le job {job_id}")

        time.sleep(max(1, poll_seconds))


def download_file(
    download_url: str,
    output_path: str | Path,
    use_monitor_download: bool = False,
) -> str:
    """
    Downloads a generated file.

    By default, it uses the API endpoint and Authorization header.
    If use_monitor_download is True, it uses the browser-friendly monitor download endpoint.
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if use_monitor_download:
        full_url = f"{WAN2GP_URL}{download_url}"
        if "?" not in full_url:
            full_url = f"{full_url}?token={quote(WAN2GP_TOKEN)}"
        headers = None
    else:
        full_url = _url(download_url)
        headers = _auth_headers()

    with _SESSION.get(
        full_url,
        headers=headers,
        timeout=DEFAULT_DOWNLOAD_TIMEOUT,
        stream=True,
    ) as response:
        _raise_for_response(response)
        with open(output_file, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)

    return str(output_file)


def download_first_generated_file(
    job: Dict[str, Any],
    output_path: str | Path,
) -> str:
    """Downloads the first generated MP4 from a completed job."""
    download_urls = job.get("download_urls", [])
    if not download_urls:
        raise Wan2GPError("Aucun fichier généré à télécharger.")
    return download_file(download_urls[0], output_path)


def get_first_download_url(job: Dict[str, Any], browser: bool = False) -> Optional[str]:
    """
    Returns the first download URL.
    If browser=True, returns a URL usable directly in a browser with token query auth.
    """
    download_urls = job.get("download_urls", [])
    if not download_urls:
        return None

    relative_url = download_urls[0]
    if not browser:
        return relative_url

    job_id = job.get("job_id")
    filename = Path(relative_url).name
    if job_id and filename:
        return f"{WAN2GP_URL}/monitor/download/{quote(str(job_id))}/{quote(filename)}?token={quote(WAN2GP_TOKEN)}"

    return f"{WAN2GP_URL}{relative_url}"


# =========================================================
# HIGH LEVEL FUNCTION FOR AGENTS
# =========================================================

def generate_video(
    prompt: str,
    mode: Optional[str] = None,
    image_path: Optional[str] = None,
    image_start_path: Optional[str] = None,
    image_end_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    use_lora: bool = False,
    lora_url: Optional[str] = None,
    lora_multiplier: Optional[str] = None,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    fps: int = DEFAULT_FPS,
    resolution: str = DEFAULT_RESOLUTION,
    num_inference_steps: int = DEFAULT_STEPS,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    output_path: Optional[str | Path] = None,
    verbose: bool = False,
    wait: bool = True,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    High-level function for agents.

    It can:
    1. choose the mode automatically
    2. submit the job
    3. optionally wait for completion
    4. optionally download the MP4

    If wait=False, it returns immediately after submission.
    """
    selected_mode = choose_mode(
        mode=mode,
        image_path=image_path,
        image_start_path=image_start_path,
        image_end_path=image_end_path,
        audio_path=audio_path,
        use_lora=use_lora,
    )

    submit_result = submit_video_job(
        mode=selected_mode,
        prompt=prompt,
        image_path=image_path,
        image_start_path=image_start_path,
        image_end_path=image_end_path,
        audio_path=audio_path,
        use_lora=use_lora,
        lora_url=lora_url,
        lora_multiplier=lora_multiplier,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    job_id = submit_result["job_id"]

    result: Dict[str, Any] = {
        "job_id": job_id,
        "mode": selected_mode,
        "mode_label": MODE_LABELS.get(selected_mode, selected_mode),
        "submit_result": submit_result,
        "monitor_url": monitor_url(),
        "final_job": None,
        "saved_file": None,
        "browser_download_url": None,
    }

    if not wait:
        return result

    final_job = wait_for_job(
        job_id=job_id,
        poll_seconds=poll_seconds,
        verbose=verbose,
        timeout_seconds=timeout_seconds,
    )

    result["final_job"] = final_job
    result["browser_download_url"] = get_first_download_url(final_job, browser=True)

    if output_path:
        result["saved_file"] = download_first_generated_file(final_job, output_path)

    return result


# =========================================================
# AGENT PROMPT HELPERS
# =========================================================

def build_ltx_prompt(
    shot: str,
    subject: str,
    action: str,
    environment: str,
    camera: str = "The camera slowly pushes in with a natural cinematic motion.",
    lighting: str = "soft natural light with realistic shadows",
    mood: str = "grounded, cinematic, physically believable",
    dialogue: Optional[str] = None,
    language: str = "French",
    audio: Optional[str] = None,
) -> str:
    """
    Small helper for agents that need to produce cleaner LTX prompts.
    It returns a coherent paragraph rather than a keyword list.
    """
    parts = [
        f"{shot.strip()} {camera.strip()}",
        f"The scene takes place in {environment.strip()}, with {lighting.strip()}.",
        f"The subject is {subject.strip()}.",
        f"During the shot, {action.strip()}.",
    ]

    if dialogue:
        parts.append(
            f"The character speaks in {language.strip()} with natural timing and clear lip sync: \"{dialogue.strip()}\"."
        )

    if audio:
        parts.append(f"Audio atmosphere: {audio.strip()}.")

    parts.append(f"The mood is {mood.strip()}, with realistic motion, consistent anatomy, and no impossible camera movement.")

    return " ".join(parts)


# =========================================================
# COMMAND LINE SMOKE TEST
# =========================================================

if __name__ == "__main__":
    print("Wan2GP health:")
    print(health())
    print("Monitor:")
    print(monitor_url())
