import os
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any


WAN2GP_URL = os.getenv("WAN2GP_URL", "http://192.168.1.53:7861")
WAN2GP_TOKEN = os.getenv("WAN2GP_TOKEN", "HGH7EPBCE51vureBCBUEBCE75678edfv9HUGBC7E")


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WAN2GP_TOKEN}"
    }


def _json_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {WAN2GP_TOKEN}",
        "Content-Type": "application/json",
    }


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

    return (
        f"Statut : {status} ({short_status})\n"
        f"Position file : {queue_position}\n"
        f"Progression : {progress}%\n"
        f"Phase : {phase}\n"
        f"Étape : {current_step}/{total_steps}\n"
        f"Message : {message}"
    )


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
    image_file = Path(image_path)

    if not image_file.exists():
        raise FileNotFoundError(f"Image introuvable : {image_path}")

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

    with open(image_file, "rb") as file_handle:
        files = {
            "image": (image_file.name, file_handle)
        }

        response = requests.post(
            f"{WAN2GP_URL}/generate/i2v",
            data=data,
            files=files,
            headers=_auth_headers(),
            timeout=120,
        )

    response.raise_for_status()
    return response.json()


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


def generate_video(
    mode: str,
    prompt: str,
    image_path: Optional[str] = None,
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

    mode :
    - "t2v" pour text to video
    - "i2v" pour image to video

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

    else:
        raise ValueError("mode doit être 't2v' ou 'i2v'.")

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