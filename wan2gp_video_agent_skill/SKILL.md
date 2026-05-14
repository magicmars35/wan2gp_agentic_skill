# Wan2GP Video Skill

## Rôle

Cette skill permet à un agent Linux OpenClaw ou Hermes de générer des vidéos via le serveur Wan2GP installé sur le PC Windows du LAN.

Le serveur Wan2GP tourne sur :


http://192.168.1.53:7861
`

Le modèle utilisé côté serveur est fixe :


LTX-2 2.3 Distilled 1.1 22B


Identifiant interne :


ltx2_22B_distilled_1_1


## Principe

L'agent ne génère pas lui-même la vidéo.

Il envoie une requête HTTP au PC Windows Wan2GP, attend la fin du job, puis télécharge le fichier MP4.

Flux normal :


Agent Linux
  -> POST /generate/t2v ou /generate/i2v
  -> récupère job_id
  -> GET /jobs/{job_id}
  -> attend status completed
  -> GET /download/{job_id}/{filename}
  -> récupère le MP4


## Configuration

La skill utilise deux variables d'environnement optionnelles :

bash
WAN2GP_URL="http://192.168.1.53:7861"
WAN2GP_TOKEN="TOKEN_SECRET"


Si elles ne sont pas définies, les valeurs par défaut du fichier `wan2gp_skill.py` sont utilisées.

Il est recommandé de définir ces variables dans l'environnement de l'agent plutôt que de laisser le token écrit en dur.

Exemple :

bash
export WAN2GP_URL="http://192.168.1.53:7861"
export WAN2GP_TOKEN="TOKEN_SECRET"


## Fonctions disponibles

### health()

Vérifie que le serveur Wan2GP répond.

### model_info()

Retourne les informations sur le modèle vidéo utilisé.

### list_jobs()

Liste les jobs connus du serveur Wan2GP.

Attention : les jobs sont stockés en mémoire côté serveur. Si le serveur API Wan2GP est redémarré, les anciens job_id disparaissent.

### get_job_status(job_id)

Récupère l'état détaillé d'un job.

Champs importants :


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


### format_job_status(job)

Transforme le statut d'un job en texte lisible pour Discord, Telegram, WhatsApp, etc.

### submit_text_to_video(...)

Lance une génération text to video.

Paramètres :


prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt


Retourne immédiatement un `job_id`.

### submit_image_to_video(...)

Lance une génération image to video.

Paramètres :


image_path
prompt
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt


Retourne immédiatement un `job_id`.

### wait_for_job(job_id)

Attend la fin d'un job.

Retourne le job final quand il est terminé.

Lève une erreur si le job échoue.

### download_file(download_url, output_path)

Télécharge un fichier généré par Wan2GP.

### download_first_generated_file(job, output_path)

Télécharge le premier fichier généré d'un job terminé.

### generate_video(...)

Fonction haut niveau.

Elle permet de tout faire en une seule commande :

1. soumettre le job
2. attendre la fin
3. télécharger le MP4 si `output_path` est fourni

Paramètres :


mode
prompt
image_path
duration_seconds
fps
resolution
num_inference_steps
seed
negative_prompt
poll_seconds
output_path
verbose


Valeurs possibles pour `mode` :


t2v
i2v


## Exemple text to video

python
from wan2gp_skill import generate_video

result = generate_video(
    mode="t2v",
    prompt="A cinematic shot of a small robot walking under neon rain, realistic lighting",
    duration_seconds=3,
    output_path="/tmp/robot.mp4",
    verbose=True,
)

print(result["saved_file"])


## Exemple image to video

python
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


## Exemple suivi manuel d'un job

python
from wan2gp_skill import submit_text_to_video, get_job_status, format_job_status

submit_result = submit_text_to_video(
    prompt="A futuristic hospital corridor, cinematic lighting",
    duration_seconds=3,
)

job_id = submit_result["job_id"]

job = get_job_status(job_id)

print(format_job_status(job))


## Statuts possibles


queued
running
completed
failed


Statuts courts :


Q = queued
R = running
C = completed
F = failed


## Comportement recommandé pour l'agent

Quand l'utilisateur demande une vidéo :

1. reformuler ou enrichir le prompt si nécessaire
2. choisir le mode :

   * t2v si aucune image n'est fournie
   * i2v si une image est fournie
3. appeler `generate_video(...)`
4. annoncer le `job_id`
5. suivre la progression avec `get_job_status(job_id)`
6. télécharger le MP4
7. publier le MP4 dans le canal de conversation


Quand l'utilisateur demande une génération vidéo, utilise la skill Wan2GP Video.
Utilise t2v s'il n'y a pas d'image.
Utilise i2v si une image est fournie.
Retourne le MP4 généré à l'utilisateur.

