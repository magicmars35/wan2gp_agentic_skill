````md
---
name: wan2gp_video
description: Wan2GP V2 video generation via HTTP API on Windows PC (.53) — t2v, i2v, i2v_end, s2v, s2v_i2v, s2v_i2v_lora modes
---

# Wan2GP Video Skill

## Role

This skill allows a Linux OpenClaw or Hermes agent to generate videos through the Wan2GP server installed on a Windows PC on the local network.

The Wan2GP server runs at:

```text
http://192.168.1.53:7861
````

The model used server-side is fixed:

```text
LTX-2 2.3 Distilled 1.1 22B
```

Internal model identifier:

```text
ltx2_22B_distilled_1_1
```

---

## Principle

The agent does not generate the video itself.

It sends an HTTP request to the Wan2GP Windows PC, waits for the job to complete, then downloads the generated MP4 file.

Normal workflow:

```text
Linux Agent
  -> POST /generate/...
  -> receives job_id
  -> GET /jobs/{job_id}
  -> waits until status = completed
  -> GET /download/{job_id}/{filename}
  -> retrieves the MP4
```

---

## Available Modes

V2 supports six generation modes:

```text
t2v
i2v
i2v_end
s2v
s2v_i2v
s2v_i2v_lora
```

---

### t2v

Text to video.

Server endpoint:

```text
POST /generate/t2v
```

Required parameters:

```text
prompt
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

---

### i2v

Image to video using a starting image.

Server endpoint:

```text
POST /generate/i2v
```

Required parameters:

```text
prompt
image_path
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

---

### i2v_end

Image to video using both a starting image and an ending image.

Server endpoint:

```text
POST /generate/i2v_end
```

Required parameters:

```text
prompt
image_start_path
image_end_path
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

---

### s2v

Audio to video without reference image.

Server endpoint:

```text
POST /generate/s2v
```

Required parameters:

```text
prompt
audio_path
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

---

### s2v_i2v

Audio to video with reference image.

Server endpoint:

```text
POST /generate/s2v_i2v
```

Required parameters:

```text
prompt
image_path
audio_path
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

---

### s2v_i2v_lora

Audio to video with reference image and server-side LoRA.

Server endpoint:

```text
POST /generate/s2v_i2v_lora
```

Required parameters:

```text
prompt
image_path
audio_path
```

Optional parameters:

```text
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

The LoRA is not dynamically selected by the agent.

It is defined server-side in:

```text
ltx2_template_s2v_i2v_lora.json
```

---

## Configuration

The skill supports two optional environment variables:

```bash
WAN2GP_URL="http://192.168.1.53:7861"
WAN2GP_TOKEN="TOKEN_SECRET"
```

If not defined, the default values from `wan2gp_skill.py` are used.

It is strongly recommended to define these variables in the agent environment rather than hardcoding the token.

Example:

```bash
export WAN2GP_URL="http://192.168.1.53:7861"
export WAN2GP_TOKEN="TOKEN_SECRET"
```

---

## Available Functions

### health()

Checks whether the Wan2GP server is responding.

---

### model_info()

Returns information about the active video model and available modes.

---

### list_jobs()

Lists known jobs on the Wan2GP server.

Important:

Jobs are stored in server memory only.

If the Wan2GP API server is restarted, previous `job_id` entries disappear.

---

### get_job_status(job_id)

Returns detailed job status.

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

---

### format_job_status(job)

Formats a job status into readable text for Discord, Telegram, WhatsApp, etc.

---

### submit_text_to_video(...)

Starts a text-to-video generation.

Parameters:

```text
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### submit_image_to_video(...)

Starts an image-to-video generation.

Parameters:

```text
image_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### submit_image_to_video_with_end_image(...)

Starts an image-to-video generation with start and end images.

Parameters:

```text
image_start_path
image_end_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### submit_sound_to_video(...)

Starts an audio-to-video generation without image.

Parameters:

```text
audio_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### submit_sound_to_video_with_image(image_path, audio_path, prompt, ...)

Important note:

If `image_path` is an HTTP URL, for example:

```text
http://192.168.1.69/sources/images_ref/alya.png
```

the function automatically downloads it into `/tmp/` before sending it to Wan2GP.

No manual preparation required.

Starts an audio-to-video generation with reference image.

Parameters:

```text
image_path
audio_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### submit_sound_to_video_with_image_and_lora(...)

Starts an audio-to-video generation with reference image and server-side LoRA.

Parameters:

```text
image_path
audio_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
```

