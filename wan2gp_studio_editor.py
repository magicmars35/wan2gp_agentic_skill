"""
Wan2GP Studio Editor module V4.

Standalone FastAPI router for the Wan2GP Studio video editor.

V4 additions:
- modernized editor UI
- draggable playhead on timeline
- scrub bar synced with program preview
- 10 possible video tracks with progressive track creation
- play, pause, start, -5s and +5s preview controls
- clip resize blocked by source duration
- transition panel with fade, crossfade, blur, white flash and light flash
- ffmpeg export as an independent MP4 output, not re-imported into assets

Required:
- ffmpeg must be available in PATH, or set FFMPEG_BIN to the full ffmpeg.exe path.
"""

from __future__ import annotations

import html
import json
import mimetypes
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse


# =========================================================
# HELPERS
# =========================================================

def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def build_token_query(token: str | None) -> str:
    if not token:
        return ""
    return f"?token={h(token)}"


def basename_or_empty(value: Any) -> str:
    if not value:
        return ""
    return Path(str(value)).name


def safe_name(name: str) -> str:
    raw = Path(name or "asset.bin").name
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ "
    cleaned = "".join(c if c in allowed else "_" for c in raw).strip()
    return cleaned or "asset.bin"


def asset_kind_from_extension(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}:
        return "video"
    if ext in {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}:
        return "audio"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    return "file"


def is_allowed_asset(path: Path, allowed_video: set[str], allowed_audio: set[str], allowed_image: set[str]) -> bool:
    ext = path.suffix.lower()
    return ext in allowed_video or ext in allowed_audio or ext in allowed_image


def mime_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_assets_json(assets: list[dict[str, Any]]) -> str:
    return json.dumps(assets, ensure_ascii=False).replace("</", "<\\/")


def ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def run_ffmpeg(args: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ffmpeg_bin(), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )


# =========================================================
# ROUTER FACTORY
# =========================================================

