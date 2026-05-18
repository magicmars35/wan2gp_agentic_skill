---
name: wan2gp_video
description: Generate and monitor Wan2GP LTX 2.3 videos through the LAN API server. Supports t2v, i2v, i2v_end, s2v, s2v_i2v, s2v_i2v_lora, universal template mode, queue monitoring, MP4 download and browser monitor URL.
---

# Wan2GP Video Skill

## Role

This skill lets an OpenClaw, Hermes or coding agent generate videos through a Wan2GP server running on a Windows PC on the LAN.

The agent does not generate the video locally. It sends a job to the Wan2GP API server, follows the queue, waits for completion when requested, and downloads the generated MP4.

Default server:

```bash
http://192.168.1.53:7861
```

Default model on the server:

```text
LTX-2 2.3 Distilled 1.1 22B
```

Internal model id:

```text
ltx2_22B_distilled_1_1
```

## Important server-side infos

The server uses one universal template:

```text
G:\APPS\Wan2GP\ltx2_template_universal.json
```

The server then applies mode controls internally:

```text
t2v            text only
i2v            start image
i2v_end        start image + end image
s2v            audio only
s2v_i2v        audio + reference image
s2v_i2v_lora   audio + reference image + LoRA
```

The agent does not need to know the template details. It only chooses the mode and sends the required files.

## Built-in monitor page

The Wan2GP API server can also serve the monitoring web page directly.

Use this helper from Python:

```python
from wan2gp_skill import monitor_url

print(monitor_url())
```

Default URL format:

```text
http://192.168.1.53:7861/monitor?token=TOKEN_SECRET
```

Alias:

```text
http://192.168.1.53:7861/ui?token=TOKEN_SECRET
```

The monitor shows:

- API status
- current model
- total jobs
- active jobs
- completed jobs
- failed jobs
- mode counts
- queue position
- job progress
- prompt excerpt
- input files
- LoRA information
- generated MP4 download link

## Environment variables

Recommended configuration:

```bash
export WAN2GP_URL="http://192.168.1.53:7861"
export WAN2GP_TOKEN="TOKEN_SECRET"
```

Optional defaults:

```bash
export WAN2GP_DEFAULT_RESOLUTION="1280x720"
export WAN2GP_DEFAULT_FPS="24"
export WAN2GP_DEFAULT_DURATION_SECONDS="3"
export WAN2GP_DEFAULT_STEPS="8"
export WAN2GP_DEFAULT_POLL_SECONDS="5"
export WAN2GP_REQUEST_TIMEOUT="60"
export WAN2GP_UPLOAD_TIMEOUT="180"
export WAN2GP_DOWNLOAD_TIMEOUT="600"
```

Avoid hardcoding secrets in agent prompts. Prefer environment variables.

## Basic flow

```text
Agent
  -> POST /generate/...
  -> receives job_id
  -> GET /jobs/{job_id}
  -> waits until status is completed or failed
  -> GET /download/{job_id}/{filename}
  -> downloads MP4
```

For human monitoring:

```text
Browser
  -> /monitor?token=TOKEN_SECRET
```

## Python module

The implementation file is:

```text
wan2gp_skill.py
```

Import examples:

```python
from wan2gp_skill import generate_video, submit_video_job, get_job_status, wait_for_job
```

## Modes

### t2v

Text to video.

Required:

- prompt

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt

Endpoint:

```text
POST /generate/t2v
```

### i2v

Image to video with a start image.

Required:

- prompt
- image_path

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt

Endpoint:

```text
POST /generate/i2v
```

### i2v_end

Image to video with a start image and an end image.

Required:

- prompt
- image_start_path
- image_end_path

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt

Endpoint:

```text
POST /generate/i2v_end
```

### s2v

Audio to video without reference image.

Required:

- prompt
- audio_path

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt

Endpoint:

```text
POST /generate/s2v
```

### s2v_i2v

Audio to video with a reference image.

Required:

- prompt
- image_path
- audio_path

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt

Endpoint:

```text
POST /generate/s2v_i2v
```

### s2v_i2v_lora

Audio to video with a reference image and LoRA.

Required:

- prompt
- image_path
- audio_path

Optional:

- duration_seconds
- fps
- resolution
- num_inference_steps
- seed
- negative_prompt
- lora_url
- lora_multiplier

Endpoint:

```text
POST /generate/s2v_i2v_lora
```

If `lora_url` is not provided, the server default LoRA is used.

## Main functions

### health()

Checks whether the server responds.

```python
from wan2gp_skill import health

print(health())
```

### model_info()

Returns model and mode information from the server.

```python
from wan2gp_skill import model_info

print(model_info())
```

### monitor_url()

