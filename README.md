# Wan2GP Agentic Skill

Wan2GP Agentic Skill allows Linux AI agents such as OpenClaw, Hermes, or any Python-based agent to generate videos through a Windows PC running Wan2GP on the local network.

<p align="center">
  <img src="https://github.com/user-attachments/assets/ceecc42b-f03b-4742-a2f7-c7b66d6c58b9"
       alt="Wan2GP Discord Demo"
       style="max-width: 100%; height: auto;">
</p>

## Concept

The concept is simple:

```text
Linux AI Agent
      |
      | HTTP API
      v
Windows PC with Wan2GP + GPU
      |
      | FastAPI server
      | - video generation API
      | - built-in queue monitor
      | - MP4 download endpoint
      v
Generated MP4 video
      |
      v
Returned to the agent
```

The project contains two main parts:

1. a FastAPI server to install on the Wan2GP Windows machine
2. a Python skill to install on the AI agent machines

The monitoring interface is directly served by the FastAPI server. No separate web server is required.

## Features

- text to video generation
- image to video generation
- start image + end image to video generation
- audio to video generation
- audio + reference image to video generation
- audio + reference image + LoRA generation
- single universal Wan2GP template file
- server-side mode routing
- job queue tracking
- job status monitoring
- built-in HTML monitoring dashboard
- automatic MP4 download after generation
- requester IP tracking
- requester user-agent tracking
- fixed Wan2GP model on the server side
- optional non-blocking job submission for agents

## Generation modes

```text
t2v              text to video
i2v              image to video
i2v_end          start image + end image to video
s2v              sound/audio to video
s2v_i2v          sound/audio + reference image to video
s2v_i2v_lora     sound/audio + reference image + LoRA
```

## Current version highlights

This version uses one universal Wan2GP JSON template instead of one template per generation mode.

The server loads:

```text
ltx2_template_universal.json
```

Then it applies the correct mode controls automatically:

- image prompt type
- audio prompt type
- start image
- end image
- audio guide
- LoRA activation
- prompt enhancer
- multimodal generation type

This keeps the configuration cleaner and avoids maintaining several nearly identical JSON files.

The server also includes a built-in monitoring dashboard:

```text
http://SERVER_IP:7861/monitor?token=YOUR_SECRET_TOKEN
```

Alias:

```text
http://SERVER_IP:7861/ui?token=YOUR_SECRET_TOKEN
```

## Fixed model

The server is designed to use one fixed model:

```text
LTX-2 2.3 Distilled 1.1 22B
```

Internal Wan2GP model identifier:

```text
ltx2_22B_distilled_1_1
```

The model is intentionally locked on the server side to prevent agents from switching models or launching unexpected heavy generations.

## Repository structure

```text
wan2gp_agentic_skill/
│
├── README.md
│
├── wan2gp_server/
│   ├── wan2gp_api_server.py
│   └── ltx2_template_universal.json
│
└── wan2gp_video_agent_skill/
    ├── wan2gp_skill.py
    └── SKILL.md
```

The logic is:

- `wan2gp_server` goes on the Windows PC running Wan2GP
- `wan2gp_video_agent_skill` goes on the Linux AI agent machines
- the monitoring dashboard is directly included in the FastAPI server

## Installation part 1: Wan2GP server

This part must be done on the Windows PC where Wan2GP is installed.

Example Wan2GP folder:

```text
G:\APPS\Wan2GP
```

Copy these files from `wan2gp_server` into the Wan2GP installation folder:

```text
wan2gp_api_server.py
ltx2_template_universal.json
```

The JSON file is a template exported from the Wan2GP Web UI.

The API server uses this universal template and automatically adapts it depending on the requested mode.

Install the API dependencies inside the same Python environment used by Wan2GP:

```powershell
pip install fastapi uvicorn python-multipart pydantic requests
```

> [!CAUTION]
> Do **not** run the Wan2GP main program at the same time as the API web server.
>
> Both may try to use the same Wan2GP resources, which can cause conflicts, failed jobs, or unstable behavior.