def create_studio_editor_router(
    *,
    api_token: str,
    get_jobs_snapshot: Callable[[], list[dict[str, Any]]],
    get_job_raw: Callable[[str], Optional[dict[str, Any]]],
    studio_assets_dir: str | Path = "studio_assets",
    studio_renders_dir: str | Path | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/studio/editor", tags=["studio-editor"])

    assets_dir = Path(studio_assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Important: renders are outside assets by default, so final exports do not pollute the asset library.
    renders_dir = Path(studio_renders_dir) if studio_renders_dir else assets_dir.parent / "studio_renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    allowed_video = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
    allowed_audio = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
    allowed_image = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    def authorize_web(token: str | None, authorization: str | None = None) -> None:
        if token and token == api_token:
            return
        if authorization == f"Bearer {api_token}":
            return
        raise HTTPException(status_code=401, detail="Unauthorized editor access")

    def local_asset_path(asset_id: str) -> Optional[Path]:
        for path in assets_dir.iterdir():
            if path.is_file() and path.name.startswith(asset_id + "_"):
                return path
        return None

    def render_path(render_id: str) -> Optional[Path]:
        for path in renders_dir.iterdir():
            if path.is_file() and path.name.startswith(render_id + "_"):
                return path
        return None

    def resolve_asset_to_path(asset: dict[str, Any]) -> Path:
        origin = asset.get("origin")

        if origin == "local":
            asset_id = str(asset.get("asset_id") or "")
            path = local_asset_path(asset_id)
            if not path:
                raise RuntimeError(f"Local asset not found: {asset_id}")
            return path

        if origin == "generated":
            job_id = asset.get("job_id")
            filename = asset.get("filename")
            job = get_job_raw(str(job_id))
            if not job:
                raise RuntimeError(f"Generated job not found: {job_id}")

            safe_filename = Path(str(filename)).name
            for file_path in job.get("files", []):
                path = Path(file_path)
                if path.name == safe_filename and path.exists():
                    return path

            raise RuntimeError(f"Generated file not found: {filename}")

        raise RuntimeError(f"Unsupported asset origin for rendering: {origin}")

    def build_generated_assets(token: str | None) -> list[dict[str, Any]]:
        jobs = get_jobs_snapshot()
        assets: list[dict[str, Any]] = []

        for job in jobs:
            if job.get("status") != "completed":
                continue

            files = job.get("files")
            if not isinstance(files, list):
                continue

            for file_path in files:
                filename = basename_or_empty(file_path)
                if not filename.lower().endswith(".mp4"):
                    continue

                job_id = job.get("job_id", "")
                download_url = f"/studio/download/{h(job_id)}/{h(filename)}{build_token_query(token)}"
                duration = job.get("duration_seconds") or ""

                assets.append(
                    {
                        "asset_id": f"job_{job_id}_{filename}",
                        "origin": "generated",
                        "kind": "video",
                        "job_id": job_id,
                        "filename": filename,
                        "url": download_url,
                        "mode": job.get("api_mode") or job.get("mode") or "",
                        "prompt": job.get("prompt") or "",
                        "duration_seconds": duration,
                        "source_duration": duration,
                        "resolution": job.get("resolution") or "",
                        "seed": job.get("seed") or "",
                        "source": "Studio" if job.get("studio") else "Agent/API",
                        "created_at": job.get("created_at") or "",
                    }
                )

        return assets

    def build_local_assets(token: str | None) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []

        for path in assets_dir.iterdir():
            if not path.is_file():
                continue

            if not is_allowed_asset(path, allowed_video, allowed_audio, allowed_image):
                continue

            parts = path.name.split("_", 1)
            asset_id = parts[0] if parts else path.stem
            original_name = parts[1] if len(parts) > 1 else path.name
            kind = asset_kind_from_extension(path)
            url = f"/studio/editor/assets/{h(asset_id)}{build_token_query(token)}"

            assets.append(
                {
                    "asset_id": asset_id,
                    "origin": "local",
                    "kind": kind,
                    "job_id": "",
                    "filename": original_name,
                    "url": url,
                    "mode": "local",
                    "prompt": "",
                    "duration_seconds": "",
                    "source_duration": "",
                    "resolution": "",
                    "seed": "",
                    "source": "Local upload",
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                    "size_bytes": path.stat().st_size,
                }
            )

        return assets

    def build_all_assets(token: str | None) -> list[dict[str, Any]]:
        # Final renders are intentionally NOT injected into the assets.
        assets = build_local_assets(token) + build_generated_assets(token)
        assets.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return assets

    def render_login(error: str | None = None) -> HTMLResponse:
        error_html = f'<div class="error">{h(error)}</div>' if error else ""
        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Wan2GP Video Editor Login</title>
    <style>{EDITOR_CSS}</style>
</head>
<body>
    <div class="login-wrap">
        <h1>Wan2GP Video Editor</h1>
        <p>Enter the API token to open the editor.</p>
        {error_html}
        <form method="get" action="/studio/editor">
            <input type="password" name="token" placeholder="Bearer token">
            <button type="submit">Open Editor</button>
        </form>
    </div>
</body>
</html>"""
        return HTMLResponse(body)

    @router.get("", response_class=HTMLResponse)
    @router.get("/", response_class=HTMLResponse)
    def editor_home(
        token: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        if not token and authorization != f"Bearer {api_token}":
            return render_login()

        try:
            authorize_web(token=token, authorization=authorization)
        except HTTPException:
            return render_login("Invalid token.")

        assets = build_all_assets(token)
        html_page = EDITOR_HTML
        html_page = html_page.replace("__ASSETS_JSON__", make_assets_json(assets))
        html_page = html_page.replace("__TOKEN_QUERY__", build_token_query(token))
        html_page = html_page.replace("__TOKEN_VALUE__", h(token or ""))
        html_page = html_page.replace("__EDITOR_CSS__", EDITOR_CSS)
        return HTMLResponse(html_page)

    @router.post("/upload")
    async def upload_assets(
        request: Request,
        files: list[UploadFile] = File(...),
        token: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        form = await request.form()
        form_token = form.get("token")
        final_token = token or (str(form_token) if form_token else None)

        authorize_web(token=final_token, authorization=authorization)

        uploaded = []
        rejected = []

        for upload in files:
            original_name = safe_name(upload.filename or "asset.bin")
            ext = Path(original_name).suffix.lower()

            if ext not in allowed_video and ext not in allowed_audio and ext not in allowed_image:
                rejected.append({"filename": original_name, "reason": "unsupported extension"})
                continue

            asset_id = uuid4().hex[:16]
            destination = assets_dir / f"{asset_id}_{original_name}"

            with destination.open("wb") as f:
                shutil.copyfileobj(upload.file, f)

            uploaded.append(
                {
                    "asset_id": asset_id,
                    "filename": original_name,
                    "kind": asset_kind_from_extension(destination),
                    "size_bytes": destination.stat().st_size,
                    "created_at": now_iso(),
                }
            )

        return JSONResponse({"uploaded": uploaded, "rejected": rejected})

    @router.get("/assets/{asset_id}")
    def get_local_asset(
        asset_id: str,
        token: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        authorize_web(token=token, authorization=authorization)

        path = local_asset_path(asset_id)
        if not path or not path.exists():
            raise HTTPException(status_code=404, detail="Asset not found")

        return FileResponse(
            path,
            media_type=mime_type_for(path),
            filename=path.name.split("_", 1)[1] if "_" in path.name else path.name,
        )

    @router.get("/renders/{render_id}")
    def get_render(
        render_id: str,
        token: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ):
        authorize_web(token=token, authorization=authorization)

        path = render_path(render_id)
        if not path or not path.exists():
            raise HTTPException(status_code=404, detail="Render not found")

        return FileResponse(
            path,
            media_type="video/mp4",
            filename=path.name.split("_", 1)[1] if "_" in path.name else path.name,
        )

    @router.post("/render")
    async def render_timeline(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ):
        token = payload.get("token")
        authorize_web(token=token, authorization=authorization)

        plan = payload.get("plan")
        if not isinstance(plan, dict):
            return JSONResponse({"ok": False, "error": "Invalid render plan"}, status_code=400)

        clips = plan.get("clips")
        if not isinstance(clips, list) or not clips:
            return JSONResponse({"ok": False, "error": "Timeline is empty"}, status_code=400)

        try:
            output_info = plan.get("output") or {}
            width = int(output_info.get("width") or 1280)
            height = int(output_info.get("height") or 720)
            fps = int(output_info.get("fps") or 24)
            total_duration = max(
                1.0,
                max(float(c.get("timeline_start") or 0) + float(c.get("duration") or 0) for c in clips),
            )

            render_id = uuid4().hex[:16]
            final_name = f"{render_id}_timeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            final_path = renders_dir / final_name

            visual_clips = [clip for clip in clips if clip.get("kind") in {"video", "image"}]
            audio_clips = [clip for clip in clips if clip.get("kind") == "audio"]

            if not visual_clips:
                raise RuntimeError("No video or image clip found on timeline")

            render_visual_composite(
                visual_clips=visual_clips,
                output_path=final_path,
                width=width,
                height=height,
                fps=fps,
                total_duration=total_duration,
                resolver=resolve_asset_to_path,
            )

            if audio_clips:
                temp_video = final_path.with_suffix(".video_only.mp4")
                shutil.move(final_path, temp_video)

                temp_audio = final_path.with_suffix(".audio.m4a")
                create_audio_mix(audio_clips, temp_audio, resolve_asset_to_path)

                result = run_ffmpeg([
                    "-y",
                    "-i", str(temp_video),
                    "-i", str(temp_audio),
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    str(final_path),
                ])

                temp_video.unlink(missing_ok=True)
                temp_audio.unlink(missing_ok=True)

                if result.returncode != 0:
                    raise RuntimeError(f"ffmpeg audio mux failed:\n{result.stderr}")

            download_url = f"/studio/editor/renders/{render_id}{build_token_query(token)}"

            return JSONResponse({
                "ok": True,
                "render_id": render_id,
                "filename": final_name,
                "download_url": download_url,
                "path": str(final_path),
                "note": "Final export is downloadable but not added to the Studio assets.",
            })

        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    def render_visual_composite(
        *,
        visual_clips: list[dict[str, Any]],
        output_path: Path,
        width: int,
        height: int,
        fps: int,
        total_duration: float,
        resolver: Callable[[dict[str, Any]], Path],
    ):
        def track_order(clip: dict[str, Any]) -> int:
            track = str(clip.get("track") or "V1")
            if track.startswith("V"):
                try:
                    return int(track[1:])
                except Exception:
                    return 1
            return 1

        sorted_clips = sorted(
            visual_clips,
            key=lambda c: (track_order(c), float(c.get("timeline_start") or 0)),
        )

        args: list[str] = [
            "-y",
            "-f", "lavfi",
            "-t", f"{total_duration:.3f}",
            "-i", f"color=c=black:s={width}x{height}:r={fps}",
        ]

        for clip in sorted_clips:
            source_path = resolver(clip)
            kind = clip.get("kind")
            trim_start = max(0.0, float(clip.get("trim_start") or 0))
            trim_end = max(trim_start + 0.05, float(clip.get("trim_end") or (trim_start + 4)))
            duration = max(0.05, float(clip.get("duration") or (trim_end - trim_start)))

            if kind == "image":
                args += ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(source_path)]
            else:
                args += ["-ss", f"{trim_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_path)]

        filter_parts: list[str] = []
        previous = "[0:v]"

        for index, clip in enumerate(sorted_clips, start=1):
            timeline_start = max(0.0, float(clip.get("timeline_start") or 0))
            duration = max(0.05, float(clip.get("duration") or 1))
            transition_in = str(clip.get("transition_in") or "none")
            transition_out = str(clip.get("transition_out") or transition_in or "none")
            transition_duration = max(0.05, min(float(clip.get("transition_duration") or 0.35), duration / 2))

            vf_chain = (
                f"[{index}:v]"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1,format=yuva420p"
            )

            if transition_in in {"fade", "crossfade", "blur", "blur_crossfade", "white_flash", "light_flash"}:
                vf_chain += f",fade=t=in:st=0:d={transition_duration:.3f}:alpha=1"

            if transition_out in {"fade", "crossfade", "blur", "blur_crossfade", "white_flash", "light_flash"}:
                out_start = max(0.0, duration - transition_duration)
                vf_chain += f",fade=t=out:st={out_start:.3f}:d={transition_duration:.3f}:alpha=1"

            vf_chain += f",setpts=PTS-STARTPTS+{timeline_start:.3f}/TB[v{index}]"
            filter_parts.append(vf_chain)

            out_label = f"[mix{index}]"
            filter_parts.append(f"{previous}[v{index}]overlay=shortest=0:eof_action=pass{out_label}")
            previous = out_label

            if transition_in in {"white_flash", "light_flash"}:
                flash_label = f"[flash{index}]"
                flash_out = f"[mix{index}f]"
                flash_duration = min(0.22, transition_duration)
                opacity = "0.75" if transition_in == "white_flash" else "0.45"
                filter_parts.append(
                    f"color=c=white@{opacity}:s={width}x{height}:d={flash_duration:.3f},"
                    f"format=yuva420p,setpts=PTS-STARTPTS+{timeline_start:.3f}/TB{flash_label}"
                )
                filter_parts.append(f"{previous}{flash_label}overlay=shortest=0:eof_action=pass{flash_out}")
                previous = flash_out

        filter_complex = ";".join(filter_parts)

        result = run_ffmpeg([
            *args,
            "-filter_complex", filter_complex,
            "-map", previous,
            "-t", f"{total_duration:.3f}",
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            str(output_path),
        ])

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg visual render failed:\n{result.stderr}")

    def create_audio_mix(
        audio_clips: list[dict[str, Any]],
        output_path: Path,
        resolver: Callable[[dict[str, Any]], Path],
    ):
        args: list[str] = ["-y"]
        filter_parts: list[str] = []
        mix_inputs: list[str] = []

        for index, clip in enumerate(audio_clips):
            source_path = resolver(clip)
            trim_start = max(0.0, float(clip.get("trim_start") or 0))
            trim_end = max(trim_start + 0.05, float(clip.get("trim_end") or (trim_start + 4)))
            duration = max(0.05, float(clip.get("duration") or (trim_end - trim_start)))
            timeline_start = max(0.0, float(clip.get("timeline_start") or 0))
            delay_ms = int(timeline_start * 1000)

            args += ["-ss", f"{trim_start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_path)]

            label = f"a{index}"
            filter_parts.append(f"[{index}:a]adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS[{label}]")
            mix_inputs.append(f"[{label}]")

        if len(audio_clips) == 1:
            filter_complex = f"{filter_parts[0]};{mix_inputs[0]}anull[aout]"
        else:
            filter_complex = (
                ";".join(filter_parts)
                + ";"
                + "".join(mix_inputs)
                + f"amix=inputs={len(audio_clips)}:duration=longest:dropout_transition=0[aout]"
            )

        result = run_ffmpeg([
            *args,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "aac",
            str(output_path),
        ])

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio mix failed:\n{result.stderr}")

    return router


# =========================================================
# HTML TEMPLATE
# =========================================================

EDITOR_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Wan2GP Studio Editor</title>
    <style>__EDITOR_CSS__</style>
</head>
<body>
<div class="app">
    <header class="topbar">
        <div class="brand">
            <div class="logo">W</div>
            <div>
                <div class="title">Wan2GP Studio</div>
                <div class="subtitle">Video Editor</div>
            </div>
        </div>

        <nav class="topnav">
            <a href="/studio__TOKEN_QUERY__">Generate</a>
            <a href="/studio/monitor__TOKEN_QUERY__">Monitor</a>
            <a href="/studio/jobs__TOKEN_QUERY__">Jobs</a>
            <a class="active" href="/studio/editor__TOKEN_QUERY__">Editor</a>
        </nav>

        <div class="top-actions">
            <button onclick="saveProject()">Save</button>
            <button onclick="exportPlan()" class="ghost">Export JSON</button>
            <button onclick="renderTimelineServer()" class="render">Export MP4</button>
            <button onclick="clearTimeline()" class="ghost">Clear</button>
        </div>
    </header>

    <main class="workspace">
        <aside class="assets-panel">
            <div class="panel-title-row">
                <h2>Assets</h2>
                <span id="assetCount" class="pill">0</span>
            </div>

            <form id="uploadForm" class="upload-box" enctype="multipart/form-data">
                <input type="hidden" name="token" value="__TOKEN_VALUE__">
                <label class="upload-label">
                    Import videos, images or MP3
                    <input id="assetUploadInput" type="file" name="files" multiple accept="video/*,audio/*,image/*" onchange="uploadAssets()">
                </label>
                <div class="upload-drop" id="uploadDrop">Drop files here</div>
                <div id="uploadStatus" class="small"></div>
            </form>

            <div class="asset-tabs">
                <button class="active" onclick="filterAssets('all', event)">All</button>
                <button onclick="filterAssets('video', event)">Video</button>
                <button onclick="filterAssets('audio', event)">Audio</button>
                <button onclick="filterAssets('image', event)">Image</button>
                <button onclick="filterAssets('local', event)">Local</button>
                <button onclick="filterAssets('generated', event)">Generated</button>
            </div>

            <input id="assetSearch" class="search" placeholder="Search assets or prompts..." oninput="renderAssets()">
            <div id="assetsGrid" class="assets-grid"></div>
        </aside>

        <section class="main-view">
            <div class="viewer-row">
                <section class="viewer-card">
                    <div class="viewer-header">
                        <span>Asset Trimmer</span>
                        <span id="clipName" class="muted">No asset selected</span>
                    </div>
                    <div class="viewer-body" id="assetViewerWrap">
                        <video id="clipViewer" controls></video>
                        <audio id="audioViewer" controls></audio>
                        <img id="imageViewer" alt="">
                    </div>
                    <div class="trim-panel">
                        <div class="trim-grid">
                            <div><label>Trim start</label><input id="trimStart" type="number" min="0" step="0.01" value="0" oninput="updateTrimPreview()"></div>
                            <div><label>Trim end</label><input id="trimEnd" type="number" min="0" step="0.01" value="0" oninput="updateTrimPreview()"></div>
                            <div><label>Timeline start</label><input id="timelineStart" type="number" min="0" step="0.01" value="0"></div>
                            <div><button onclick="addSelectedToTimeline()">Add selection</button></div>
                        </div>
                    </div>
                </section>

                <section class="viewer-card final-viewer">
                    <div class="viewer-header">
                        <span>Program Preview</span>
                        <span id="programTime" class="muted">00:00:00.00</span>
                    </div>
                    <div class="viewer-body timeline-preview" id="previewWrap">
                        <video id="timelineViewer"></video>
                        <audio id="timelineAudioViewer"></audio>
                        <img id="timelineImageViewer" alt="">
                        <div id="emptyPreview" class="empty-preview">Move the playhead on the timeline</div>
                    </div>
                    <div class="viewer-controls preview-controls">
                        <button onclick="goToStart()">⏮</button>
                        <button onclick="seekRelative(-5)">-5s</button>
                        <button id="playPauseButton" onclick="togglePlayback()">▶</button>
                        <button onclick="pausePlayback()">⏸</button>
                        <button onclick="seekRelative(5)">+5s</button>
                        <button onclick="previewSelectedTimelineItem()" class="ghost">Selected</button>
                        <button onclick="renderTimelineServer()" class="render">Export MP4</button>
                    </div>
                </section>
            </div>

            <section class="timeline-section">
                <div class="timeline-toolbar">
                    <div class="timeline-name">
                        <span class="tab active">Wan2GP Timeline</span>
                        <span class="muted" id="projectState">Unsaved</span>
                        <span class="muted" id="snapState">Snap: on</span>
                        <span class="muted" id="playheadLabel">00:00:00.00</span>
                    </div>
                    <div class="timeline-tools">
                        <button onclick="addVideoTrack()" class="icon">+ Video Track</button>
                        <button onclick="toggleSnap()" class="icon">Snap</button>
                        <button onclick="zoomOut()" class="icon">-</button>
                        <span id="zoomLabel">1x</span>
                        <button onclick="zoomIn()" class="icon">+</button>
                    </div>
                </div>

                <div class="scrubbar">
                    <input id="scrubInput" type="range" min="0" max="30" step="0.01" value="0" oninput="setPlayhead(Number(this.value), true)">
                </div>

                <div class="timeline-scroll-shell">
                    <div class="timeline-ruler" id="timelineRuler"></div>
                    <div class="tracks" id="tracksRoot"></div>
                    <div id="playhead" class="playhead"></div>
                </div>
            </section>
        </section>

        <aside class="inspector-panel">
            <h2>Inspector</h2>

            <div class="transition-box">
                <h3>Transitions</h3>
                <div class="transition-grid">
                    <button onclick="setSelectedTransition('fade')">Fade</button>
                    <button onclick="setSelectedTransition('crossfade')">Crossfade</button>
                    <button onclick="setSelectedTransition('blur')">Blur</button>
                    <button onclick="setSelectedTransition('blur_crossfade')">Blur cross</button>
                    <button onclick="setSelectedTransition('white_flash')">White flash</button>
                    <button onclick="setSelectedTransition('light_flash')">Light flash</button>
                    <button onclick="setSelectedTransition('none')" class="ghost">None</button>
                </div>
                <div class="small">Select a clip, then choose a transition. Transitions are shown on clips and used by ffmpeg export.</div>
            </div>

            <div id="inspectorContent" class="inspector-content">Select an asset or timeline item.</div>
            <div id="renderStatus" class="render-status"></div>
        </aside>
    </main>
</div>

<script>
const TOKEN_QUERY = "__TOKEN_QUERY__";
const TOKEN_VALUE = "__TOKEN_VALUE__";
let ASSETS = __ASSETS_JSON__;

const MAX_VIDEO_TRACKS = 10;
let visibleVideoTracks = 3;

let selectedAsset = null;
let selectedTimelineItemId = null;
let activeFilter = "all";
let timeline = [];
let zoom = 1;
let snapEnabled = true;
let currentTime = 0;
let isPlaying = false;
let playbackTimer = null;
let mouseEdit = null;

const pxPerSecondBase = 58;
const snapSeconds = 0.12;

function loadProject() {
    const saved = localStorage.getItem("wan2gp_editor_timeline_v4");
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            timeline = parsed.timeline || parsed || [];
            visibleVideoTracks = parsed.visibleVideoTracks || computeNeededVideoTracks();
            document.getElementById("projectState").innerText = "Loaded from browser";
        } catch(e) {
            timeline = [];
        }
    }
}

function saveProject() {
    localStorage.setItem("wan2gp_editor_timeline_v4", JSON.stringify({timeline, visibleVideoTracks}));
    document.getElementById("projectState").innerText = "Saved";
}

function clearTimeline() {
    if (!confirm("Clear browser timeline?")) return;
    timeline = [];
    selectedTimelineItemId = null;
    currentTime = 0;
    visibleVideoTracks = 3;
    saveProject();
    renderTimeline();
    setPlayhead(0, true);
}

function computeNeededVideoTracks() {
    let needed = 3;
    timeline.forEach(item => {
        if (String(item.track || "").startsWith("V")) {
            const n = Number(String(item.track).replace("V", ""));
            if (n > needed) needed = n;
        }
    });
    return Math.min(MAX_VIDEO_TRACKS, Math.max(3, needed));
}

function addVideoTrack() {
    visibleVideoTracks = Math.min(MAX_VIDEO_TRACKS, visibleVideoTracks + 1);
    renderTimeline();
    saveProject();
}

function filterAssets(filter, event) {
    activeFilter = filter;
    document.querySelectorAll(".asset-tabs button").forEach(btn => btn.classList.remove("active"));
    if (event && event.target) event.target.classList.add("active");
    renderAssets();
}

function assetMatchesFilter(asset) {
    if (activeFilter === "all") return true;
    if (activeFilter === "video") return asset.kind === "video";
    if (activeFilter === "audio") return asset.kind === "audio";
    if (activeFilter === "image") return asset.kind === "image";
    if (activeFilter === "local") return asset.origin === "local";
    if (activeFilter === "generated") return asset.origin === "generated";
    return true;
}

function renderAssets() {
    const search = document.getElementById("assetSearch").value.toLowerCase();
    const grid = document.getElementById("assetsGrid");
    const filtered = ASSETS.filter(asset => {
        const haystack = `${asset.filename} ${asset.prompt} ${asset.mode} ${asset.source} ${asset.kind}`.toLowerCase();
        return assetMatchesFilter(asset) && haystack.includes(search);
    });

    document.getElementById("assetCount").innerText = filtered.length;
    grid.innerHTML = "";

    if (filtered.length === 0) {
        grid.innerHTML = `<div class="empty">No asset found.<br>Import files or generate videos first.</div>`;
        return;
    }

    filtered.forEach((asset) => {
        const card = document.createElement("div");
        card.className = "asset-card";
        card.draggable = true;
        card.onclick = () => selectAsset(asset);
        card.ondragstart = (ev) => {
            ev.dataTransfer.setData("application/json", JSON.stringify(asset));
            ev.dataTransfer.effectAllowed = "copy";
        };

        card.innerHTML = `
            <div class="thumb ${asset.kind}">
                ${renderAssetThumb(asset)}
                <span class="kind">${asset.kind}</span>
            </div>
            <div class="asset-title">${escapeHtml(asset.filename)}</div>
            <div class="asset-meta">${escapeHtml(asset.source)} · ${escapeHtml(asset.mode || asset.origin)}</div>
        `;
        grid.appendChild(card);
    });
}

function renderAssetThumb(asset) {
    if (asset.kind === "video") return `<video muted preload="metadata" src="${asset.url}"></video>`;
    if (asset.kind === "audio") return `<div class="audio-thumb">♫</div>`;
    if (asset.kind === "image") return `<img src="${asset.url}" alt="">`;
    return `<div class="audio-thumb">?</div>`;
}

function selectAsset(asset) {
    selectedAsset = asset;
    selectedTimelineItemId = null;

    document.getElementById("clipName").innerText = asset.filename;

    const clipViewer = document.getElementById("clipViewer");
    const audioViewer = document.getElementById("audioViewer");
    const imageViewer = document.getElementById("imageViewer");

    clipViewer.style.display = "none";
    audioViewer.style.display = "none";
    imageViewer.style.display = "none";
    clipViewer.pause();
    audioViewer.pause();

    if (asset.kind === "video") {
        clipViewer.src = asset.url;
        clipViewer.style.display = "block";
        clipViewer.onloadedmetadata = () => {
            const duration = clipViewer.duration || Number(asset.source_duration || asset.duration_seconds || 0) || 4;
            asset.source_duration = duration;
            setTrimDefaults(duration);
        };
        clipViewer.load();
    } else if (asset.kind === "audio") {
        audioViewer.src = asset.url;
        audioViewer.style.display = "block";
        audioViewer.onloadedmetadata = () => {
            const duration = audioViewer.duration || 4;
            asset.source_duration = duration;
            setTrimDefaults(duration);
        };
        audioViewer.load();
    } else if (asset.kind === "image") {
        imageViewer.src = asset.url;
        imageViewer.style.display = "block";
        asset.source_duration = Number(asset.source_duration || 4);
        setTrimDefaults(asset.source_duration);
    }

    renderInspectorForAsset(asset);
}

function setTrimDefaults(duration) {
    const safeDuration = Math.max(0.1, Number(duration || 4));
    document.getElementById("trimStart").value = 0;
    document.getElementById("trimEnd").value = safeDuration.toFixed(2);
}

function updateTrimPreview() {
    if (!selectedAsset) return;
    const start = Number(document.getElementById("trimStart").value || 0);
    const max = getSourceDuration(selectedAsset);
    const trimEndInput = document.getElementById("trimEnd");
    if (Number(trimEndInput.value) > max) trimEndInput.value = max.toFixed(2);

    if (selectedAsset.kind === "video") {
        const viewer = document.getElementById("clipViewer");
        if (!isNaN(start)) viewer.currentTime = Math.min(start, max);
    }
    if (selectedAsset.kind === "audio") {
        const viewer = document.getElementById("audioViewer");
        if (!isNaN(start)) viewer.currentTime = Math.min(start, max);
    }
}

function renderInspectorForAsset(asset) {
    document.getElementById("inspectorContent").innerHTML = `
        <div class="field"><label>Filename</label><div>${escapeHtml(asset.filename)}</div></div>
        <div class="field"><label>Kind</label><div>${escapeHtml(asset.kind)}</div></div>
        <div class="field"><label>Origin</label><div>${escapeHtml(asset.origin)}</div></div>
        <div class="field"><label>Source</label><div>${escapeHtml(asset.source)}</div></div>
        <div class="field"><label>Source duration</label><div>${escapeHtml(formatSeconds(asset.source_duration || asset.duration_seconds || ""))}</div></div>
        <div class="field"><label>Prompt</label><div class="prompt-box">${escapeHtml(asset.prompt || "")}</div></div>
    `;
}

function addSelectedToTimeline(trackName=null) {
    if (!selectedAsset) {
        alert("Select an asset first.");
        return;
    }

    const sourceDuration = getSourceDuration(selectedAsset);
    const start = clamp(Number(document.getElementById("trimStart").value || 0), 0, sourceDuration);
    const end = clamp(Number(document.getElementById("trimEnd").value || sourceDuration), start + 0.05, sourceDuration);
    const timelineStart = snapTime(Math.max(0, Number(document.getElementById("timelineStart").value || getNextTimelineStart())));
    const inferredTrack = trackName || inferTrack(selectedAsset);

    timeline.push({
        id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
        ...selectedAsset,
        track: inferredTrack,
        source_duration: sourceDuration,
        trim_start: round2(start),
        trim_end: round2(end),
        timeline_start: round2(timelineStart),
        duration: round2(Math.max(0.05, end - start)),
        transition_in: "none",
        transition_out: "none",
        transition_duration: 0.35
    });

    selectedTimelineItemId = timeline[timeline.length - 1].id;

    if (String(inferredTrack).startsWith("V")) {
        visibleVideoTracks = Math.max(visibleVideoTracks, Number(String(inferredTrack).replace("V", "")));
    }

    renderTimeline();
    saveProject();
}

function getSourceDuration(asset) {
    return Math.max(0.1, Number(asset.source_duration || asset.duration_seconds || 4));
}

function inferTrack(asset) {
    if (asset.kind === "audio") return "A1";
    if (asset.kind === "image") return "V2";
    return "V1";
}

function getNextTimelineStart() {
    if (timeline.length === 0) return 0;
    let maxEnd = 0;
    timeline.forEach(item => {
        maxEnd = Math.max(maxEnd, Number(item.timeline_start || 0) + Number(item.duration || 0));
    });
    return round2(maxEnd);
}

function removeTimelineItem(id) {
    timeline = timeline.filter(item => item.id !== id);
    if (selectedTimelineItemId === id) selectedTimelineItemId = null;
    renderTimeline();
    saveProject();
}

function setSelectedTransition(transition) {
    if (!selectedTimelineItemId) {
        alert("Select a clip first.");
        return;
    }
    const item = timeline.find(x => x.id === selectedTimelineItemId);
    if (!item) return;
    item.transition_in = transition;
    item.transition_out = transition;
    if (!item.transition_duration) item.transition_duration = 0.35;
    renderTimeline();
    selectTimelineItem(item.id, false);
    saveProject();
}

function updateTimelineItem(id, field, value) {
    const item = timeline.find(x => x.id === id);
    if (!item) return;

    if (["trim_start", "trim_end", "timeline_start", "transition_duration"].includes(field)) {
        item[field] = round2(Math.max(0, Number(value || 0)));
        clampTrimToSource(item);
    } else {
        item[field] = value;
    }

    if (field === "track" && String(value).startsWith("V")) {
        visibleVideoTracks = Math.max(visibleVideoTracks, Number(String(value).replace("V", "")));
    }

    renderTimeline();
    saveProject();
    selectTimelineItem(item.id, false);
}

function clampTrimToSource(item) {
    const maxDuration = getSourceDuration(item);
    item.trim_start = clamp(Number(item.trim_start || 0), 0, maxDuration - 0.05);
    item.trim_end = clamp(Number(item.trim_end || maxDuration), item.trim_start + 0.05, maxDuration);
    item.duration = round2(Math.max(0.05, item.trim_end - item.trim_start));
}

function renderTimeline() {
    visibleVideoTracks = Math.max(visibleVideoTracks, computeNeededVideoTracks());
    const tracksRoot = document.getElementById("tracksRoot");
    tracksRoot.innerHTML = "";

    for (let i = MAX_VIDEO_TRACKS; i >= 1; i--) {
        const hasItems = timeline.some(item => item.track === `V${i}`);
        if (i > visibleVideoTracks && !hasItems) continue;
        addTrackDom(`V${i}`, i === 1 ? "Video" : "Overlay");
    }

    addTrackDom("A1", "Audio");
    addTrackDom("A2", "Music");

    const pxPerSecond = pxPerSecondBase * zoom;

    timeline.forEach((item) => {
        const track = document.getElementById("track" + item.track);
        if (!track) return;

        const width = Math.max(18, Number(item.duration || 4) * pxPerSecond);
        const left = Number(item.timeline_start || 0) * pxPerSecond;

        const clip = document.createElement("div");
        clip.className = `clip ${item.kind} ${selectedTimelineItemId === item.id ? "selected" : ""}`;
        clip.style.width = width + "px";
        clip.style.left = left + "px";
        clip.dataset.id = item.id;
        clip.onmousedown = (ev) => startClipMouseEdit(ev, item.id, "move");

        clip.innerHTML = `
            <div class="resize-handle left" onmousedown="event.stopPropagation(); startClipMouseEdit(event, '${item.id}', 'trim-left')"></div>
            <div class="clip-thumb">${renderTimelineThumb(item)}</div>
            <div class="clip-text">${escapeHtml(item.filename)}<br><span>${Number(item.trim_start).toFixed(2)}s to ${Number(item.trim_end).toFixed(2)}s · ${escapeHtml(item.transition_in || "none")}</span></div>
            <div class="clip-actions"><button onclick="event.stopPropagation(); removeTimelineItem('${item.id}')">×</button></div>
            <div class="resize-handle right" onmousedown="event.stopPropagation(); startClipMouseEdit(event, '${item.id}', 'trim-right')"></div>
        `;
        track.appendChild(clip);
    });

    updateTimelineLengthUi();
    renderRuler();
    renderPlayhead();
    setupTimelineScrubDrag();
}

function addTrackDom(name, label) {
    const root = document.getElementById("tracksRoot");

    const labelDiv = document.createElement("div");
    labelDiv.className = "track-label";
    labelDiv.innerHTML = `<strong>${name}</strong><span>${label}</span>`;

    const trackDiv = document.createElement("div");
    trackDiv.className = name.startsWith("A") ? "track audio-track" : "track video-track";
    trackDiv.id = "track" + name;
    trackDiv.dataset.track = name;
    setupTrackDrop(trackDiv);

    root.appendChild(labelDiv);
    root.appendChild(trackDiv);
}

function renderTimelineThumb(item) {
    if (item.kind === "video") return `<video muted preload="metadata" src="${item.url}"></video>`;
    if (item.kind === "image") return `<img src="${item.url}" alt="">`;
    if (item.kind === "audio") return `<div class="audio-symbol">♫</div>`;
    return `<div>?</div>`;
}

function setupTrackDrop(trackElement) {
    trackElement.ondragover = (ev) => {
        ev.preventDefault();
        trackElement.classList.add("drop-hover");
    };

    trackElement.ondragleave = () => trackElement.classList.remove("drop-hover");

    trackElement.ondrop = (ev) => {
        ev.preventDefault();
        trackElement.classList.remove("drop-hover");

        const assetJson = ev.dataTransfer.getData("application/json");
        const trackName = trackElement.dataset.track;
        const droppedStart = timeFromMouseEvent(ev, trackElement);

        if (assetJson) {
            selectedAsset = JSON.parse(assetJson);
            setDefaultTrimForAsset(selectedAsset);
            document.getElementById("timelineStart").value = snapTime(droppedStart);
            addSelectedToTimeline(trackName);
        }
    };
}

function setDefaultTrimForAsset(asset) {
    const duration = getSourceDuration(asset);
    document.getElementById("trimStart").value = 0;
    document.getElementById("trimEnd").value = duration.toFixed(2);
}

function timeFromMouseEvent(ev, trackElement) {
    const rect = trackElement.getBoundingClientRect();
    const x = Math.max(0, ev.clientX - rect.left + trackElement.scrollLeft);
    return round2(x / (pxPerSecondBase * zoom));
}

function startClipMouseEdit(ev, id, mode) {
    ev.preventDefault();

    const item = timeline.find(x => x.id === id);
    if (!item) return;

    selectedTimelineItemId = id;

    mouseEdit = {
        id,
        mode,
        startX: ev.clientX,
        originalTimelineStart: Number(item.timeline_start || 0),
        originalTrimStart: Number(item.trim_start || 0),
        originalTrimEnd: Number(item.trim_end || 0),
        originalDuration: Number(item.duration || 0),
        sourceDuration: getSourceDuration(item)
    };

    document.body.classList.add("editing-timeline");
    window.addEventListener("mousemove", onClipMouseMove);
    window.addEventListener("mouseup", stopClipMouseEdit);
    selectTimelineItem(id, false);
}

function onClipMouseMove(ev) {
    if (!mouseEdit) return;

    const item = timeline.find(x => x.id === mouseEdit.id);
    if (!item) return;

    const deltaPx = ev.clientX - mouseEdit.startX;
    const deltaTime = deltaPx / (pxPerSecondBase * zoom);

    if (mouseEdit.mode === "move") {
        item.timeline_start = round2(snapTime(Math.max(0, mouseEdit.originalTimelineStart + deltaTime), item.id));
    }

    if (mouseEdit.mode === "trim-left") {
        const newTrimStart = clamp(mouseEdit.originalTrimStart + deltaTime, 0, mouseEdit.originalTrimEnd - 0.05);
        const trimDelta = newTrimStart - mouseEdit.originalTrimStart;
        item.trim_start = round2(newTrimStart);
        item.timeline_start = round2(snapTime(Math.max(0, mouseEdit.originalTimelineStart + trimDelta), item.id));
        item.duration = round2(Math.max(0.05, item.trim_end - item.trim_start));
    }

    if (mouseEdit.mode === "trim-right") {
        const newTrimEnd = clamp(mouseEdit.originalTrimEnd + deltaTime, item.trim_start + 0.05, mouseEdit.sourceDuration);
        item.trim_end = round2(newTrimEnd);
        item.duration = round2(Math.max(0.05, item.trim_end - item.trim_start));
    }

    renderTimeline();
}

function stopClipMouseEdit() {
    if (!mouseEdit) return;

    window.removeEventListener("mousemove", onClipMouseMove);
    window.removeEventListener("mouseup", stopClipMouseEdit);
    document.body.classList.remove("editing-timeline");

    const id = mouseEdit.id;
    mouseEdit = null;
    selectTimelineItem(id, false);
    saveProject();
}

function snapTime(time, movingId=null) {
    if (!snapEnabled) return round2(time);

    let candidates = [0, currentTime];

    timeline.forEach(item => {
        if (item.id === movingId) return;
        const start = Number(item.timeline_start || 0);
        const end = start + Number(item.duration || 0);
        candidates.push(start, end);
    });

    for (const candidate of candidates) {
        if (Math.abs(time - candidate) <= snapSeconds) return round2(candidate);
    }

    return round2(Math.round(time / 0.05) * 0.05);
}

function toggleSnap() {
    snapEnabled = !snapEnabled;
    document.getElementById("snapState").innerText = snapEnabled ? "Snap: on" : "Snap: off";
}

function selectTimelineItem(id, doRender=true) {
    const item = timeline.find(x => x.id === id);
    if (!item) return;

    selectedTimelineItemId = id;
    if (doRender) setPlayhead(Number(item.timeline_start || 0), true);

    const trackOptions = [];
    for (let i = 1; i <= MAX_VIDEO_TRACKS; i++) {
        trackOptions.push(`<option value="V${i}" ${item.track === `V${i}` ? "selected" : ""}>V${i}</option>`);
    }
    trackOptions.push(`<option value="A1" ${item.track === "A1" ? "selected" : ""}>A1 Audio</option>`);
    trackOptions.push(`<option value="A2" ${item.track === "A2" ? "selected" : ""}>A2 Music</option>`);

    document.getElementById("inspectorContent").innerHTML = `
        <div class="field"><label>Filename</label><div>${escapeHtml(item.filename)}</div></div>
        <div class="field"><label>Kind</label><div>${escapeHtml(item.kind)}</div></div>
        <div class="field"><label>Track</label><select onchange="updateTimelineItem('${item.id}', 'track', this.value)">${trackOptions.join("")}</select></div>
        <div class="field"><label>Timeline start</label><input type="number" step="0.01" value="${item.timeline_start}" onchange="updateTimelineItem('${item.id}', 'timeline_start', this.value)"></div>
        <div class="field"><label>Trim start</label><input type="number" step="0.01" value="${item.trim_start}" onchange="updateTimelineItem('${item.id}', 'trim_start', this.value)"></div>
        <div class="field"><label>Trim end</label><input type="number" step="0.01" value="${item.trim_end}" onchange="updateTimelineItem('${item.id}', 'trim_end', this.value)"></div>
        <div class="field"><label>Transition in/out</label><select onchange="updateTimelineItem('${item.id}', 'transition_in', this.value); updateTimelineItem('${item.id}', 'transition_out', this.value);">${transitionOptions(item.transition_in)}</select></div>
        <div class="field"><label>Transition duration</label><input type="number" step="0.05" value="${item.transition_duration || 0.35}" onchange="updateTimelineItem('${item.id}', 'transition_duration', this.value)"></div>
        <div class="field"><label>Source max</label><div>${formatSeconds(getSourceDuration(item))}</div></div>
        <div class="field"><label>Clip duration</label><div>${Number(item.duration || 0).toFixed(2)}s</div></div>
        <div class="field"><label>Prompt</label><div class="prompt-box">${escapeHtml(item.prompt || "")}</div></div>
    `;

    if (doRender) renderTimeline();
}

function transitionOptions(selected) {
    const values = [
        ["none", "None"],
        ["fade", "Fade"],
        ["crossfade", "Crossfade"],
        ["blur", "Blur"],
        ["blur_crossfade", "Blur crossfade"],
        ["white_flash", "White flash"],
        ["light_flash", "Light flash"]
    ];
    return values.map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`).join("");
}

function setPlayhead(time, preview=true) {
    currentTime = clamp(time, 0, getTimelineMaxEnd());
    document.getElementById("scrubInput").value = currentTime;
    document.getElementById("playheadLabel").innerText = formatTimecode(currentTime);
    document.getElementById("programTime").innerText = formatTimecode(currentTime);
    renderPlayhead();
    if (preview) previewAtTime(currentTime);
}

function renderPlayhead() {
    const playhead = document.getElementById("playhead");
    const left = 118 + currentTime * pxPerSecondBase * zoom;
    playhead.style.left = left + "px";
}

function setupTimelineScrubDrag() {
    const shell = document.querySelector(".timeline-scroll-shell");
    shell.onmousedown = (ev) => {
        if (!ev.target.classList.contains("timeline-ruler")) return;
        const rect = shell.getBoundingClientRect();
        const x = ev.clientX - rect.left + shell.scrollLeft - 118;
        setPlayhead(round2(Math.max(0, x / (pxPerSecondBase * zoom))), true);

        const move = (moveEv) => {
            const xx = moveEv.clientX - rect.left + shell.scrollLeft - 118;
            setPlayhead(round2(Math.max(0, xx / (pxPerSecondBase * zoom))), true);
        };
        const up = () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", up);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", up);
    };
}

function previewAtTime(time) {
    const visual = getTopVisualAtTime(time);
    const audio = getAudioAtTime(time);

    const v = document.getElementById("timelineViewer");
    const a = document.getElementById("timelineAudioViewer");
    const img = document.getElementById("timelineImageViewer");
    const empty = document.getElementById("emptyPreview");

    v.style.display = "none";
    a.style.display = "none";
    img.style.display = "none";
    empty.style.display = "none";
    v.pause();
    a.pause();

    if (visual) {
        const sourceTime = Number(visual.trim_start || 0) + (time - Number(visual.timeline_start || 0));
        if (visual.kind === "video") {
            v.src = visual.url;
            v.style.display = "block";
            v.onloadedmetadata = () => { v.currentTime = clamp(sourceTime, 0, getSourceDuration(visual)); };
            v.load();
        } else if (visual.kind === "image") {
            img.src = visual.url;
            img.style.display = "block";
        }
    } else {
        empty.style.display = "grid";
    }

    if (audio) {
        const audioTime = Number(audio.trim_start || 0) + (time - Number(audio.timeline_start || 0));
        a.src = audio.url;
        a.onloadedmetadata = () => { a.currentTime = clamp(audioTime, 0, getSourceDuration(audio)); };
        a.load();
    }
}

function getTopVisualAtTime(time) {
    const active = timeline.filter(item => {
        if (!["video", "image"].includes(item.kind)) return false;
        const start = Number(item.timeline_start || 0);
        const end = start + Number(item.duration || 0);
        return time >= start && time <= end;
    });

    if (active.length === 0) return null;

    active.sort((a, b) => {
        const ta = Number(String(a.track || "V1").replace("V", "")) || 1;
        const tb = Number(String(b.track || "V1").replace("V", "")) || 1;
        return tb - ta;
    });

    return active[0];
}

function getAudioAtTime(time) {
    return timeline.find(item => {
        if (item.kind !== "audio") return false;
        const start = Number(item.timeline_start || 0);
        const end = start + Number(item.duration || 0);
        return time >= start && time <= end;
    });
}

function goToStart() {
    pausePlayback();
    setPlayhead(0, true);
}

function seekRelative(delta) {
    setPlayhead(currentTime + delta, true);
}

function togglePlayback() {
    if (isPlaying) pausePlayback();
    else startPlayback();
}

function startPlayback() {
    isPlaying = true;
    document.getElementById("playPauseButton").innerText = "⏸";
    clearInterval(playbackTimer);

    const last = { t: performance.now() };
    playbackTimer = setInterval(() => {
        const now = performance.now();
        const delta = (now - last.t) / 1000;
        last.t = now;

        const max = getTimelineMaxEnd();
        if (currentTime >= max) {
            pausePlayback();
            return;
        }

        currentTime = clamp(currentTime + delta, 0, max);
        document.getElementById("scrubInput").value = currentTime;
        document.getElementById("playheadLabel").innerText = formatTimecode(currentTime);
        document.getElementById("programTime").innerText = formatTimecode(currentTime);
        renderPlayhead();

        const visual = getTopVisualAtTime(currentTime);
        if (visual && visual.kind === "video") {
            const v = document.getElementById("timelineViewer");
            if (v.src !== visual.url) previewAtTime(currentTime);
            if (v.paused) v.play().catch(() => {});
        } else {
            previewAtTime(currentTime);
        }
    }, 120);
}

function pausePlayback() {
    isPlaying = false;
    document.getElementById("playPauseButton").innerText = "▶";
    clearInterval(playbackTimer);
    document.getElementById("timelineViewer").pause();
    document.getElementById("timelineAudioViewer").pause();
}

function previewSelectedTimelineItem() {
    if (!selectedTimelineItemId) {
        alert("Select a timeline item first.");
        return;
    }
    const item = timeline.find(x => x.id === selectedTimelineItemId);
    if (item) setPlayhead(Number(item.timeline_start || 0), true);
}

function exportPlan() {
    const plan = buildPlan();
    const blob = new Blob([JSON.stringify(plan, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "wan2gp_timeline_plan.json";
    a.click();
    URL.revokeObjectURL(url);
}

function buildPlan() {
    return {
        type: "wan2gp_studio_timeline_plan",
        version: 4,
        created_at: new Date().toISOString(),
        render_hint: "ffmpeg",
        output: { width: 1280, height: 720, fps: 24 },
        clips: timeline
    };
}

async function renderTimelineServer() {
    if (timeline.length === 0) {
        alert("Timeline is empty.");
        return;
    }

    const status = document.getElementById("renderStatus");
    status.innerHTML = "Exporting MP4 with ffmpeg...";

    try {
        const response = await fetch("/studio/editor/render", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ token: TOKEN_VALUE, plan: buildPlan() })
        });

        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Render failed");

        status.innerHTML = `
            <div class="success">
                Export completed.<br>
                <a href="${data.download_url}" target="_blank">Download final MP4</a><br>
                <span class="small">The export is not added to the asset library.</span>
            </div>
        `;
    } catch (err) {
        status.innerHTML = `<div class="error">Export failed: ${escapeHtml(err.message)}</div>`;
    }
}

function zoomIn() {
    zoom = Math.min(4, zoom + 0.25);
    document.getElementById("zoomLabel").innerText = `${zoom}x`;
    renderTimeline();
}

function zoomOut() {
    zoom = Math.max(0.25, zoom - 0.25);
    document.getElementById("zoomLabel").innerText = `${zoom}x`;
    renderTimeline();
}

function renderRuler() {
    const ruler = document.getElementById("timelineRuler");
    ruler.innerHTML = "";
    const total = Math.max(30, getTimelineMaxEnd() + 10);
    const pxPerSecond = pxPerSecondBase * zoom;

    for (let i = 0; i <= total; i += 1) {
        const mark = document.createElement("div");
        mark.className = i % 5 === 0 ? "ruler-mark major" : "ruler-mark";
        mark.style.left = (118 + i * pxPerSecond) + "px";
        mark.innerText = i % 5 === 0 ? `00:00:${String(i).padStart(2, "0")}` : "|";
        ruler.appendChild(mark);
    }
}

function getTimelineMaxEnd() {
    let maxEnd = 30;
    timeline.forEach(item => {
        maxEnd = Math.max(maxEnd, Number(item.timeline_start || 0) + Number(item.duration || 0));
    });
    return Math.ceil(maxEnd);
}

function updateTimelineLengthUi() {
    const max = getTimelineMaxEnd();
    const scrub = document.getElementById("scrubInput");
    scrub.max = max;
    document.getElementById("timelineDuration").innerText = `${timeline.length} items · ${formatSeconds(max)}`;
}

async function uploadAssets() {
    const input = document.getElementById("assetUploadInput");
    if (!input.files || input.files.length === 0) return;

    const status = document.getElementById("uploadStatus");
    status.innerText = "Uploading...";

    const form = new FormData();
    form.append("token", TOKEN_VALUE);
    for (const file of input.files) form.append("files", file);

    try {
        const response = await fetch("/studio/editor/upload", {method: "POST", body: form});
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        status.innerText = `Uploaded ${data.uploaded.length} file(s). Refreshing...`;
        window.location.reload();
    } catch (err) {
        status.innerText = "Upload failed: " + err.message;
    }
}

function setupUploadDrop() {
    const drop = document.getElementById("uploadDrop");
    const input = document.getElementById("assetUploadInput");

    drop.ondragover = (ev) => {
        ev.preventDefault();
        drop.classList.add("drop-hover");
    };

    drop.ondragleave = () => drop.classList.remove("drop-hover");

    drop.ondrop = async (ev) => {
        ev.preventDefault();
        drop.classList.remove("drop-hover");
        if (!ev.dataTransfer.files || ev.dataTransfer.files.length === 0) return;
        const dt = new DataTransfer();
        for (const file of ev.dataTransfer.files) dt.items.add(file);
        input.files = dt.files;
        await uploadAssets();
    };
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function round2(value) {
    return Math.round(Number(value) * 100) / 100;
}

function formatSeconds(value) {
    if (value === "" || value === null || value === undefined) return "";
    return `${Number(value).toFixed(2)}s`;
}

function formatTimecode(seconds) {
    seconds = Math.max(0, Number(seconds || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const cs = Math.floor((seconds - Math.floor(seconds)) * 100);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

loadProject();
setupUploadDrop();
renderAssets();
renderTimeline();
setPlayhead(0, false);
</script>
</body>
</html>
'''

EDITOR_CSS = r'''
:root {
    --bg: #090b10;
    --panel: #121722;
    --panel2: #1b2230;
    --panel3: #0e131c;
    --line: #2a3344;
    --text: #f4f7fb;
    --muted: #8993a5;
    --blue: #4f7cff;
    --blue2: #315de8;
    --green: #22c55e;
    --yellow: #fbbf24;
    --red: #ef4444;
    --clip: #203a78;
    --clipBorder: #5e87ff;
    --audio: #14532d;
    --audioBorder: #22c55e;
    --image: #4c1d95;
    --imageBorder: #a78bfa;
}
* { box-sizing: border-box; }
html, body {
    height: 100%;
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Inter, Segoe UI, Arial, Helvetica, sans-serif;
    overflow: hidden;
}
a { color: inherit; text-decoration: none; }
button {
    border: 0;
    border-radius: 10px;
    background: linear-gradient(180deg, var(--blue), var(--blue2));
    color: white;
    padding: 8px 11px;
    font-weight: 750;
    cursor: pointer;
    box-shadow: 0 8px 18px rgba(0,0,0,.20);
}
button:hover { filter: brightness(1.08); }
button.ghost, .ghost { background: #2a3242; color: #d1d5db; }
button.render { background: linear-gradient(180deg, #22c55e, #15803d); }
button.icon { padding: 6px 10px; background: #252d3a; }
.app { height: 100vh; display: flex; flex-direction: column; }
.topbar {
    height: 66px;
    flex: 0 0 66px;
    background: rgba(15, 18, 25, .96);
    border-bottom: 1px solid var(--line);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 18px;
}
.brand { display: flex; align-items: center; gap: 12px; }
.logo {
    width: 36px;
    height: 36px;
    border-radius: 12px;
    background: radial-gradient(circle at top left, #70a5ff, #1e3a8a 60%, #111827);
    display: grid;
    place-items: center;
    font-weight: 900;
}
.title { font-weight: 900; font-size: 16px; }
.subtitle { color: var(--muted); font-size: 12px; }
.topnav {
    display: flex;
    gap: 8px;
    background: rgba(255,255,255,.035);
    border: 1px solid rgba(255,255,255,.06);
    padding: 5px;
    border-radius: 14px;
}
.topnav a {
    padding: 9px 13px;
    border-radius: 10px;
    color: #cbd5e1;
    font-size: 14px;
    font-weight: 750;
}
.topnav a:hover { background: #222b3a; }
.topnav a.active { background: #eef2ff; color: #101827; }
.top-actions { display: flex; gap: 8px; }
.workspace {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 350px 1fr 340px;
    grid-template-rows: 1fr;
}
.assets-panel,
.inspector-panel {
    min-height: 0;
    background: var(--panel);
    border-right: 1px solid var(--line);
    padding: 14px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.inspector-panel { border-right: 0; border-left: 1px solid var(--line); }
.panel-title-row { display: flex; justify-content: space-between; align-items: center; }
h2 { margin: 0 0 12px; font-size: 17px; }
h3 { margin: 16px 0 8px; font-size: 14px; }
.pill { background: #293244; color: #cbd5e1; padding: 4px 8px; border-radius: 999px; font-size: 12px; }
.upload-box {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--panel3);
    padding: 10px;
    margin-bottom: 12px;
}
.upload-label { display: block; color: #d1d5db; font-size: 12px; font-weight: 800; margin-bottom: 8px; }
.upload-label input { width: 100%; margin-top: 7px; }
.upload-drop {
    margin-top: 8px;
    border: 1px dashed #3b4454;
    border-radius: 12px;
    padding: 12px;
    color: var(--muted);
    text-align: center;
    font-size: 12px;
}
.upload-drop.drop-hover { border-color: var(--blue); background: rgba(79,124,255,.12); }
.asset-tabs { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 10px; }
.asset-tabs button { background: #222b3a; color: #cbd5e1; padding: 7px; font-size: 12px; }
.asset-tabs button.active { background: var(--blue2); color: white; }
.search {
    width: 100%;
    padding: 10px;
    border: 1px solid var(--line);
    background: #090d14;
    color: white;
    border-radius: 12px;
    margin-bottom: 12px;
}
.assets-grid {
    overflow-y: auto;
    padding-right: 4px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}
.asset-card {
    background: #0d121b;
    border: 1px solid var(--line);
    border-radius: 14px;
    overflow: hidden;
    cursor: grab;
    box-shadow: 0 10px 20px rgba(0,0,0,.18);
}
.asset-card:hover { border-color: var(--blue); }
.thumb { position: relative; aspect-ratio: 16 / 9; background: #050505; overflow: hidden; }
.thumb video, .thumb img { width: 100%; height: 100%; object-fit: cover; }
.audio-thumb, .audio-symbol {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    color: #bbf7d0;
    font-size: 34px;
    background: radial-gradient(circle at center, #166534, #052e16);
}
.kind {
    position: absolute;
    left: 7px;
    bottom: 7px;
    background: rgba(0,0,0,.72);
    padding: 3px 6px;
    border-radius: 6px;
    font-size: 11px;
    text-transform: uppercase;
}
.asset-title { font-size: 12px; padding: 7px 7px 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.asset-meta { font-size: 11px; color: var(--muted); padding: 0 7px 8px; }
.empty { grid-column: span 2; color: var(--muted); padding: 18px; border: 1px dashed var(--line); border-radius: 12px; line-height: 1.4; }
.main-view { min-width: 0; min-height: 0; display: grid; grid-template-rows: minmax(320px, 48%) 1fr; }
.viewer-row { min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 10px; background: #080b10; }
.viewer-card {
    min-width: 0;
    min-height: 0;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    display: grid;
    grid-template-rows: 36px minmax(0, 1fr) auto;
    overflow: hidden;
    box-shadow: 0 15px 35px rgba(0,0,0,.25);
}
.viewer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 12px;
    border-bottom: 1px solid var(--line);
    color: #d1d5db;
    font-size: 13px;
    font-weight: 800;
}
.muted { color: var(--muted); font-weight: 500; font-size: 12px; }
.viewer-body {
    min-height: 0;
    max-width: 100%;
    overflow: hidden;
    background: #050505;
    display: grid;
    place-items: center;
    position: relative;
}
.viewer-body video, .viewer-body img { width: 100%; height: 100%; max-width: 100%; object-fit: contain; }
.viewer-body audio { width: 80%; }
.empty-preview { display: grid; place-items: center; color: var(--muted); height: 100%; width: 100%; }
#clipViewer, #audioViewer, #imageViewer, #timelineViewer, #timelineAudioViewer, #timelineImageViewer { display: none; }
.timeline-preview {
    background:
        linear-gradient(45deg, #050505 25%, transparent 25%),
        linear-gradient(-45deg, #050505 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #050505 75%),
        linear-gradient(-45deg, transparent 75%, #050505 75%);
    background-size: 24px 24px;
    background-color: #080808;
}
.viewer-controls, .trim-panel { border-top: 1px solid var(--line); padding: 8px 10px; }
.viewer-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 52px; }
.trim-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; align-items: end; }
.trim-grid label { color: var(--muted); font-size: 11px; }
.trim-grid input, .inspector-content input, .inspector-content select {
    width: 100%;
    padding: 7px;
    border: 1px solid var(--line);
    background: #090d14;
    color: white;
    border-radius: 8px;
}
.help, .small { color: var(--muted); font-size: 12px; line-height: 1.4; }
.timeline-section { min-height: 0; background: #080b10; border-top: 1px solid var(--line); display: grid; grid-template-rows: 42px 26px 1fr; }
.timeline-toolbar { display: flex; align-items: center; justify-content: space-between; background: #111721; border-bottom: 1px solid var(--line); padding: 0 10px; }
.timeline-name { display: flex; align-items: center; gap: 10px; }
.tab { background: #1e3a8a; color: white; border-radius: 9px; padding: 7px 11px; font-size: 13px; font-weight: 800; }
.timeline-tools { display: flex; align-items: center; gap: 8px; }
.scrubbar { background: #0d121b; border-bottom: 1px solid var(--line); padding: 4px 12px; }
.scrubbar input { width: 100%; }
.timeline-scroll-shell { position: relative; min-height: 0; overflow: auto; }
.timeline-ruler { position: relative; height: 28px; background: #11141c; border-bottom: 1px solid var(--line); min-width: 2800px; cursor: pointer; }
.ruler-mark { position: absolute; top: 10px; color: #5f6877; font-size: 9px; }
.ruler-mark.major { top: 7px; color: var(--muted); font-size: 11px; }
.tracks { min-height: 0; display: grid; grid-template-columns: 118px 1fr; grid-auto-rows: 68px; }
.track-label {
    background: #111721;
    border-right: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    padding: 10px 10px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    position: sticky;
    left: 0;
    z-index: 8;
}
.track-label strong { color: #dbeafe; }
.track-label span { color: var(--muted); font-size: 12px; }
.track {
    position: relative;
    min-width: 2800px;
    background: repeating-linear-gradient(to right, #0d0f14 0, #0d0f14 57px, #171d29 58px);
    border-bottom: 1px solid var(--line);
}
.track.drop-hover { background: repeating-linear-gradient(to right, rgba(79,124,255,.15) 0, rgba(79,124,255,.15) 57px, rgba(79,124,255,.30) 58px); }
.playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: #ef4444;
    z-index: 20;
    pointer-events: none;
    box-shadow: 0 0 0 1px rgba(239,68,68,.3), 0 0 15px rgba(239,68,68,.6);
}
.playhead::before {
    content: "";
    position: absolute;
    top: 0;
    left: -6px;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-top: 10px solid #ef4444;
}
.clip {
    position: absolute;
    top: 6px;
    height: 56px;
    background: var(--clip);
    border: 1px solid var(--clipBorder);
    border-radius: 10px;
    display: grid;
    grid-template-columns: 50px 1fr auto;
    overflow: hidden;
    min-width: 18px;
    cursor: grab;
    user-select: none;
    box-shadow: 0 10px 18px rgba(0,0,0,.22);
}
.clip.selected { outline: 2px solid #fbbf24; z-index: 5; }
.clip.audio { background: var(--audio); border-color: var(--audioBorder); }
.clip.image { background: var(--image); border-color: var(--imageBorder); }
.clip:hover { filter: brightness(1.16); }
.clip-thumb { background: black; pointer-events: none; }
.clip-thumb video, .clip-thumb img { width: 100%; height: 100%; object-fit: cover; }
.clip-text { font-size: 11px; padding: 6px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; pointer-events: none; }
.clip-text span { color: #cbd5e1; font-size: 10px; }
.clip-actions { display: flex; align-items: center; gap: 2px; padding-right: 12px; }
.clip-actions button { padding: 2px 5px; border-radius: 5px; background: rgba(0,0,0,.35); font-size: 11px; }
.resize-handle { position: absolute; top: 0; width: 9px; height: 100%; z-index: 10; background: rgba(255,255,255,.02); }
.resize-handle:hover { background: rgba(251,191,36,.4); }
.resize-handle.left { left: 0; cursor: ew-resize; }
.resize-handle.right { right: 0; cursor: ew-resize; }
.editing-timeline, .editing-timeline * { cursor: ew-resize !important; }
.inspector-content { color: #d1d5db; font-size: 13px; overflow-y: auto; }
.field { margin-bottom: 12px; }
.field label { display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; margin-bottom: 4px; }
.prompt-box { background: #090d14; border: 1px solid var(--line); border-radius: 10px; padding: 9px; line-height: 1.35; max-height: 180px; overflow-y: auto; }
.transition-box { background: var(--panel3); border: 1px solid var(--line); padding: 12px; border-radius: 14px; margin-bottom: 14px; }
.transition-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-bottom: 8px; }
.transition-grid button { padding: 7px; font-size: 12px; }
.render-status { margin-top: 12px; font-size: 13px; }
.success { background: rgba(34,197,94,.13); border: 1px solid rgba(34,197,94,.45); color: #bbf7d0; padding: 12px; border-radius: 12px; }
.login-wrap { max-width: 520px; margin: 80px auto; background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 24px; }
.login-wrap input { width: 100%; padding: 11px; border: 1px solid var(--line); background: #0b0d12; color: white; border-radius: 10px; margin-bottom: 12px; }
.error { background: rgba(239,68,68,.13); border: 1px solid rgba(239,68,68,.45); color: #fecaca; padding: 14px; border-radius: 14px; margin-bottom: 16px; }
@media (max-width: 1450px) {
    .workspace { grid-template-columns: 320px 1fr; }
    .inspector-panel { display: none; }
}
'''