Returns the browser monitor URL with token query auth.

```python
from wan2gp_skill import monitor_url

print(monitor_url())
```

### list_jobs()

Lists all known jobs in server memory.

```python
from wan2gp_skill import list_jobs

jobs = list_jobs()
print(jobs["count"])
```

### active_jobs()

Returns queued and running jobs.

```python
from wan2gp_skill import active_jobs

for job in active_jobs():
    print(job["job_id"], job["status"], job.get("queue_position"))
```

### get_job_status(job_id)

Gets detailed status for one job.

Important fields:

```text
job_id
api_mode
mode
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

### format_job_status(job)

Formats a job as readable text for chat, logs or notifications.

```python
from wan2gp_skill import get_job_status, format_job_status

job = get_job_status("JOB_ID")
print(format_job_status(job))
```

### submit_video_job(...)

Submits a job and returns immediately.

This is useful when agents need to start work, report the job id, and let the user follow it through `/monitor`.

```python
from wan2gp_skill import submit_video_job, monitor_url

result = submit_video_job(
    prompt="A cinematic robot walking under neon rain, realistic reflections",
    mode="t2v",
    duration_seconds=4,
)

print(result["job_id"])
print(monitor_url())
```

### generate_video(...)

High-level function for agents.

It can:

1. choose the mode automatically
2. submit the job
3. wait for completion
4. download the MP4 if `output_path` is provided

```python
from wan2gp_skill import generate_video

result = generate_video(
    prompt="A cinematic robot walking under neon rain, realistic reflections",
    duration_seconds=4,
    output_path="/tmp/robot.mp4",
    verbose=True,
)

print(result["saved_file"])
```

Use `wait=False` to submit only:

```python
from wan2gp_skill import generate_video

result = generate_video(
    prompt="A cinematic establishing shot of a futuristic hospital corridor",
    mode="t2v",
    duration_seconds=3,
    wait=False,
)

print(result["job_id"])
print(result["monitor_url"])
```

## Automatic mode choice

If `mode` is omitted, `generate_video()` and `submit_video_job()` choose automatically:

```text
prompt only                              -> t2v
image_path                              -> i2v
image_start_path + image_end_path       -> i2v_end
audio_path                              -> s2v
image_path + audio_path                 -> s2v_i2v
image_path + audio_path + use_lora=True -> s2v_i2v_lora
```

Do not provide incompatible combinations. For example, `image_start_path + image_end_path + audio_path` is not supported by this API.

## Examples

### Text to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    prompt="A slow cinematic tracking shot through a futuristic hospital corridor at night, blue emergency lights reflecting on polished floors, subtle fog, realistic camera movement",
    duration_seconds=4,
    output_path="/tmp/hospital_corridor.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Image to video

For Image to Video, do not redescribe everything visible in the reference image. Describe motion, camera, lighting changes and action.

```python
from wan2gp_skill import generate_video

