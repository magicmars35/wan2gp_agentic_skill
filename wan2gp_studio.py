"""
Wan2GP Studio router.

Put this file next to wan2gp_api_server.py.

This version makes /studio the unique web entry point:
- /studio          new video job form
- /studio/monitor  global monitor for all jobs, including jobs submitted by agents through the API
- /studio/jobs     compact job list
- /studio/job/{id} detailed job view

The global monitor is rendered by wan2gp_studio_monitor.py.
This module never initializes Wan2GP. It only uses callbacks passed by wan2gp_api_server.py.
"""

from __future__ import annotations

import copy
import html
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from wan2gp_studio_monitor import monitor_extra_css, render_global_monitor_body


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def short_text(value: Any, limit: int = 260) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def basename_or_empty(value: Any) -> str:
    return Path(str(value)).name if value else ""


def has_upload(upload: Optional[UploadFile]) -> bool:
    return bool(upload and upload.filename)


def mode_label(mode: str) -> str:
    labels = {
        "t2v": "Text to Video",
        "i2v": "Image to Video",
        "i2v_end": "Start Image + End Image",
        "s2v": "Sound to Video",
        "s2v_i2v": "Sound + Reference Image",
        "s2v_i2v_lora": "Sound + Reference Image + LoRA",
    }
    return labels.get(mode, mode)


def status_badge_class(status: str) -> str:
    return f"status {status}" if status in {"queued", "running", "completed", "failed"} else "status unknown"


def build_token_query(token: str | None) -> str:
    return "" if not token else f"?token={h(token)}"


def format_error(exc: Exception) -> str:
    return str(exc.detail) if isinstance(exc, HTTPException) else str(exc)


STUDIO_CSS = """
:root { --bg:#0e1117; --panel:#171b25; --panel2:#202637; --panel3:#11151f; --text:#f3f4f6; --muted:#9ca3af; --border:#2f3748; --blue:#3b82f6; --green:#22c55e; --red:#ef4444; --orange:#f59e0b; }
* { box-sizing:border-box; }
body { margin:0; padding:24px; background:radial-gradient(circle at top left,#20263a,var(--bg)); color:var(--text); font-family:Arial,Helvetica,sans-serif; }
a { color:#93c5fd; text-decoration:none; } a:hover { text-decoration:underline; }
h1 { margin:0 0 8px; font-size:30px; } h2 { margin-top:0; font-size:20px; }
.subtitle { color:var(--muted); line-height:1.45; margin-bottom:22px; }
.nav { display:flex; gap:12px; margin-bottom:22px; flex-wrap:wrap; }
.nav a,.button,button { display:inline-block; border:0; padding:10px 14px; border-radius:11px; background:var(--blue); color:white; font-weight:700; cursor:pointer; text-decoration:none; }
.nav a.secondary,.button.secondary { background:#374151; } .nav a.active { background:var(--green); color:#052e16; }
button:hover,.button:hover,.nav a:hover { filter:brightness(1.08); text-decoration:none; }
.grid { display:grid; grid-template-columns:minmax(360px,560px) 1fr; gap:18px; align-items:start; }
.card { background:rgba(23,27,37,.94); border:1px solid var(--border); border-radius:18px; padding:18px; box-shadow:0 14px 32px rgba(0,0,0,.28); }
.form-row { margin-bottom:14px; } label { display:block; color:#d1d5db; font-size:13px; font-weight:700; margin-bottom:6px; }
input[type="text"],input[type="number"],input[type="password"],select,textarea { width:100%; padding:10px 11px; border-radius:10px; border:1px solid var(--border); background:#0b0f17; color:var(--text); outline:none; }
input[type="file"] { width:100%; padding:10px; border-radius:10px; border:1px dashed var(--border); background:#0b0f17; color:var(--muted); }
textarea { min-height:170px; resize:vertical; line-height:1.35; }
.small { color:var(--muted); font-size:12px; line-height:1.4; } .help { margin-top:5px; color:var(--muted); font-size:12px; }
.inline-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.status { display:inline-block; padding:5px 9px; border-radius:999px; font-size:12px; color:#050505; font-weight:800; }
.status.queued { background:var(--orange); } .status.running { background:#38bdf8; } .status.completed { background:var(--green); } .status.failed { background:var(--red); color:white; } .status.unknown { background:#94a3b8; }
.table-wrap { overflow-x:auto; } table { width:100%; border-collapse:collapse; } th,td { text-align:left; vertical-align:top; padding:10px 8px; border-bottom:1px solid var(--border); font-size:13px; } th { color:#d1d5db; background:var(--panel2); text-transform:uppercase; letter-spacing:.04em; font-size:11px; }
.mono { font-family:Consolas,Monaco,monospace; font-size:12px; word-break:break-all; }
.progress-wrap { width:170px; height:12px; background:#0b0f17; border:1px solid var(--border); border-radius:999px; overflow:hidden; }
.progress-bar { height:100%; background:linear-gradient(90deg,#38bdf8,#22c55e); } .progress-text { color:var(--muted); font-size:12px; margin-top:4px; }
.error { background:rgba(239,68,68,.13); border:1px solid rgba(239,68,68,.45); color:#fecaca; padding:14px; border-radius:14px; margin-bottom:16px; }
.success { background:rgba(34,197,94,.12); border:1px solid rgba(34,197,94,.40); color:#bbf7d0; padding:14px; border-radius:14px; margin-bottom:16px; }
.warn { color:#fde68a; } video { width:100%; max-height:520px; background:black; border-radius:14px; border:1px solid var(--border); }
.footer { margin-top:24px; color:var(--muted); font-size:12px; } pre { white-space:pre-wrap; word-break:break-word; } .section { margin-top:28px; }
@media (max-width:1100px) { .grid { grid-template-columns:1fr; } .inline-grid { grid-template-columns:repeat(2,1fr); } }
""" + monitor_extra_css()


