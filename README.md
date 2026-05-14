
# Wan2GP Agentic Skill (LTX 2.3 Distilled 1.1)

Wan2GP Agentic Skill is a small LAN-oriented integration layer that allows AI agents to generate videos through a Windows PC running Wan2GP.

The goal is simple:

```text
AI Agent on Linux
        |
        | HTTP API
        v
Windows PC running Wan2GP
        |
        | GPU video generation
        v
Generated MP4 returned to the agent
````

This project provides:

* a FastAPI server wrapping Wan2GP generation
* a Python client skill for Linux agents
* support for text to video
* support for image to video
* job queue monitoring
* MP4 download after generation
* fixed model configuration for safer agent usage

## Project structure

```text
wan2gp_agentic_skill/
│
├── README.md
│
├── wan2gp_server/
│   ├── wan2gp_api_server.py
│   ├── ltx2_template_t2v.json
│   └── ltx2_template_i2v.json
│
└── wan2gp_video_agent_skill/
    ├── wan2gp_skill.py
    └── SKILL.md
```

## What it does

The server exposes a local HTTP API in front of Wan2GP.

AI agents can call the API to:

1. submit a video generation job
2. receive a `job_id`
3. check the job status
4. wait until the video is complete
5. download the generated MP4
6. send the MP4 back to Discord, Telegram, WhatsApp, OpenClaw, Hermes, or any other messaging platform

## Intended architecture

```text
Linux agent OpenClaw / Hermes
        |
        | POST /generate/t2v
        | POST /generate/i2v
        | GET  /jobs/{job_id}
        | GET  /download/{job_id}/{filename}
        v
Windows PC
Wan2GP API server
        |
        v
Wan2GP Python API
        |
        v
NVIDIA GPU
        |
        v
MP4 output
```

## Main use case

This project is useful when you have:

* one powerful Windows PC with GPU and Wan2GP installed
* several AI agents running on Linux machines
* a local network connecting them
* a need for agents to generate videos without installing Wan2GP locally

Example:

```text
Genesis, Alya, Hemera, Zeya, Hermes, or any other agent
can request a video generation from a central Wan2GP machine.
```

## Fixed model

The current setup is designed for one fixed model:

```text
LTX-2 2.3 Distilled 1.1 22B
```

Internal Wan2GP model type:

```text
ltx2_22B_distilled_1_1
```

This is intentional.

Agents should not dynamically switch models. Keeping the model fixed reduces mistakes, prevents unexpected VRAM usage, and makes behavior more predictable.

## Requirements

### Windows Wan2GP server

You need:

* Windows
* Wan2GP already installed
* Python environment used by Wan2GP
* NVIDIA GPU supported by your Wan2GP setup
* FastAPI dependencies installed in the Wan2GP Python environment

Install server dependencies:

```powershell
pip install fastapi uvicorn python-multipart pydantic
```

### Linux agent side

You need:

```bash
pip install requests
```

## Server installation

Copy the server files into your Wan2GP installation folder.

Example:

```text
G:\APPS\Wan2GP\
```

Expected files:

```text
G:\APPS\Wan2GP\wan2gp_api_server.py
G:\APPS\Wan2GP\ltx2_template_t2v.json
G:\APPS\Wan2GP\ltx2_template_i2v.json
```


## Why two templates?

Wan2GP stores mode-specific settings in its exported JSON.

A template exported from an image to video job may still require a start image even if the script clears `image_start`.

For this reason, the project uses two separate templates:

```text
ltx2_template_t2v.json
ltx2_template_i2v.json
```

This avoids mode confusion and makes the API more reliable.

## Start the server

On the Windows Wan2GP PC:

```powershell
Set-Location "G:\APPS\Wan2GP"
.\venv\Scripts\activate
python wan2gp_api_server.py
```

Depending on your Wan2GP installation, the virtual environment path may differ.

Alternative examples:

```powershell
.\.venv\Scripts\activate
```

or:

```powershell
.\installer_files\env\Scripts\activate
```

The API should start on:

```text
http://0.0.0.0:7861
```

From the Windows PC, test:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:7861/health"
```

## Network access

If agents run on other machines in the LAN, open the Windows firewall port:

```powershell
New-NetFirewallRule `
  -DisplayName "Wan2GP API 7861" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 7861 `
  -Action Allow
```

Example server IP:

```text
192.168.1.53
```

Agent-side base URL:

```text
http://192.168.1.53:7861
```

## Authentication

The API uses a Bearer token.

Example header:

```text
Authorization: Bearer YOUR_SECRET_TOKEN
```

Do not expose the API directly on the Internet.

Recommended deployment:

```text
LAN only
or
VPN only
```

## API endpoints

### Health check

```http
GET /health
```

Returns basic API status.

### Model info

```http
GET /model
```

Requires authorization.

Returns the fixed model information.

### List jobs

```http
GET /jobs
```

Requires authorization.

Returns known jobs stored in server memory.

Important: job history is lost when the API server restarts.

### Get job status

```http
GET /jobs/{job_id}
```

Requires authorization.

Returns job status, progress, queue position, generated files, and errors.

Possible job statuses:

```text
queued
running
completed
failed
```

Short statuses:

```text
Q = queued
R = running
C = completed
F = failed
```

### Text to video

```http
POST /generate/t2v
```

JSON body example:

```json
{
  "prompt": "A cinematic shot of a robot walking under neon rain",
  "duration_seconds": 3,
  "fps": 24,
  "resolution": "1280x720",
  "num_inference_steps": 8
}
```

Optional fields:

```json
{
  "seed": 123456,
  "negative_prompt": "blurry, low quality"
}
```

### Image to video

```http
POST /generate/i2v
```

Multipart form fields:

```text
prompt
image
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Example with curl:

```bash
curl -X POST "http://192.168.1.53:7861/generate/i2v" \
  -H "Authorization: Bearer YOUR_SECRET_TOKEN" \
  -F "prompt=A cinematic close-up portrait, subtle natural movement, warm daylight" \
  -F "duration_seconds=3" \
  -F "fps=24" \
  -F "resolution=1280x720" \
  -F "num_inference_steps=8" \
  -F "image=@/tmp/image.png"
```

### Download result

```http
GET /download/{job_id}/{filename}
```

Requires authorization.

The job status response contains `download_urls` once generation is complete.

Example:

```json
{
  "download_urls": [
    "/download/abc-123/video.mp4"
  ]
}
```

Full URL:

```text
http://192.168.1.53:7861/download/abc-123/video.mp4
```

## Agent skill installation

Copy the agent skill folder to your agent workspace.

Example for OpenClaw:

```bash
mkdir -p ~/.openclaw/workspace/skills/wan2gp_video
cp wan2gp_video_agent_skill/* ~/.openclaw/workspace/skills/wan2gp_video/
```

Install Python dependency:

```bash
pip install requests
```

Set environment variables:

```bash
export WAN2GP_URL="http://192.168.1.53:7861"
export WAN2GP_TOKEN="YOUR_SECRET_TOKEN"
```

## Python usage

### Text to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="t2v",
    prompt="A cinematic shot of a robot walking under neon rain, realistic lighting",
    duration_seconds=3,
    output_path="/tmp/robot.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Image to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="i2v",
    image_path="/tmp/image.png",
    prompt="A cinematic close-up portrait, subtle natural movement, warm daylight",
    duration_seconds=3,
    output_path="/tmp/portrait.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Submit a job without waiting

```python
from wan2gp_skill import submit_text_to_video

result = submit_text_to_video(
    prompt="A futuristic hospital corridor, cinematic lighting",
    duration_seconds=3,
)

print(result["job_id"])
```

### Check job status

```python
from wan2gp_skill import get_job_status, format_job_status

job = get_job_status("YOUR_JOB_ID")

print(format_job_status(job))
```

### Download result manually

```python
from wan2gp_skill import get_job_status, download_first_generated_file

job = get_job_status("YOUR_JOB_ID")

download_first_generated_file(
    job=job,
    output_path="/tmp/generated_video.mp4",
)
```

## Recommended agent behavior

When a user asks for a video:

1. decide whether the request is text to video or image to video
2. build or improve the prompt
3. call `submit_text_to_video()` or `submit_image_to_video()`
4. store the returned `job_id`
5. poll `get_job_status(job_id)`
6. when status is `completed`, download the MP4
7. send the MP4 back to the user through the messaging platform

## Queue behavior

The server processes jobs sequentially.

This avoids multiple agents launching several GPU-heavy generations at the same time.

Each job exposes:

```text
job_id
status
short_status
queue_position
progress
phase
current_step
total_steps
message
download_urls
errors
```

## Security notes

This project is intended for trusted local network use.

Do not expose the Wan2GP API directly to the public Internet.

Recommended protections:

* keep it LAN-only
* use a strong Bearer token
* restrict Windows firewall rules to agent IP addresses
* rotate the token if it has been shared
* avoid committing real tokens to GitHub

Use placeholders in public files:

```text
YOUR_SECRET_TOKEN
```

## VRAM behavior

Wan2GP may keep models loaded in VRAM between generations for better performance.

This is good for speed but keeps GPU memory occupied.

Possible strategies:

* keep the server always warm for fast generation
* add a manual unload endpoint
* clean CUDA cache after inactivity
* restart the API process after a long idle delay for full VRAM release

The most reliable way to fully release VRAM is to stop the Python process that loaded the model.

## Troubleshooting

### `Job not found`

Possible causes:

* wrong `job_id`
* empty `job_id`
* server was restarted
* job history was lost because jobs are stored in memory

### `You must provide a Start Image`

You are probably using an image to video template for a text to video job.

Fix:

* export a real text to video template from the Wan2GP UI
* save it as `ltx2_template_t2v.json`

### The agent cannot reach the API

Check from Linux:

```bash
curl http://192.168.1.53:7861/health
```

Then check authenticated access:

```bash
curl -H "Authorization: Bearer YOUR_SECRET_TOKEN" \
  http://192.168.1.53:7861/model
```

### MP4 download fails from browser

The `/download` endpoint requires the Authorization header.

A normal browser link cannot add that header automatically.

Use:

* the Python skill download function
* curl with the Authorization header
* a small authenticated proxy page if needed

## Disclaimer

This project is an integration wrapper around Wan2GP.

It does not include Wan2GP itself, model weights, or any third-party model files.

Make sure you respect the licenses and terms of the software and models you use.

## Repository

GitHub:

```text
https://github.com/magicmars35/wan2gp_agentic_skill
```