Returns immediately:

```text
job_id
```

---

### wait_for_job(job_id)

Waits for job completion.

Returns the final completed job object.

Raises an error if the job fails.

---

### download_file(download_url, output_path)

Downloads a generated file from Wan2GP.

---

### download_first_generated_file(job, output_path)

Downloads the first generated file from a completed job.

---

### generate_video(...)

High-level convenience function.

Performs everything in a single call:

1. submit the job
2. wait for completion
3. download the MP4 if `output_path` is provided

Parameters:

```text
mode
prompt
image_path
image_start_path
image_end_path
audio_path
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
poll_seconds
output_path
verbose
```

Supported mode values:

```text
t2v
i2v
i2v_end
s2v
s2v_i2v
s2v_i2v_lora
```

---

## Examples

### Text to Video

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

---

### Image to Video

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="i2v",
    prompt="A cinematic close-up portrait, subtle natural movement, warm daylight",
    image_path="/tmp/image_depart.png",
    duration_seconds=3,
    output_path="/tmp/portrait.mp4",
    verbose=True,
)

print(result["saved_file"])
```

---

### Start + End Image

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="i2v_end",
    prompt="The woman slowly turns toward the camera, cinematic motion",
    image_start_path="/tmp/start.png",
    image_end_path="/tmp/end.png",
    duration_seconds=4,
    output_path="/tmp/i2v_end.mp4",
    verbose=True,
)

print(result["saved_file"])
```

---

### Audio to Video Without Image

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v",
    prompt="A cinematic dialogue scene with perfect lip sync and expressive acting",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/s2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

---

### Audio + Reference Image

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v_i2v",
    prompt="The woman speaks naturally in front of the camera, perfect lip sync",
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/s2v_i2v.mp4",
    verbose=True,
)

print(result["saved_file"])
```

---

### Audio + Reference Image + LoRA

```python
from wan2gp_skill import generate_video

result = generate_video(
    mode="s2v_i2v_lora",
    prompt="The woman speaks in French in front of the camera with perfect lip sync, studio ambiance",
    image_path="/tmp/reference.png",
    audio_path="/tmp/voice.mp3",
    duration_seconds=6,
    output_path="/tmp/s2v_i2v_lora.mp4",
    verbose=True,
)

print(result["saved_file"])
```

---

## Manual Job Tracking Example

```python
from wan2gp_skill import submit_text_to_video, get_job_status, format_job_status

submit_result = submit_text_to_video(
    prompt="A futuristic hospital corridor, cinematic lighting",
    duration_seconds=3,
)

job_id = submit_result["job_id"]

job = get_job_status(job_id)