Only run this API server script. It is not necessary to run the Wan2GP legacy program separately.

Example startup with a virtual environment:

```powershell
Set-Location "G:\APPS\Wan2GP"
.\venv\Scripts\activate
python wan2gp_api_server.py
```

Depending on your Wan2GP installation, the virtual environment path may be different.

If your agents are on the LAN, open the Windows firewall port:

```powershell
New-NetFirewallRule `
  -DisplayName "Wan2GP API 7861" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 7861 `
  -Action Allow
```

Example server URL for agents:

```text
http://192.168.1.53:7861
```

## Built-in monitoring dashboard

The FastAPI server includes its own monitoring dashboard.

Open:

```text
http://192.168.1.53:7861/monitor?token=YOUR_SECRET_TOKEN
```

Or:

```text
http://192.168.1.53:7861/ui?token=YOUR_SECRET_TOKEN
```

The dashboard displays:

- API status
- loaded model
- total jobs
- active jobs
- completed jobs
- failed jobs
- job status
- queue position
- generation mode
- progress
- current phase
- current step
- requester IP
- requester user-agent
- prompt excerpt
- input files
- LoRA information
- generation duration
- MP4 download link

The dashboard uses a browser token parameter because browsers do not easily send an `Authorization: Bearer ...` header when opening a page directly.

## Installation part 2: AI agent skill

### Method 1: let your agent install the skill from GitHub

The simplest method is to give your AI agent the URL of this GitHub repository and ask it to install the skill itself.

Example instruction to give to your agent:

```text
Install the Wan2GP video generation skill from this GitHub repository.
Read the README, copy the agent skill files into your skill workspace, and make the skill available for use.
```

### Method 2: manual installation

This part must be done on the Linux machines running the agents.

Copy the `wan2gp_video_agent_skill` folder into your agent skill workspace.

Example for OpenClaw:

```bash
mkdir -p ~/.openclaw/workspace/skills/wan2gp_video
cp wan2gp_video_agent_skill/* ~/.openclaw/workspace/skills/wan2gp_video/
```

Install the Python dependency:

```bash
pip install requests
```

Configure the server URL and token:

```bash
export WAN2GP_URL="http://192.168.1.53:7861"
export WAN2GP_TOKEN="YOUR_SECRET_TOKEN"
```

It is recommended to use environment variables instead of hardcoding the token in the Python file.

## What to tell the agents

Add this to the system prompt or skill configuration of your agent:

```text
You have access to a skill called Wan2GP Video.

Use this skill whenever the user asks for video generation.

Choose the mode automatically:

- text only: t2v
- image + prompt: i2v
- start image + end image + prompt: i2v_end
- audio + prompt: s2v
- audio + image + prompt: s2v_i2v
- audio + image + explicit LoRA request: s2v_i2v_lora

After submitting the job, retrieve the job_id, monitor progress with get_job_status, wait until the job is complete, download the generated MP4, then return the video file to the user.

When useful, provide the user with the built-in monitor URL so they can follow the queue visually.
```

## Agent usage examples

### Text to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="t2v",
    prompt="A cinematic shot of a small robot walking under neon rain, realistic lighting",
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
    prompt="A cinematic close-up portrait, subtle natural movement, warm daylight",
    image_path="/tmp/reference.png",
    duration_seconds=3,
    output_path="/tmp/i2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Start image + end image

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="i2v_end",
    prompt="The subject slowly turns toward the camera as the lighting shifts from warm daylight to blue evening light",
    image_start_path="/tmp/start.png",
    image_end_path="/tmp/end.png",
    duration_seconds=4,
    output_path="/tmp/i2v_end.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Audio to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v",
    prompt="A cinematic dialogue scene with natural facial expression and perfect lip sync",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/s2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Audio + image

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v_i2v",
    prompt="The woman speaks naturally in French in front of the camera, soft studio lighting, realistic facial motion, perfect lip sync",
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/s2v_i2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Audio + image + LoRA

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v_i2v_lora",
    prompt="The woman speaks in French in front of the camera with perfect lip sync, calm studio ambiance, subtle cinematic camera movement",
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/result.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Submit without waiting

