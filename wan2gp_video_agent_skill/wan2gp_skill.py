import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any


WAN2GP_URL = os.getenv("WAN2GP_URL", "http://192.168.1.53:7861")
WAN2GP_TOKEN = os.getenv("WAN2GP_TOKEN", "my-super-token-to-change")


# =========================================================
# HEADERS
# =========================================================

def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WAN2GP_TOKEN}"
    }


def _json_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WAN2GP_TOKEN}",
        "Content-Type": "application/json",
    }


# =========================================================
# BASIC API
# =========================================================

def health() -> Dict[str, Any]:
    """
    Vérifie que le serveur Wan2GP répond.
    """
    response = requests.get(
        f"{WAN2GP_URL}/health",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def model_info() -> Dict[str, Any]:
    """
    Retourne les informations du modèle Wan2GP fixe.
    """
    response = requests.get(
        f"{WAN2GP_URL}/model",
        headers=_auth_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def list_jobs() -> Dict[str, Any]:
    """
    Liste les jobs connus par le serveur Wan2GP.

    Attention : les jobs sont gardés en mémoire côté API.
    Si l'API est redémarrée, l'historique disparaît.
    """
    response = requests.get(
        f"{WAN2GP_URL}/jobs",
        headers=_auth_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Récupère l'état détaillé d'un job.
    """
    response = requests.get(
        f"{WAN2GP_URL}/jobs/{job_id}",
        headers=_auth_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def format_job_status(job: Dict[str, Any]) -> str:
    """
    Formate l'état du job pour affichage dans Discord, Telegram, WhatsApp, etc.
    """
    status = job.get("status")
    short_status = job.get("short_status")
    queue_position = job.get("queue_position")
    progress = job.get("progress")
    phase = job.get("phase")
    current_step = job.get("current_step")
    total_steps = job.get("total_steps")
    message = job.get("message")
    api_mode = job.get("api_mode")
    mode = job.get("mode")

    return (
        f"Mode : {api_mode or mode}\n"
        f"Statut : {status} ({short_status})\n"
        f"Position file : {queue_position}\n"
        f"Progression : {progress}%\n"
        f"Phase : {phase}\n"
        f"Étape : {current_step}/{total_steps}\n"
        f"Message : {message}"
    )


# =========================================================
# INTERNAL HELPERS
# =========================================================

def _ensure_file_exists(file_path: str, label: str) -> Path:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"{label} introuvable : {file_path}")

    if not path.is_file():
        raise FileNotFoundError(f"{label} n'est pas un fichier : {file_path}")

    return path


def _base_form_data(
    prompt: str,
    duration_seconds: int,
    fps: int,
    resolution: str,
    num_inference_steps: int,
    seed: Optional[int],
    negative_prompt: Optional[str],
) -> Dict[str, str]:
    data = {
        "prompt": prompt,
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


def _post_multipart(
    endpoint: str,
    data: Dict[str, str],
    files: Dict[str, Any],
    timeout: int = 120,
) -> Dict[str, Any]:
    response = requests.post(
        f"{WAN2GP_URL}{endpoint}",
        data=data,
        files=files,
        headers=_auth_headers(),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


# =========================================================
# SUBMIT FUNCTIONS
# =========================================================

def submit_text_to_video(
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération text to video.
    Retourne immédiatement un job_id.
    """
    payload = {
        "prompt": prompt,
        "duration_seconds": duration_seconds,
        "fps": fps,
        "resolution": resolution,
        "num_inference_steps": num_inference_steps,
    }

    if seed is not None:
        payload["seed"] = seed

    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    response = requests.post(
        f"{WAN2GP_URL}/generate/t2v",
        json=payload,
        headers=_json_headers(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def submit_image_to_video(
    image_path: str,
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération image to video.
    Retourne immédiatement un job_id.
    """
    image_file = _ensure_file_exists(image_path, "Image")

    data = _base_form_data(
        prompt=prompt,
        duration_seconds=duration_seconds,
        fps=fps,
        resolution=resolution,
        num_inference_steps=num_inference_steps,
        seed=seed,
        negative_prompt=negative_prompt,
    )

    with open(image_file, "rb") as file_handle:
        files = {
            "image": (image_file.name, file_handle)
        }

        return _post_multipart(
            endpoint="/generate/i2v",
            data=data,
            files=files,
            timeout=120,
        )


def submit_image_to_video_with_end_image(
    image_start_path: str,
    image_end_path: str,
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération image to video avec image de début et image de fin.
    Retourne immédiatement un job_id.
    """
    image_start_file = _ensure_file_exists(image_start_path, "Image de début")
    image_end_file = _ensure_file_exists(image_end_path, "Image de fin")

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
            "image_start": (image_start_file.name, start_handle),
            "image_end": (image_end_file.name, end_handle),
        }

        return _post_multipart(
            endpoint="/generate/i2v_end",
            data=data,
            files=files,
            timeout=120,
        )


def submit_sound_to_video(
    audio_path: str,
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération sound/audio to video sans image de référence.
    Retourne immédiatement un job_id.
    """
    audio_file = _ensure_file_exists(audio_path, "Audio")

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
            "audio": (audio_file.name, audio_handle),
        }

        return _post_multipart(
            endpoint="/generate/s2v",
            data=data,
            files=files,
            timeout=120,
        )


def submit_sound_to_video_with_image(
    image_path: str,
    audio_path: str,
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération sound/audio to video avec image de référence.
    Retourne immédiatement un job_id.
    """
    image_file = _ensure_file_exists(image_path, "Image")
    audio_file = _ensure_file_exists(audio_path, "Audio")

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
            "image": (image_file.name, image_handle),
            "audio": (audio_file.name, audio_handle),
        }

        return _post_multipart(
            endpoint="/generate/s2v_i2v",
            data=data,
            files=files,
            timeout=120,
        )


def submit_sound_to_video_with_image_and_lora(
    image_path: str,
    audio_path: str,
    prompt: str,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lance une génération sound/audio to video avec image de référence et LoRA serveur.
    Le LoRA est défini côté serveur dans le template s2v_i2v_lora.
    Retourne immédiatement un job_id.
    """
    image_file = _ensure_file_exists(image_path, "Image")
    audio_file = _ensure_file_exists(audio_path, "Audio")

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
            "image": (image_file.name, image_handle),
            "audio": (audio_file.name, audio_handle),
        }

        return _post_multipart(
            endpoint="/generate/s2v_i2v_lora",
            data=data,
            files=files,
            timeout=120,
        )


# =========================================================
# JOB WAIT / DOWNLOAD
# =========================================================

def wait_for_job(
    job_id: str,
    poll_seconds: int = 5,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Attend la fin d'un job.
    Retourne le job complet quand il est terminé.
    """
    while True:
        job = get_job_status(job_id)

        if verbose:
            print(format_job_status(job))

        status = job.get("status")

        if status == "completed":
            return job

        if status == "failed":
            raise RuntimeError(job.get("errors"))

        time.sleep(poll_seconds)


def download_file(
    download_url: str,
    output_path: str,
) -> str:
    """
    Télécharge un fichier généré depuis l'API Wan2GP.
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    full_url = f"{WAN2GP_URL}{download_url}"

    with requests.get(
        full_url,
        headers=_auth_headers(),
        timeout=300,
        stream=True,
    ) as response:
        response.raise_for_status()

        with open(output_file, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)

    return str(output_file)


def download_first_generated_file(
    job: Dict[str, Any],
    output_path: str,
) -> str:
    """
    Télécharge le premier MP4 généré par un job terminé.
    """
    download_urls = job.get("download_urls", [])

    if not download_urls:
        raise RuntimeError("Aucun fichier généré à télécharger.")

    return download_file(download_urls[0], output_path)


# =========================================================
# HIGH LEVEL FUNCTION FOR AGENTS
# =========================================================

def generate_video(
    mode: str,
    prompt: str,
    image_path: Optional[str] = None,
    image_start_path: Optional[str] = None,
    image_end_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    duration_seconds: int = 3,
    fps: int = 24,
    resolution: str = "1280x720",
    num_inference_steps: int = 8,
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    poll_seconds: int = 5,
    output_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Fonction haut niveau pour les agents.

    Modes disponibles :

    - "t2v"            : texte vers vidéo
    - "i2v"            : image vers vidéo
    - "i2v_end"        : image de début + image de fin vers vidéo
    - "s2v"            : audio vers vidéo sans image
    - "s2v_i2v"        : audio + image de référence vers vidéo
    - "s2v_i2v_lora"   : audio + image de référence + LoRA serveur vers vidéo

    Si output_path est fourni, le MP4 est automatiquement téléchargé.
    """
    if mode == "t2v":
        submit_result = submit_text_to_video(
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    elif mode == "i2v":
        if not image_path:
            raise ValueError("image_path est obligatoire en mode i2v.")

        submit_result = submit_image_to_video(
            image_path=image_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    elif mode == "i2v_end":
        if not image_start_path or not image_end_path:
            raise ValueError("image_start_path et image_end_path sont obligatoires en mode i2v_end.")

        submit_result = submit_image_to_video_with_end_image(
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

    elif mode == "s2v":
        if not audio_path:
            raise ValueError("audio_path est obligatoire en mode s2v.")

        submit_result = submit_sound_to_video(
            audio_path=audio_path,
            prompt=prompt,
            duration_seconds=duration_seconds,
            fps=fps,
            resolution=resolution,
            num_inference_steps=num_inference_steps,
            seed=seed,
            negative_prompt=negative_prompt,
        )

    elif mode == "s2v_i2v":
        if not image_path or not audio_path:
            raise ValueError("image_path et audio_path sont obligatoires en mode s2v_i2v.")

        submit_result = submit_sound_to_video_with_image(
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

    elif mode == "s2v_i2v_lora":
        if not image_path or not audio_path:
            raise ValueError("image_path et audio_path sont obligatoires en mode s2v_i2v_lora.")

        submit_result = submit_sound_to_video_with_image_and_lora(
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

    else:
        raise ValueError(
            "mode doit être : 't2v', 'i2v', 'i2v_end', 's2v', 's2v_i2v' ou 's2v_i2v_lora'."
        )

    job_id = submit_result["job_id"]

    final_job = wait_for_job(
        job_id=job_id,
        poll_seconds=poll_seconds,
        verbose=verbose,
    )

    saved_file = None

    if output_path:
        saved_file = download_first_generated_file(
            job=final_job,
            output_path=output_path,
        )

    return {
        "job_id": job_id,
        "submit_result": submit_result,
        "final_job": final_job,
        "saved_file": saved_file,
    }
