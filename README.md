# Wan2GP Agentic Skill

Wan2GP Agentic Skill allows Linux AI agents such as OpenClaw, Hermes, or any Python-based agent to generate videos through a Windows PC running Wan2GP on the local network.

<img width="1672" height="941" alt="ChatGPT Image 15 mai 2026, 13_10_05" src="https://github.com/user-attachments/assets/dc939d3a-4bab-4d1e-bffd-3552fc23edfd" />





The concept is simple:

```text
Linux AI Agent
      |
      | HTTP API
      v
Windows PC with Wan2GP + GPU
      |
      v
Generated MP4 video
      |
      v
Returned to the agent
````

The project contains two main parts:

1. a FastAPI server to install on the Wan2GP Windows machine
2. a Python skill to install on the AI agent machines

## Features

* text to video generation
* image to video generation
* start image + end image to video generation
* audio to video generation
* audio + reference image to video generation
* audio + reference image + server-side LoRA generation
* job queue tracking
* job status monitoring
* automatic MP4 download after generation
* requester IP tracking
* fixed Wan2GP model on the server side

## V2 Update

V2 adds the following generation modes:

```text
t2v              text to video
i2v              image to video
i2v_end          start image + end image to video
s2v              sound/audio to video
s2v_i2v          sound/audio + reference image to video
s2v_i2v_lora     sound/audio + reference image + server-side LoRA
```

V2 also adds:

* `requester_ip` in job data
* `requester_user_agent` in job data
* improved `/jobs` monitoring
* a PHP monitoring page compatible with all V2 modes
* an updated agent skill supporting all V2 modes

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
│   ├── ltx2_template_t2v.json
│   ├── ltx2_template_i2v.json
│   ├── ltx2_template_i2v_end.json
│   ├── ltx2_template_s2v.json
│   ├── ltx2_template_s2v_i2v.json
│   └── ltx2_template_s2v_i2v_lora.json
│
├── wan2gp_video_agent_skill/
│   ├── wan2gp_skill.py
│   └── SKILL.md
│
└── php_monitor/
    ├── wan2gp_queue.php
    └── wan2gp_download.php
```

The exact folder structure may vary, but the logic is:

* `wan2gp_server` goes on the Windows PC running Wan2GP
* `wan2gp_video_agent_skill` goes on the Linux AI agent machines
* `php_monitor` can be installed on a Linux web server to visually monitor the queue

## Installation part 1: Wan2GP server

This part must be done on the Windows PC where Wan2GP is installed.

Example Wan2GP folder:

```text
G:\APPS\Wan2GP
```

1. Copy all the JSON  files from `wan2gp_server` into the Wan2GP installation folder.
2. Copy also `wan2gp_api_server.py` into the Wan2GP installation folder

```text
wan2gp_api_server.py
ltx2_template_t2v.json
ltx2_template_i2v.json
ltx2_template_i2v_end.json
ltx2_template_s2v.json
ltx2_template_s2v_i2v.json
ltx2_template_s2v_i2v_lora.json
```

The JSON files are templates exported from the Wan2GP Web UI.

Each generation mode uses its own template to avoid internal configuration conflicts.
Install the API dependencies inside the same Python environment used by Wan2GP:

```powershell
pip install fastapi uvicorn python-multipart pydantic
```


Start the server:



> [!CAUTION]
> Do **not** run the Wan2GP main program at the same time as the API web server.
>
> Both may try to use the same Wan2GP resources, which can cause conflicts, failed jobs, or unstable behavior.




Again : Only run this API server script. It is NOT necessary to run the WAN2GP legacy program (wgp.py) 
Use conda Wan2gp offical setup inscruction to enter the Wan2GP python environment.

(I used  venv to install WAN2GP).

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

## Installation part 2: AI agent skill

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

### Audio + image + server-side LoRA

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v_i2v_lora",
    prompt="The woman speaks in French in front of the camera with perfect lip sync",
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/result.mp4",
    verbose=True,
)

print(result["saved_file"])
```

## Main endpoints

```text
GET  /health
GET  /model
GET  /jobs
GET  /jobs/{job_id}
GET  /download/{job_id}/{filename}

POST /generate/t2v
POST /generate/i2v
POST /generate/i2v_end
POST /generate/s2v
POST /generate/s2v_i2v
POST /generate/s2v_i2v_lora
```

Protected endpoints require a Bearer token:

```text
Authorization: Bearer YOUR_SECRET_TOKEN
```

## PHP monitoring page

<img width="1885" height="849" alt="image" src="https://github.com/user-attachments/assets/5a2c0206-bdd9-46ae-b8fa-9297b005e3a6" />

The PHP monitoring page can query `/jobs` and display:

* job status
* generation type
* progress
* requester machine
* requester IP
* real generation duration
* input files
* MP4 download link

Quick installation example on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y apache2 php php-curl
sudo cp php_monitor/*.php /var/www/html/
```

Then open:

```text
http://YOUR_PHP_SERVER_IP/wan2gp_queue.php
```

## Important notes

Jobs are stored in memory on the API server.

If the API server is restarted, previous `job_id` values will no longer be available.

The Wan2GP API server must be running before agents can generate videos.

The first generation after startup may be slower if the model has to be loaded into VRAM.

## Security

This project is designed for local network or VPN usage.

Do not expose the Wan2GP API directly to the public Internet.

Recommendations:

* use a long Bearer token
* do not publish real tokens on GitHub
* restrict the Windows firewall to agent IP addresses if possible
* keep Wan2GP LAN-only
* use `YOUR_SECRET_TOKEN` in public files

## Disclaimer

This project is a wrapper around Wan2GP.

It does not include Wan2GP, AI models, model weights, LoRA files, or any third-party generation assets.

Respect the licenses and terms of use of Wan2GP, the models, and the LoRA files you use.

```
```