print(format_job_status(job))
```

---

## Possible Status Values

```text
queued
running
completed
failed
```

Short codes:

```text
Q = queued
R = running
C = completed
F = failed
```

---

## Recommended Agent Behavior

When a user requests a video:

1. reformulate or enrich the prompt if needed
2. choose the appropriate mode:

* `t2v` if only a text prompt is provided
* `i2v` if a starting image is provided
* `i2v_end` if both start and end images are provided
* `s2v` if only audio is provided
* `s2v_i2v` if both audio and image are provided
* `s2v_i2v_lora` if the user explicitly requests server LoRA rendering

3. call `generate_video(...)`
4. announce the `job_id` if useful
5. monitor progress with `get_job_status(job_id)`
6. download the MP4
7. publish the MP4 back to the conversation

---

## Discord Upload 413

Videos larger than 8MB may fail with:

```text
413 Request entity too large
```

Compress before upload:

```bash
ffmpeg -i input.mp4 -vf "scale=720:480" -c:v libx264 -preset fast -crf 28 -c:a aac -b:a 64k output_comp.mp4 -y
```

Reference:

```text
references/discord_upload_413.md
```

---

## Important Notes

### Common Pitfalls

#### 1. Image URL → FileNotFoundError

`_ensure_file_exists()` does not automatically download HTTP URLs.

For `submit_sound_to_video_with_image`, HTTP URLs are handled automatically.

Other functions are not.

Always provide a local file unless the function explicitly supports remote URLs.

---

#### 2. 422 "Field required: audio/image"

Multipart field names must be:

```text
image
audio
```

Not:

```text
image_file
audio_file
```

Correct example:

```python
requests.post(..., files={'image': ..., 'audio': ...})
```

---

#### 3. 401 Unauthorized

Verify:

```text
Authorization: Bearer {token}
```

Expected token:

```text
HGH7EPBCE51vureBCBUEBCE75678edfv9HUGBC7E
```

---

#### 4. Default Duration = 5 Seconds

If no duration is specified, the server defaults to 5 seconds.

Always confirm duration with the user.

If the user asked for 15 seconds, generate 15 seconds.

---

#### 5. Discord MEDIA failed

Even below 25MB, Discord upload may fail intermittently.

Solutions:

* retry upload
* retrieve manually from:

```text
G:\APPS\Wan2GP\api_outputs\
```

---

#### 6. HTTP Portrait URLs in submit_image_to_video

These must be downloaded manually first:

```bash
curl -o /tmp/genesis.png http://192.168.1.69/sources/images_ref/genesis.png
```

Never pass HTTP URLs directly to:

```text
image_path
```

for `submit_image_to_video`.

---

#### 7. Resolution Parameter

Correct:

```text
1280x720
```

Incorrect:

```text
720p
720
```

The server expects width x height format.

---

## Infrastructure Requirements

The Wan2GP server must be running on the Windows PC before use.

Server IP:

```text
192.168.1.53
```

Port:

```text
7861
```

Windows Firewall must allow inbound connections from Linux agent machines.

Jobs are memory-only.

Restarting the API clears previous jobs.

---

## Agent Instruction

When a user requests video generation, use the Wan2GP Video skill.

Automatically select the correct mode:

```text
Text only -> t2v
Image + prompt -> i2v
Start image + end image + prompt -> i2v_end
Audio only + prompt -> s2v
Audio + image + prompt -> s2v_i2v
Audio + image + LoRA request -> s2v_i2v_lora
```

Always return the generated MP4 to the user when processing is complete.

---

## Prompting Rules for LTX 2.3

For LTX 2.3 video generation, write prompts as clear cinematic direction rather than keyword lists.

Start with:

* shot type
* camera movement

Then define:

* environment
* lighting
* subject
* visible action
* mood through visible behavior
* audio

Describe physical action in sequence from beginning to end.

Use present tense action verbs.

Be explicit about:

* materials
* light sources
* atmosphere
* lens style
* depth of field
* pacing
* composition

Avoid vague emotional labels like:

```text
sad
dramatic
```

Instead translate them into visible cues:

* posture
* facial tension
* breathing
* eye movement
* silence
* hand motion

For image-to-video:

Do not redescribe what is already visible in the reference image.

Only describe:

* camera motion
* subject movement
* environmental change
* sound

Prompts must remain coherent, cinematic, and physically plausible.

---

## Dialogue Handling

If the video contains dialogue:

Include dialogue directly inside the prompt exactly where it occurs.

Use quotation marks.

Specify:

* speaker
* language
* tone
* pacing
* emotional delivery

Example:

```text
The camera slowly pushes in as the woman lowers her eyes, pauses, then whispers in English, "I should have told you the truth," with a trembling voice. After the line, the other character remains silent, exhales slowly, and looks away.
```

Guidelines:

* keep dialogue short
* keep it natural
* support it visually
* use pauses, gestures, facial expressions, ambient sound

Avoid long monologues or overly complex lip sync.

```
```




For LTX 2.3 video generation, write the prompt as a clear cinematic direction, not as a list of keywords. Start with the shot type and camera movement, then define the environment, lighting, subject, visible action, mood, and audio. Describe movement in a physical sequence from beginning to end, using present-tense action verbs: what the subject does, how the camera reacts, and what changes in the scene. Be specific about materials, light sources, atmosphere, lens style, depth of field, pacing, and frame composition. Avoid vague emotions like “sad” or “dramatic”; translate them into visible cues such as posture, facial tension, hand movement, breathing, eye direction, or silence. For Image-to-Video, do not redescribe what is already visible in the reference image; only describe camera motion, subject movement, environmental changes, and sound. Keep the prompt coherent, cinematic, and physically possible.

If the video contains dialogue, include the dialogue directly inside the prompt exactly where it happens in the scene, using quotation marks and specifying who speaks, in what language, tone, pace, and emotional delivery. Do not place dialogue in a separate note unless the tool explicitly asks for it; integrate it into the action so the model understands timing and performance. Example: The camera slowly pushes in as the woman lowers her eyes, pauses, then whispers in English, “I should have told you the truth,” with a trembling voice. After the line, describe the reaction: the other character remains silent, exhales slowly, and looks away. Keep dialogue short, natural, and visually supported by facial expressions, pauses, gestures, and ambient sound, because long monologues or complex lip-sync can drift.