def page_shell(title: str, body: str, token: str | None = None, refresh_seconds: int | None = None) -> HTMLResponse:
    refresh = f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">' if refresh_seconds else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">{refresh}<title>{h(title)}</title><style>{STUDIO_CSS}</style></head>
<body>{body}<div class="footer">Wan2GP Studio | Unified web cockpit | Same FastAPI server, same Wan2GP queue</div></body></html>""")


def create_studio_router(
    *,
    api_token: str,
    mode_controls: dict[str, dict[str, Any]],
    template_file: Path | str,
    default_resolution: str,
    default_fps: int,
    default_duration_seconds: int,
    default_steps: int,
    allowed_image_extensions: list[str],
    allowed_audio_extensions: list[str],
    get_requester_info: Callable[[Request], dict[str, Any]],
    save_upload_path: Callable[..., Path],
    write_upload_to_disk: Callable[..., Any],
    build_v2_settings: Callable[..., dict[str, Any]],
    create_job_record: Callable[..., Any],
    start_generation_thread: Callable[[str, dict[str, Any]], Any],
    get_job_raw: Callable[[str], Optional[dict[str, Any]]],
    get_jobs_snapshot: Callable[[], list[dict[str, Any]]],
    get_health_snapshot: Optional[Callable[[], dict[str, Any]]] = None,
    get_model_snapshot: Optional[Callable[[], dict[str, Any]]] = None,
) -> APIRouter:
    router = APIRouter(prefix="/studio", tags=["studio"])

    def authorize_web(token: str | None, authorization: str | None = None) -> None:
        if token and token == api_token:
            return
        if authorization == f"Bearer {api_token}":
            return
        raise HTTPException(status_code=401, detail="Unauthorized studio access")

    def build_nav(token: str | None, active: str = "new") -> str:
        tq = build_token_query(token)
        def cls(name: str) -> str:
            return "active" if name == active else "secondary"
        return f"""
        <div class="nav">
            <a href="/studio{tq}" class="{cls('new')}">New video</a>
            <a href="/studio/editor{tq}" class="{cls("editor")}">Editor</a>
            <a href="/studio/monitor{tq}" class="{cls('monitor')}">Global monitor</a>
            <a href="/studio/jobs{tq}" class="{cls('jobs')}">Compact jobs</a>
        </div>
        """

    def render_login(error: str | None = None) -> HTMLResponse:
        error_html = f'<div class="error">{h(error)}</div>' if error else ""
        return page_shell("Wan2GP Studio Login", f"""
        <h1>Wan2GP Studio</h1><div class="subtitle">Enter the API token to open the unified video studio.</div>{error_html}
        <div class="card" style="max-width:520px;"><form method="get" action="/studio"><div class="form-row"><label>Token</label><input type="password" name="token" placeholder="Bearer token"></div><button type="submit">Open Studio</button></form></div>
        """)

    def render_recent_jobs(token: str | None, limit: int = 12) -> str:
        jobs = [copy.deepcopy(j) for j in get_jobs_snapshot()]
        jobs.sort(key=lambda x: x.get("sequence", 0), reverse=True)
        jobs = jobs[:limit]
        if not jobs:
            return '<div class="small">No job yet.</div>'
        tq = build_token_query(token)
        rows = []
        for job in jobs:
            job_id = job.get("job_id", "")
            status = job.get("status", "unknown")
            progress = max(0, min(100, float(job.get("progress") or 0)))
            api_mode = job.get("api_mode") or job.get("mode") or ""
            prompt = short_text(job.get("prompt", ""), 180)
            source = "Studio" if job.get("studio") else "Agent/API"
            rows.append(f"""
            <tr><td><span class="{h(status_badge_class(status))}">{h(status)}</span></td><td>{h(api_mode)}<div class="small">{h(source)}</div></td><td><div class="progress-wrap"><div class="progress-bar" style="width:{h(progress)}%;"></div></div><div class="small">{h(progress)}%</div></td><td>{h(prompt)}</td><td><a href="/studio/job/{h(job_id)}{tq}">Open</a></td></tr>
            """)
        return f"<div class='table-wrap'><table><thead><tr><th>Status</th><th>Mode</th><th>Progress</th><th>Prompt</th><th>Job</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"

    def render_studio_form(token: str | None, error: str | None = None, success: str | None = None) -> HTMLResponse:
        if not token:
            return render_login()
        error_html = f'<div class="error">{h(error)}</div>' if error else ""
        success_html = f'<div class="success">{success}</div>' if success else ""
        options = "".join(f'<option value="{h(mode)}">{h(mode)} - {h(mode_label(mode))}</option>' for mode in mode_controls.keys())
        body = f"""
        <h1>Wan2GP Mini Studio</h1>
        <div class="subtitle">Generate videos directly from the same FastAPI server that runs Wan2GP. The Studio is now the unique web cockpit for generation and monitoring.</div>
        {build_nav(token, active='new')}{error_html}{success_html}
        <div class="grid"><div class="card"><h2>New video job</h2>
        <form method="post" action="/studio/submit" enctype="multipart/form-data">
            <input type="hidden" name="token" value="{h(token)}">
            <div class="form-row"><label>Generation mode</label><select name="mode" id="mode" onchange="updateModeHelp()">{options}</select><div class="help" id="modeHelp"></div></div>
            <div class="form-row"><label>Prompt</label><textarea name="prompt" required placeholder="Write a cinematic Wan2GP / LTX prompt here..."></textarea><div class="help">For LTX, write a clear cinematic direction: camera movement, subject action, lighting, physical motion, mood, and dialogue if needed.</div></div>
            <div class="inline-grid">
                <div class="form-row"><label>Duration seconds</label><input type="number" name="duration_seconds" min="1" max="60" value="{h(default_duration_seconds)}"></div>
                <div class="form-row"><label>FPS</label><input type="number" name="fps" min="1" max="60" value="{h(default_fps)}"></div>
                <div class="form-row"><label>Resolution</label><input type="text" name="resolution" value="{h(default_resolution)}"></div>
                <div class="form-row"><label>Steps</label><input type="number" name="num_inference_steps" min="1" max="100" value="{h(default_steps)}"></div>
            </div>
            <div class="inline-grid">
                <div class="form-row"><label>Seed</label><input type="number" name="seed" placeholder="random"></div>
                <div class="form-row"><label>LoRA multiplier</label><input type="text" name="lora_multiplier" placeholder="1"></div>
                <div class="form-row" style="grid-column:span 2;"><label>LoRA URL, optional</label><input type="text" name="lora_url" placeholder="Use server default if empty"></div>
            </div>
            <div class="form-row"><label>Negative prompt, optional</label><input type="text" name="negative_prompt" placeholder="Things to avoid"></div>
            <div class="form-row"><label>Reference image</label><input type="file" name="image" accept="image/png,image/jpeg,image/webp"><div class="help">Used by i2v, s2v_i2v and s2v_i2v_lora.</div></div>
            <div class="form-row"><label>Start image</label><input type="file" name="image_start" accept="image/png,image/jpeg,image/webp"><div class="help">Used by i2v_end. If empty, the reference image can be used as start image.</div></div>
            <div class="form-row"><label>End image</label><input type="file" name="image_end" accept="image/png,image/jpeg,image/webp"></div>
            <div class="form-row"><label>Audio</label><input type="file" name="audio" accept="audio/mpeg,audio/wav,audio/ogg,audio/mp4,audio/flac"><div class="help">Used by s2v, s2v_i2v and s2v_i2v_lora.</div></div>
            <button type="submit">Submit video job</button>
        </form></div><div class="card"><h2>Recent jobs</h2>{render_recent_jobs(token)}</div></div>
        <script>
        const modeHints={{"t2v":"Text only. No image or audio required.","i2v":"Requires a reference image. The image becomes the first frame/reference.","i2v_end":"Requires a start image and an end image. You may use Reference image as start image.","s2v":"Requires an audio file. The prompt should describe the visual performance.","s2v_i2v":"Requires a reference image and an audio file. Best for lip sync with a stable character.","s2v_i2v_lora":"Requires a reference image and an audio file. Adds server-side or custom LoRA."}};
        function updateModeHelp(){{const mode=document.getElementById("mode").value;document.getElementById("modeHelp").innerText=modeHints[mode]||"";}} updateModeHelp();
        </script>
        """
        return page_shell("Wan2GP Mini Studio", body, token=token)

    async def save_optional_upload(upload: Optional[UploadFile], job_id: str, prefix: str, allowed_extensions: list[str]) -> Optional[Path]:
        if not has_upload(upload):
            return None
        path = save_upload_path(upload=upload, job_id=job_id, prefix=prefix, allowed_extensions=allowed_extensions)
        await write_upload_to_disk(upload, path)
        return path

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    def studio_home(token: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        if not token and authorization != f"Bearer {api_token}":
            return render_login()
        try:
            authorize_web(token=token, authorization=authorization)
        except HTTPException:
            return render_login("Invalid token.")
        return render_studio_form(token=token)

    @router.get("/monitor", response_class=HTMLResponse)
    def studio_monitor(token: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        authorize_web(token=token, authorization=authorization)
        health = None
        model = None
        if get_health_snapshot:
            try: health = get_health_snapshot()
            except Exception: health = None
        if get_model_snapshot:
            try: model = get_model_snapshot()
            except Exception: model = None
        body = render_global_monitor_body(jobs=get_jobs_snapshot(), token=token, nav_html=build_nav(token, active="monitor"), health=health, model=model, title="Wan2GP Studio Global Monitor")
        return page_shell("Wan2GP Studio Global Monitor", body, token=token, refresh_seconds=5)

    @router.get("/jobs", response_class=HTMLResponse)
    def studio_jobs(token: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        authorize_web(token=token, authorization=authorization)
        body = f"<h1>Wan2GP Studio Jobs</h1><div class='subtitle'>Compact list of recent jobs from the shared Wan2GP queue. For the full monitoring view, use Global monitor.</div>{build_nav(token, active='jobs')}<div class='card'>{render_recent_jobs(token, limit=100)}</div>"
        return page_shell("Wan2GP Studio Jobs", body, token=token, refresh_seconds=5)

    @router.post("/submit")
    async def studio_submit(
        request: Request,
        token: str = Form(...),
        mode: str = Form(...),
        prompt: str = Form(...),
        duration_seconds: int = Form(default_duration_seconds),
        fps: int = Form(default_fps),
        resolution: str = Form(default_resolution),
        num_inference_steps: int = Form(default_steps),
        seed: str | None = Form(None),
        negative_prompt: str | None = Form(None),
        lora_url: str | None = Form(None),
        lora_multiplier: str | None = Form(None),
        image: UploadFile | None = File(None),
        image_start: UploadFile | None = File(None),
        image_end: UploadFile | None = File(None),
        audio: UploadFile | None = File(None),
        authorization: str | None = Header(default=None),
    ):
        try:
            authorize_web(token=token, authorization=authorization)
            if mode not in mode_controls:
                raise ValueError(f"Unknown mode: {mode}")
            if not prompt or len(prompt.strip()) < 3:
                raise ValueError("Prompt is required and must contain at least 3 characters.")
            parsed_seed = int(str(seed).strip()) if seed is not None and str(seed).strip() else None
            clean_prompt = prompt.strip()
            clean_negative_prompt = (negative_prompt or "").strip() or None
            clean_lora_url = (lora_url or "").strip() or None
            clean_lora_multiplier = (lora_multiplier or "").strip() or None
            job_id = str(uuid4())
            requester_info = get_requester_info(request)
            reference_image_path = await save_optional_upload(image, job_id, "image", allowed_image_extensions)
            image_start_path = await save_optional_upload(image_start, job_id, "image_start", allowed_image_extensions)
            image_end_path = await save_optional_upload(image_end, job_id, "image_end", allowed_image_extensions)
            audio_path = await save_optional_upload(audio, job_id, "audio", allowed_audio_extensions)
            if mode == "i2v_end" and image_start_path is None and reference_image_path is not None:
                image_start_path = reference_image_path
            settings_image_start = settings_image_end = settings_audio = None
            if mode == "i2v":
                if reference_image_path is None: raise ValueError("Mode i2v requires a reference image.")
                settings_image_start = reference_image_path
            elif mode == "i2v_end":
                if image_start_path is None or image_end_path is None: raise ValueError("Mode i2v_end requires a start image and an end image.")
                settings_image_start = image_start_path; settings_image_end = image_end_path
            elif mode == "s2v":
                if audio_path is None: raise ValueError("Mode s2v requires an audio file.")
                settings_audio = audio_path
            elif mode in {"s2v_i2v", "s2v_i2v_lora"}:
                if reference_image_path is None: raise ValueError(f"Mode {mode} requires a reference image.")
                if audio_path is None: raise ValueError(f"Mode {mode} requires an audio file.")
                settings_image_start = reference_image_path; settings_audio = audio_path
            settings = build_v2_settings(mode=mode, prompt=clean_prompt, duration_seconds=duration_seconds, fps=fps, resolution=resolution, seed=parsed_seed, negative_prompt=clean_negative_prompt, num_inference_steps=num_inference_steps, image_start=settings_image_start, image_end=settings_image_end, audio_guide=settings_audio, lora_url=clean_lora_url, lora_multiplier=clean_lora_multiplier)
            public_mode = mode_controls[mode].get("public_mode", mode)
            extra = {"api_mode": mode, "studio": True, "template_file": str(template_file)}
            if reference_image_path: extra["input_image"] = str(reference_image_path)
            if image_start_path: extra["input_image_start"] = str(image_start_path)
            if image_end_path: extra["input_image_end"] = str(image_end_path)
            if audio_path: extra["input_audio"] = str(audio_path)
            if settings.get("activated_loras"):
                extra["activated_loras"] = settings.get("activated_loras", [])
                extra["loras_multipliers"] = settings.get("loras_multipliers", "")
            create_job_record(job_id=job_id, mode=public_mode, prompt=clean_prompt, settings=settings, duration_seconds=duration_seconds, fps=fps, resolution=resolution, requester_info=requester_info, extra=extra)
            start_generation_thread(job_id, settings)
            return RedirectResponse(url=f"/studio/job/{job_id}{build_token_query(token)}", status_code=303)
        except Exception as exc:
            return render_studio_form(token=token, error=format_error(exc))

    @router.get("/job/{job_id}", response_class=HTMLResponse)
    def studio_job(job_id: str, token: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        authorize_web(token=token, authorization=authorization)
        job = get_job_raw(job_id)
        if not job:
            return page_shell("Wan2GP Job Not Found", f"<h1>Job not found</h1>{build_nav(token)}<div class='error'>Unknown job_id: {h(job_id)}</div>", token=token)
        status = job.get("status", "unknown")
        refresh = 3 if status in {"queued", "running"} else None
        progress = max(0, min(100, float(job.get("progress") or 0)))
        download_html = '<span class="small">No generated file yet.</span>'
        preview_html = ""
        download_urls = job.get("download_urls") or []
        if download_urls:
            first_url = str(download_urls[0])
            filename = basename_or_empty(first_url)
            download_href = f"/studio/download/{h(job_id)}/{h(filename)}{build_token_query(token)}"
            download_html = f'<a class="button" href="{download_href}" target="_blank">Download MP4</a>'
            if status == "completed":
                preview_html = f"<div class='card' style='margin-top:18px;'><h2>Preview</h2><video controls src='{download_href}'></video></div>"
        errors_html = f"<div class='error'><strong>Errors</strong><br><pre class='mono'>{h(job.get('errors'))}</pre></div>" if job.get("errors") else ""
        input_lines = []
        for key, label in [("input_image", "Reference image"), ("input_image_start", "Start image"), ("input_image_end", "End image"), ("input_audio", "Audio")]:
            if job.get(key): input_lines.append(f"<div>{h(label)}: <span class='mono'>{h(basename_or_empty(job.get(key)))}</span></div>")
        if job.get("activated_loras"):
            input_lines.append(f"<div>LoRA: <span class='mono'>{h(job.get('activated_loras'))}</span></div>")
            input_lines.append(f"<div>LoRA multiplier: <span class='mono'>{h(job.get('loras_multipliers'))}</span></div>")
        inputs_html = "".join(input_lines) if input_lines else '<span class="small">No input file.</span>'
        source = "Studio" if job.get("studio") else "Agent/API"
        body = f"""
        <h1>Wan2GP Studio Job</h1><div class="subtitle">Job ID: <span class="mono">{h(job_id)}</span></div>{build_nav(token)}{errors_html}
        <div class="grid"><div class="card"><h2>Status</h2><p><span class="{h(status_badge_class(status))}">{h(status)}</span></p><div class="progress-wrap"><div class="progress-bar" style="width:{h(progress)}%;"></div></div><div class="small">{h(progress)}%</div><p class="small">Source: <strong>{h(source)}</strong><br>Mode: <strong>{h(job.get("api_mode") or job.get("mode"))}</strong><br>Queue position: <strong>{h(job.get("queue_position"))}</strong><br>Phase: <strong>{h(job.get("phase"))}</strong><br>Step: <strong>{h(job.get("current_step"))}/{h(job.get("total_steps"))}</strong><br>Message: <strong>{h(job.get("message"))}</strong></p><p>{download_html}</p></div>
        <div class="card"><h2>Request</h2><p class="small">Resolution: <strong>{h(job.get("resolution"))}</strong><br>Duration: <strong>{h(job.get("duration_seconds"))}s</strong><br>FPS: <strong>{h(job.get("fps"))}</strong><br>Seed: <span class="mono">{h(job.get("seed"))}</span><br>Requester IP: <span class="mono">{h(job.get("requester_ip"))}</span></p><h2>Prompt</h2><p>{h(job.get("prompt"))}</p><h2>Inputs</h2><div class="small">{inputs_html}</div></div></div>{preview_html}
        """
        return page_shell("Wan2GP Studio Job", body, token=token, refresh_seconds=refresh)

    @router.get("/download/{job_id}/{filename}")
    def studio_download(job_id: str, filename: str, token: str | None = Query(default=None), authorization: str | None = Header(default=None)):
        authorize_web(token=token, authorization=authorization)
        job = get_job_raw(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        safe_filename = Path(filename).name
        for file_path in job.get("files", []):
            path = Path(file_path)
            if path.name == safe_filename and path.exists():
                return FileResponse(path, media_type="video/mp4", filename=path.name)
        raise HTTPException(status_code=404, detail="File not found")

    return router