result = generate_video(
    image_path="/tmp/reference.png",
    prompt="The camera slowly pushes in. The subject breathes naturally, blinks once, and turns slightly toward the window light. The background remains stable with shallow depth of field.",
    duration_seconds=4,
    output_path="/tmp/i2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Start image + end image

```python
from wan2gp_skill import generate_video

result = generate_video(
    image_start_path="/tmp/start.png",
    image_end_path="/tmp/end.png",
    prompt="The shot smoothly transitions from the first pose to the final pose with a believable head turn, subtle shoulder movement, and stable cinematic framing.",
    duration_seconds=5,
    output_path="/tmp/i2v_end.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Audio to video

```python
from wan2gp_skill import generate_video

result = generate_video(
    audio_path="/tmp/voice.mp3",
    prompt="A cinematic close-up of a woman speaking directly to camera with natural lip sync, soft studio light, subtle facial expressions, and calm breathing between words.",
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
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    prompt="The woman from the reference image speaks naturally in French, keeping her identity consistent. The camera holds a stable close-up while she blinks, breathes, and moves her lips in sync with the audio.",
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
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    use_lora=True,
    prompt="The woman from the reference image speaks in French in front of the camera with perfect lip sync, relaxed studio ambiance, realistic skin detail, and subtle head movement.",
    duration_seconds=6,
    output_path="/tmp/s2v_i2v_lora.mp4",
    verbose=True,
)

print(result["saved_file"])
```

### Custom LoRA URL

```python
from wan2gp_skill import generate_video

result = generate_video(
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    use_lora=True,
    lora_url="https://example.com/my_lora.safetensors",
    lora_multiplier="0.8",
    prompt="The subject speaks naturally with clean lip sync and a stable cinematic close-up.",
    duration_seconds=6,
    output_path="/tmp/custom_lora.mp4",
    verbose=True,
)
```

### Submit now, monitor manually

```python
from wan2gp_skill import submit_video_job, monitor_url

result = submit_video_job(
    prompt="A dreamy cinematic shot of a small robot discovering a glowing flower in a dark workshop",
    mode="t2v",
    duration_seconds=4,
)

print("Job:", result["job_id"])
print("Monitor:", monitor_url())
```

### Wait for an existing job

```python
from wan2gp_skill import wait_for_job, download_first_generated_file

job = wait_for_job("JOB_ID", verbose=True)
file_path = download_first_generated_file(job, "/tmp/result.mp4")
print(file_path)
```

## Prompt rules for LTX 2.3

Write prompts as cinematic direction, not keyword lists.

A strong prompt usually contains:

1. shot type
2. camera movement
3. environment
4. lighting
5. subject action
6. visible emotional cues
7. timing
8. audio or dialogue if relevant

Good structure:

```text
A tight cinematic close-up. The camera slowly pushes in as the woman lowers her eyes, breathes in, and turns slightly toward the window light. Warm afternoon light crosses her face, revealing subtle tension in her jaw and fingers. She whispers in French, "Je crois que j'ai compris", with soft, hesitant timing. The room stays still behind her, shallow depth of field, realistic skin detail, quiet room tone.
```

Avoid:

```text
beautiful woman, cinematic, sad, dramatic, 4k, realistic, amazing, high quality
```

## Dialogue rules

If the video contains dialogue, include the dialogue directly inside the prompt where it happens.

Good:

```text
The camera slowly pushes in as the woman looks at her father and says in French, "Papa, je crois que la lune n'est pas un lampadaire", with a confused but sincere voice. He freezes, blinks twice, then slowly turns toward her.
```

Bad:

```text
Dialogue: Papa, je crois que la lune n'est pas un lampadaire.
```

Keep dialogue short. Long monologues can drift and reduce lip-sync quality.

## Image to Video rules

When using `i2v`, `s2v_i2v` or `s2v_i2v_lora`:

- do not redescribe the whole reference image
- do describe what changes after frame one
- describe camera movement
- describe facial movement and body movement
- describe lighting changes if useful
- ask for identity consistency if the character must stay faithful

Example:

```text
Starting from the reference image, the camera holds a stable close-up. The subject keeps the same face, hairstyle and outfit, then slowly smiles, blinks naturally, and turns her eyes toward the lens. The background remains unchanged, with subtle film grain and soft daylight.
```

## Optimization recommendations

For reliable agent automation:

- use `duration_seconds=3` to `6` for first tests
- use `num_inference_steps=8` for fast draft generation
- increase steps only after the prompt is validated
- use `1280x720` for 16:9 default generations
- use `wait=False` when launching multiple jobs and monitor them from `/monitor`
- use `verbose=True` only for debugging, not for silent background agent workflows
- avoid uploading huge audio files when only a short dialogue is needed
- use short, precise dialogue for lip sync
- use `seed` only when repeatability matters

## Recommended agent behavior

When the user asks for a video:

1. identify available inputs: prompt, image, start image, end image, audio, LoRA request
2. choose the mode automatically when obvious
3. write or improve the prompt as cinematic direction
4. keep the generation short for the first pass unless the user asked otherwise
5. call `generate_video(...)` when the user expects a finished MP4
6. call `submit_video_job(..., wait=False)` or `generate_video(..., wait=False)` when the user wants several jobs queued
7. give the user the `job_id` and the `monitor_url`
8. download and return the MP4 when the job is completed

## Status values

Possible job statuses:

```text
queued
running
completed
failed
```

Short status values:

```text
Q = queued
R = running
C = completed
F = failed
```

## Troubleshooting

### Server not reachable

Check:

- Wan2GP API server is running on the Windows PC
- Windows firewall allows inbound connections on port 7861
- the agent machine can reach `192.168.1.53`
- `WAN2GP_URL` is correct

### Unauthorized

Check:

- `WAN2GP_TOKEN` matches the API token configured server-side
- the API uses `Authorization: Bearer TOKEN`
- the browser monitor uses `?token=TOKEN`

### Job disappeared

Jobs are stored in server memory. If the API server restarts, old job ids disappear.

### No MP4 download URL

The job may still be queued or running. Call:

```python
from wan2gp_skill import get_job_status
print(get_job_status("JOB_ID"))
```

### Lip-sync is poor

Try:

- shorter dialogue
- clearer audio
- close-up face framing
- explicit language and delivery in the prompt
- `s2v_i2v` or `s2v_i2v_lora` with a clean reference image

## Minimal smoke test

```python
from wan2gp_skill import health, monitor_url

print(health())
print(monitor_url())
```
