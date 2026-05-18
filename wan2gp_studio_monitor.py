"""
Wan2GP Studio Monitor module.

Renders the global monitoring view inside /studio/monitor.
This module does not initialize Wan2GP and does not expose routes by itself.
It only renders HTML from job snapshots provided by the main server.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Optional


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def short_text(value: Any, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def basename_or_empty(value: Any) -> str:
    return Path(str(value)).name if value else ""


def status_badge_class(status: str) -> str:
    return f"status {status}" if status in {"queued", "running", "completed", "failed"} else "status unknown"


def mode_badge_class(api_mode: str) -> str:
    mapping = {
        "t2v": "mode t2v",
        "i2v": "mode i2v",
        "i2v_end": "mode i2v-end",
        "s2v": "mode s2v",
        "s2v_i2v": "mode s2v-i2v",
        "s2v_i2v_lora": "mode s2v-i2v-lora",
    }
    return mapping.get(api_mode, "mode unknown")


def format_mode_label(job: dict[str, Any]) -> str:
    labels = {
        "t2v": "Text to Video",
        "i2v": "Image to Video",
        "i2v_end": "Start Image + End Image",
        "s2v": "Sound to Video",
        "s2v_i2v": "Sound + Reference Image",
        "s2v_i2v_lora": "Sound + Reference Image + LoRA",
    }
    api_mode = job.get("api_mode", "")
    return labels.get(api_mode, job.get("mode") or "Unknown mode")


def is_active_job(job: dict[str, Any]) -> bool:
    return job.get("status") in {"queued", "running"}


def is_completed_job(job: dict[str, Any]) -> bool:
    return job.get("status") == "completed"


def is_failed_job(job: dict[str, Any]) -> bool:
    return job.get("status") == "failed"


def get_requester_ip(job: dict[str, Any]) -> str:
    return job.get("requester_ip") or job.get("client_ip") or job.get("remote_addr") or ""


def count_by_mode(jobs: list[dict[str, Any]], mode: str) -> int:
    return sum(1 for job in jobs if job.get("api_mode") == mode)


def count_studio_jobs(jobs: list[dict[str, Any]]) -> int:
    return sum(1 for job in jobs if bool(job.get("studio")))


def count_agent_jobs(jobs: list[dict[str, Any]]) -> int:
    return sum(1 for job in jobs if not bool(job.get("studio")))


def parse_datetime(value: Any):
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def format_date_value(value: Any) -> str:
    dt = parse_datetime(value)
    if not dt:
        return "" if value is None else str(value)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def format_duration_seconds(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def seconds_between_dates(start: Any, end: Any) -> Optional[int]:
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if not start_dt or not end_dt:
        return None
    diff = int((end_dt - start_dt).total_seconds())
    return diff if diff >= 0 else None


def generation_duration(job: dict[str, Any]) -> str:
    started = job.get("started_at")
    finished = job.get("finished_at")
    if not started:
        return ""
    if job.get("status") == "running":
        start_dt = parse_datetime(started)
        if not start_dt:
            return ""
        from datetime import datetime
        return format_duration_seconds(int((datetime.now() - start_dt).total_seconds())) + " running"
    diff = seconds_between_dates(started, finished)
    return "" if diff is None else format_duration_seconds(diff)


def first_download_url(job: dict[str, Any]) -> Optional[str]:
    download_urls = job.get("download_urls")
    if isinstance(download_urls, list) and download_urls:
        return str(download_urls[0])
    return None


def build_token_query(token: str | None) -> str:
    return "" if not token else f"?token={h(token)}"


def render_top_cards(jobs: list[dict[str, Any]], health: dict[str, Any] | None = None, model: dict[str, Any] | None = None) -> str:
    active_jobs = [j for j in jobs if is_active_job(j)]
    completed_jobs = [j for j in jobs if is_completed_job(j)]
    failed_jobs = [j for j in jobs if is_failed_job(j)]
    api_status = "OK" if not health or health.get("status") in {None, "ok"} else "KO"
    model_label = ""
    if model:
        model_label = model.get("display_name") or model.get("model_type") or ""
    return f"""
    <div class="top-grid">
        <div class="card metric"><div class="metric-title">API</div><div class="metric-value ok">{h(api_status)}</div><div class="small">{h(model_label)}</div></div>
        <div class="card metric"><div class="metric-title">Total jobs</div><div class="metric-value">{h(len(jobs))}</div></div>
        <div class="card metric"><div class="metric-title">Active</div><div class="metric-value">{h(len(active_jobs))}</div></div>
        <div class="card metric"><div class="metric-title">Completed</div><div class="metric-value">{h(len(completed_jobs))}</div></div>
        <div class="card metric"><div class="metric-title">Failed</div><div class="metric-value failed-text">{h(len(failed_jobs))}</div></div>
        <div class="card metric"><div class="metric-title">Studio jobs</div><div class="metric-value">{h(count_studio_jobs(jobs))}</div></div>
        <div class="card metric"><div class="metric-title">Agent/API jobs</div><div class="metric-value">{h(count_agent_jobs(jobs))}</div></div>
    </div>
    """


def render_mode_cards(jobs: list[dict[str, Any]]) -> str:
    modes = [
        ("t2v", "Text to Video"),
        ("i2v", "Image to Video"),
        ("i2v_end", "Start + End"),
        ("s2v", "Sound to Video"),
        ("s2v_i2v", "Sound + Image"),
        ("s2v_i2v_lora", "Sound + Image + LoRA"),
    ]
    cards = []
    for mode, label in modes:
        cards.append(f"""
        <div class="card mode-card">
            <div class="metric-title">{h(label)}</div>
            <div class="metric-value">{h(count_by_mode(jobs, mode))}</div>
            <div class="small">{h(mode)}</div>
        </div>
        """)
    return f"<div class='mode-grid'>{''.join(cards)}</div>"


def render_inputs(job: dict[str, Any]) -> str:
    lines = []
    for key, label in [("input_image", "Image"), ("input_image_start", "Start"), ("input_image_end", "End"), ("input_audio", "Audio")]:
        value = job.get(key)
        if value:
            lines.append(f"<div>{h(label)}: <span class='mono'>{h(basename_or_empty(value))}</span></div>")
    loras = job.get("activated_loras")
    if isinstance(loras, list) and loras:
        lines.append("<div>LoRA:</div>")
        for lora in loras:
            lines.append(f"<div class='mono'>{h(basename_or_empty(lora))}</div>")
        lines.append(f"<div>Multiplier: <span class='mono'>{h(job.get('loras_multipliers'))}</span></div>")
    return "".join(lines) if lines else '<span class="small">No input file</span>'


def render_download(job: dict[str, Any], token: str | None) -> str:
    download_url = first_download_url(job)
    if not download_url:
        return '<span class="small">Not ready</span>'
    job_id = job.get("job_id", "")
    filename = basename_or_empty(download_url)
    href = f"/studio/download/{h(job_id)}/{h(filename)}{build_token_query(token)}"
    return f'<a class="button small-button" href="{href}" target="_blank">Download MP4</a>'


def render_jobs_table(jobs: list[dict[str, Any]], token: str | None, max_prompt_length: int = 500) -> str:
    if not jobs:
        return '<div class="card">No job known for now.</div>'
    rows = []
    for job in jobs:
        status = job.get("status", "unknown")
        progress = max(0, min(100, float(job.get("progress") or 0)))
        api_mode = job.get("api_mode") or ""
        source = "Studio" if job.get("studio") else "Agent/API"
        requester_ip = get_requester_ip(job)
        job_id = job.get("job_id", "")
        real_duration = generation_duration(job)
        queue_html = f"<strong>#{h(job.get('queue_position'))}</strong>" if job.get("queue_position") is not None else '<span class="small">out of queue</span>'
        errors_html = ""
        if job.get("errors"):
            errors_html = f"<div class='small error-mini'>Errors:<pre>{h(job.get('errors'))}</pre></div>"
        files_html = ""
        files = job.get("files")
        if isinstance(files, list) and files:
            files_html = "".join(f"<div class='mono'>{h(file)}</div>" for file in files)
        prompt_html = h(short_text(job.get("prompt"), max_prompt_length)).replace("\n", "<br>")
        rows.append(f"""
        <tr>
            <td><span class="{h(status_badge_class(status))}">{h(status)}</span><div class="small">{h(job.get("short_status"))}</div></td>
            <td>{queue_html}</td>
            <td><span class="{h(mode_badge_class(api_mode))}">{h(api_mode or "legacy")}</span><div class="small" style="margin-top:6px;">{h(format_mode_label(job))}</div><div class="small">{h(job.get("mode"))}</div><div class="small source-label">{h(source)}</div></td>
            <td><div class="progress-wrap"><div class="progress-bar" style="width:{h(progress)}%;"></div></div><div class="progress-text">{h(progress)}%</div><div class="small">Phase: {h(job.get("phase"))}<br>Step: {h(job.get("current_step"))}/{h(job.get("total_steps"))}<br>Message: {h(job.get("message"))}</div></td>
            <td><div class="small">Resolution: <strong>{h(job.get("resolution"))}</strong><br>Requested video: <strong>{h(job.get("duration_seconds"))}s</strong><br>FPS: <strong>{h(job.get("fps"))}</strong><br>Seed: <span class="mono">{h(job.get("seed"))}</span><br>Job ID: <a class="mono" href="/studio/job/{h(job_id)}{build_token_query(token)}">{h(job_id)}</a></div></td>
            <td>{f'<span class="mono">{h(requester_ip)}</span>' if requester_ip else '<span class="small warn">Unknown</span>'}<div class="small">{h(job.get("requester_user_agent"))}</div></td>
            <td><div class="prompt">{prompt_html}</div></td>
            <td><div class="input-list small">{render_inputs(job)}</div>{errors_html}</td>
            <td><div class="small">Created: {h(format_date_value(job.get("created_at")))}<br>Started: {h(format_date_value(job.get("started_at")))}<br>Finished: {h(format_date_value(job.get("finished_at")))}<br>Updated: {h(format_date_value(job.get("updated_at")))}<br><br>Real duration: {f'<strong>{h(real_duration)}</strong>' if real_duration else '<span class="small">n/a</span>'}</div></td>
            <td>{render_download(job, token)}<div style="margin-top:8px;">{files_html}</div></td>
        </tr>
        """)
    return f"""
    <div class="table-wrap">
        <table class="monitor-table">
            <thead><tr><th>Status</th><th>Queue</th><th>Type</th><th>Progress</th><th>Request</th><th>Machine</th><th>Prompt</th><th>Inputs</th><th>Time</th><th>Result</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </div>
    """


def render_global_monitor_body(jobs: list[dict[str, Any]], token: str | None, nav_html: str, health: dict[str, Any] | None = None, model: dict[str, Any] | None = None, title: str = "Wan2GP Studio Monitor") -> str:
    jobs = list(jobs)
    jobs.sort(key=lambda x: x.get("sequence", 0), reverse=True)
    return f"""
    <h1>{h(title)}</h1>
    <div class="subtitle">Unified web console for Studio, agent jobs and global Wan2GP queue monitoring.</div>
    {nav_html}
    {render_top_cards(jobs=jobs, health=health, model=model)}
    {render_mode_cards(jobs)}
    <div class="section"><h2>Global queue and history</h2>{render_jobs_table(jobs=jobs, token=token)}</div>
    """


def monitor_extra_css() -> str:
    return """