This is useful when several agents submit jobs and the queue is monitored from the built-in dashboard.

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="t2v",
    prompt="A futuristic hospital corridor, cinematic lighting, slow dolly forward",
    duration_seconds=4,
    wait=False,
)

print(result["job_id"])
print(result["monitor_url"])
```

## Main API endpoints

```text
GET  /health
GET  /model
GET  /jobs
GET  /jobs/{job_id}
GET  /download/{job_id}/{filename}
GET  /monitor?token=YOUR_SECRET_TOKEN
GET  /ui?token=YOUR_SECRET_TOKEN
GET  /monitor/download/{job_id}/{filename}?token=YOUR_SECRET_TOKEN

POST /generate/t2v
POST /generate/i2v
POST /generate/i2v_end
POST /generate/s2v
POST /generate/s2v_i2v
POST /generate/s2v_i2v_lora
```

Protected API endpoints require a Bearer token:

```text
Authorization: Bearer YOUR_SECRET_TOKEN
```

The browser monitoring endpoints accept the token as a query parameter:

```text
?token=YOUR_SECRET_TOKEN
```

## Endpoint details

### GET /health

Returns basic API status and available modes.

### GET /model

Returns the fixed model information, default generation settings, template file path, and supported mode controls.

### GET /jobs

Returns all jobs currently known by the API server.

Jobs are stored in memory. If the server restarts, the job history is cleared.

### GET /jobs/{job_id}

Returns a single job with runtime fields such as `queue_position` and `short_status`.

### GET /download/{job_id}/{filename}

Downloads a generated MP4 using Bearer token authentication.

### GET /monitor

Displays the built-in HTML queue dashboard.

### GET /monitor/download/{job_id}/{filename}

Downloads a generated MP4 from the browser dashboard using the `token` query parameter.

## Prompting recommendations for LTX 2.3

For LTX 2.3 video generation, write the prompt as a clear cinematic direction, not as a list of keywords.

Recommended structure:

1. shot type
2. camera movement
3. environment
4. lighting
5. subject
6. visible action
7. mood expressed through physical details
8. audio or dialogue when needed

Example:

```text
The camera starts in a tight cinematic close-up, then slowly pushes forward as the woman raises her eyes toward the lens. Warm studio light reflects softly on her face. She breathes in, pauses, and says in French, "Je crois que j'ai enfin compris." Her voice is quiet and sincere. After the line, she gives a small uncertain smile while the background remains softly blurred.
```

For Image-to-Video, do not redescribe what is already visible in the reference image. Describe only:

- camera movement
- subject movement
- environmental changes
- lighting changes
- facial expression changes
- dialogue or sound timing

If the video contains dialogue, include the dialogue directly inside the prompt exactly where it happens in the scene.

## Important notes

The Wan2GP API server must be running before agents can generate videos.

The first generation after startup may be slower if the model has to be loaded into VRAM.

Jobs are stored in memory on the API server.

If the API server is restarted, previous `job_id` values will no longer be available.

Use the built-in monitor to follow the queue visually while agents submit generation jobs.

## Security

This project is designed for local network or VPN usage.

Do not expose the Wan2GP API directly to the public Internet.

Recommendations:

- use a long Bearer token
- do not publish real tokens on GitHub
- restrict the Windows firewall to agent IP addresses if possible
- keep Wan2GP LAN-only
- use `YOUR_SECRET_TOKEN` in public files
- avoid committing local IPs or private infrastructure details if the repository is public

## Disclaimer

This project is a wrapper around Wan2GP.

It does not include Wan2GP, AI models, model weights, LoRA files, or any third-party generation assets.

Respect the licenses and terms of use of Wan2GP, the models, and the LoRA files you use.