.top-grid { display:grid; grid-template-columns:repeat(7,minmax(130px,1fr)); gap:12px; margin-bottom:18px; }
.mode-grid { display:grid; grid-template-columns:repeat(6,minmax(130px,1fr)); gap:12px; margin-bottom:22px; }
.metric-title { color:var(--muted); font-size:12px; margin-bottom:7px; text-transform:uppercase; letter-spacing:.04em; }
.metric-value { font-size:26px; font-weight:800; }
.failed-text { color:#fca5a5; }
.ok { color:#86efac; }
.source-label { margin-top:6px; color:#fde68a; }
.monitor-table th, .monitor-table td { font-size:13px; }
.input-list { margin-top:4px; padding:8px; background:var(--panel3); border-radius:10px; border:1px solid var(--border); }
.prompt { max-width:460px; line-height:1.35; }
.error-mini { margin-top:8px; color:#fecaca; }
.error-mini pre { white-space:pre-wrap; word-break:break-word; max-width:360px; }
.mode { display:inline-block; padding:5px 9px; border-radius:999px; font-size:12px; color:#050505; font-weight:800; white-space:nowrap; }
.mode.t2v { background:#a78bfa; }
.mode.i2v { background:#60a5fa; }
.mode.i2v-end { background:#34d399; }
.mode.s2v { background:#f472b6; }
.mode.s2v-i2v { background:#fbbf24; }
.mode.s2v-i2v-lora { background:#fb7185; }
.mode.unknown { background:#94a3b8; }
.small-button { padding:7px 10px; font-size:12px; }
@media (max-width:1500px) { .top-grid { grid-template-columns:repeat(3,minmax(130px,1fr)); } .mode-grid { grid-template-columns:repeat(3,minmax(130px,1fr)); } }
@media (max-width:900px) { .top-grid, .mode-grid { grid-template-columns:repeat(2,minmax(130px,1fr)); } }
"""
