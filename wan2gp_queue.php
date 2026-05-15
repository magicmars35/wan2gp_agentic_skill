<?php
// THIS EXTRA  IS USED TO FOLLOW AND MONITOR JOBS SUBMITTED BY AI AGENTS.
// PLACE THIS PHP FILE IN A PHP WEB SERVER (Eg : APACHE + PHP)  ON THE  SAME NETWORK AS THE WAN2GP SERVER REST API.



// ======================================================
// CONFIGURATION
// ======================================================

$WAN2GP_URL = "http://192.168.1.53:7861";
$WAN2GP_TOKEN = "my-super-token-to-change";

$AUTO_REFRESH_SECONDS = 5;

// Si tu as créé wan2gp_download.php, laisse true.
// Sinon mets false pour afficher le lien API brut.
$USE_DOWNLOAD_PROXY = true;


// ======================================================
// API CALL
// ======================================================

function wan2gp_get($endpoint, $baseUrl, $token) {
    $url = rtrim($baseUrl, "/") . $endpoint;

    $ch = curl_init($url);

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            "Authorization: Bearer " . $token
        ],
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_TIMEOUT => 15,
    ]);

    $response = curl_exec($ch);
    $error = curl_error($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);

    curl_close($ch);

    if ($response === false) {
        return [
            "ok" => false,
            "error" => "Erreur CURL : " . $error,
            "http_code" => $httpCode,
            "data" => null
        ];
    }

    $data = json_decode($response, true);

    if ($httpCode < 200 || $httpCode >= 300) {
        return [
            "ok" => false,
            "error" => "Erreur HTTP " . $httpCode,
            "http_code" => $httpCode,
            "raw" => $response,
            "data" => $data
        ];
    }

    return [
        "ok" => true,
        "error" => null,
        "http_code" => $httpCode,
        "data" => $data
    ];
}

$health = wan2gp_get("/health", $WAN2GP_URL, $WAN2GP_TOKEN);
$model = wan2gp_get("/model", $WAN2GP_URL, $WAN2GP_TOKEN);
$jobsResponse = wan2gp_get("/jobs", $WAN2GP_URL, $WAN2GP_TOKEN);

$jobs = [];

if ($jobsResponse["ok"] && isset($jobsResponse["data"]["jobs"]) && is_array($jobsResponse["data"]["jobs"])) {
    $jobs = $jobsResponse["data"]["jobs"];
}


// ======================================================
// HELPERS
// ======================================================

function h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES, "UTF-8");
}

function status_badge_class($status) {
    switch ($status) {
        case "queued":
            return "badge queued";
        case "running":
            return "badge running";
        case "completed":
            return "badge completed";
        case "failed":
            return "badge failed";
        default:
            return "badge unknown";
    }
}

function mode_badge_class($apiMode) {
    switch ($apiMode) {
        case "t2v":
            return "mode-badge t2v";
        case "i2v":
            return "mode-badge i2v";
        case "i2v_end":
            return "mode-badge i2v-end";
        case "s2v":
            return "mode-badge s2v";
        case "s2v_i2v":
            return "mode-badge s2v-i2v";
        case "s2v_i2v_lora":
            return "mode-badge s2v-i2v-lora";
        default:
            return "mode-badge unknown";
    }
}

function format_mode_label($job) {
    $apiMode = $job["api_mode"] ?? "";

    switch ($apiMode) {
        case "t2v":
            return "Texte → Vidéo";
        case "i2v":
            return "Image → Vidéo";
        case "i2v_end":
            return "Image début + fin";
        case "s2v":
            return "Audio → Vidéo";
        case "s2v_i2v":
            return "Audio + Image";
        case "s2v_i2v_lora":
            return "Audio + Image + LoRA";
        default:
            return $job["mode"] ?? "Mode inconnu";
    }
}

function format_date_value($value) {
    if (!$value) {
        return "";
    }

    $timestamp = strtotime($value);

    if (!$timestamp) {
        return $value;
    }

    return date("d/m/Y H:i:s", $timestamp);
}

function seconds_between_dates($start, $end) {
    if (!$start || !$end) {
        return null;
    }

    $startTs = strtotime($start);
    $endTs = strtotime($end);

    if (!$startTs || !$endTs) {
        return null;
    }

    $diff = $endTs - $startTs;

    if ($diff < 0) {
        return null;
    }

    return $diff;
}

function format_duration_seconds($seconds) {
    if ($seconds === null) {
        return "";
    }

    $seconds = (int)$seconds;

    $hours = intdiv($seconds, 3600);
    $minutes = intdiv($seconds % 3600, 60);
    $secs = $seconds % 60;

    if ($hours > 0) {
        return sprintf("%dh %02dm %02ds", $hours, $minutes, $secs);
    }

    if ($minutes > 0) {
        return sprintf("%dm %02ds", $minutes, $secs);
    }

    return sprintf("%ds", $secs);
}

function generation_duration($job) {
    $started = $job["started_at"] ?? "";
    $finished = $job["finished_at"] ?? "";

    if (!$started) {
        return "";
    }

    if (($job["status"] ?? "") === "running") {
        $startTs = strtotime($started);

        if (!$startTs) {
            return "";
        }

        return format_duration_seconds(time() - $startTs) . " en cours";
    }

    $diff = seconds_between_dates($started, $finished);

    if ($diff === null) {
        return "";
    }

    return format_duration_seconds($diff);
}

function first_download_url($job) {
    if (!isset($job["download_urls"]) || !is_array($job["download_urls"]) || count($job["download_urls"]) === 0) {
        return null;
    }

    return $job["download_urls"][0];
}

function is_active_job($job) {
    return in_array($job["status"] ?? "", ["queued", "running"], true);
}

function is_completed_job($job) {
    return ($job["status"] ?? "") === "completed";
}

function is_failed_job($job) {
    return ($job["status"] ?? "") === "failed";
}

function get_requester_ip($job) {
    return $job["requester_ip"]
        ?? $job["client_ip"]
        ?? $job["remote_addr"]
        ?? "";
}

function basename_or_empty($value) {
    if (!$value) {
        return "";
    }

    return basename((string)$value);
}

function prompt_excerpt($text, $limit = 500) {
    $text = (string)$text;

    if (function_exists("mb_strimwidth")) {
        return mb_strimwidth($text, 0, $limit, "...", "UTF-8");
    }

    if (strlen($text) > $limit) {
        return substr($text, 0, $limit) . "...";
    }

    return $text;
}

function build_download_href($job, $downloadUrl, $wan2gpUrl, $useProxy) {
    if (!$downloadUrl) {
        return null;
    }

    if ($useProxy) {
        $jobId = $job["job_id"] ?? "";
        $path = parse_url($downloadUrl, PHP_URL_PATH);
        $filename = basename($path ?: "");

        if ($jobId && $filename) {
            return "wan2gp_download.php?job_id=" . rawurlencode($jobId) . "&filename=" . rawurlencode($filename);
        }
    }

    return rtrim($wan2gpUrl, "/") . $downloadUrl;
}

function count_by_mode($jobs, $mode) {
    $count = 0;

    foreach ($jobs as $job) {
        if (($job["api_mode"] ?? "") === $mode) {
            $count++;
        }
    }

    return $count;
}

$activeJobs = array_filter($jobs, "is_active_job");
$completedJobs = array_filter($jobs, "is_completed_job");
$failedJobs = array_filter($jobs, "is_failed_job");

$modeCounts = [
    "t2v" => count_by_mode($jobs, "t2v"),
    "i2v" => count_by_mode($jobs, "i2v"),
    "i2v_end" => count_by_mode($jobs, "i2v_end"),
    "s2v" => count_by_mode($jobs, "s2v"),
    "s2v_i2v" => count_by_mode($jobs, "s2v_i2v"),
    "s2v_i2v_lora" => count_by_mode($jobs, "s2v_i2v_lora"),
];
?>
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Wan2GP Queue Monitor V2</title>
    <meta http-equiv="refresh" content="<?php echo (int)$AUTO_REFRESH_SECONDS; ?>">
    <style>
        :root {
            --bg: #0f1117;
            --panel: #171a23;
            --panel2: #202431;
            --panel3: #11141c;
            --text: #f3f4f6;
            --muted: #9ca3af;
            --border: #2d3342;

            --queued: #f59e0b;
            --running: #38bdf8;
            --completed: #22c55e;
            --failed: #ef4444;
            --unknown: #94a3b8;

            --t2v: #a78bfa;
            --i2v: #60a5fa;
            --i2v-end: #34d399;
            --s2v: #f472b6;
            --s2v-i2v: #fbbf24;
            --s2v-i2v-lora: #fb7185;
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            padding: 24px;
            background: radial-gradient(circle at top, #1d2230, var(--bg));
            color: var(--text);
            font-family: Arial, Helvetica, sans-serif;
        }

        h1 {
            margin: 0 0 8px;
            font-size: 28px;
        }

        .subtitle {
            color: var(--muted);
            margin-bottom: 24px;
            line-height: 1.5;
        }

        .top-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(150px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .mode-grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(130px, 1fr));
            gap: 12px;
            margin-bottom: 24px;
        }

        .card {
            background: rgba(23, 26, 35, 0.92);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            box-shadow: 0 12px 28px rgba(0,0,0,0.25);
        }

        .card-title {
            color: var(--muted);
            font-size: 13px;
            margin-bottom: 8px;
        }

        .card-value {
            font-size: 26px;
            font-weight: bold;
        }

        .section {
            margin-top: 28px;
        }

        .section h2 {
            font-size: 20px;
            margin-bottom: 12px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(23, 26, 35, 0.92);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
        }

        th, td {
            padding: 12px 10px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
            text-align: left;
            font-size: 14px;
        }

        th {
            background: var(--panel2);
            color: #d1d5db;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            position: sticky;
            top: 0;
            z-index: 2;
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: rgba(255,255,255,0.025);
        }

        .badge,
        .mode-badge {
            display: inline-block;
            padding: 5px 9px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: bold;
            color: #050505;
            white-space: nowrap;
        }

        .badge.queued {
            background: var(--queued);
        }

        .badge.running {
            background: var(--running);
        }

        .badge.completed {
            background: var(--completed);
        }

        .badge.failed {
            background: var(--failed);
            color: white;
        }

        .badge.unknown {
            background: var(--unknown);
        }

        .mode-badge.t2v {
            background: var(--t2v);
        }

        .mode-badge.i2v {
            background: var(--i2v);
        }

        .mode-badge.i2v-end {
            background: var(--i2v-end);
        }

        .mode-badge.s2v {
            background: var(--s2v);
        }

        .mode-badge.s2v-i2v {
            background: var(--s2v-i2v);
        }

        .mode-badge.s2v-i2v-lora {
            background: var(--s2v-i2v-lora);
            color: #111827;
        }

        .mode-badge.unknown {
            background: var(--unknown);
        }

        .progress-wrap {
            width: 160px;
            height: 12px;
            background: #0b0d12;
            border-radius: 999px;
            overflow: hidden;
            border: 1px solid var(--border);
        }

        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #22c55e);
            width: 0%;
        }

        .progress-text {
            color: var(--muted);
            font-size: 12px;
            margin-top: 4px;
        }

        .prompt {
            max-width: 460px;
            color: #e5e7eb;
            line-height: 1.35;
            white-space: normal;
        }

        .small {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.45;
        }

        .mono {
            font-family: Consolas, Monaco, monospace;
            font-size: 12px;
            color: #cbd5e1;
            word-break: break-all;
        }

        .input-list {
            margin-top: 6px;
            padding: 8px;
            background: var(--panel3);
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        .input-list div {
            margin-bottom: 4px;
        }

        .input-list div:last-child {
            margin-bottom: 0;
        }

        a {
            color: #93c5fd;
            text-decoration: none;
        }

        a:hover {
            text-decoration: underline;
        }

        .button-link {
            display: inline-block;
            padding: 8px 11px;
            background: #2563eb;
            color: white;
            border-radius: 10px;
            text-decoration: none;
            font-weight: bold;
            font-size: 13px;
        }

        .button-link:hover {
            background: #1d4ed8;
            text-decoration: none;
        }

        .error {
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.45);
            color: #fecaca;
            padding: 16px;
            border-radius: 14px;
            margin-bottom: 20px;
        }

        .ok {
            color: #86efac;
        }

        .ko {
            color: #fca5a5;
        }

        .warn {
            color: #fde68a;
        }

        .footer {
            margin-top: 24px;
            color: var(--muted);
            font-size: 12px;
        }

        pre {
            white-space: pre-wrap;
            word-break: break-word;
            background: #0b0d12;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 8px;
            color: #fecaca;
        }

        @media (max-width: 1300px) {
            .top-grid {
                grid-template-columns: repeat(2, minmax(160px, 1fr));
            }

            .mode-grid {
                grid-template-columns: repeat(2, minmax(140px, 1fr));
            }

            table {
                display: block;
                overflow-x: auto;
            }
        }
    </style>
</head>
<body>

<h1>Wan2GP Queue Monitor V2</h1>

<div class="subtitle">
    Serveur : <span class="mono"><?php echo h($WAN2GP_URL); ?></span><br>
    Rafraîchissement automatique : <?php echo (int)$AUTO_REFRESH_SECONDS; ?> s |
    Page générée à <?php echo date("d/m/Y H:i:s"); ?>
</div>

<?php if (!$health["ok"]): ?>
    <div class="error">
        Impossible de joindre le serveur Wan2GP.<br>
        <?php echo h($health["error"]); ?><br>
        <?php if (isset($health["raw"])): ?>
            <pre><?php echo h($health["raw"]); ?></pre>
        <?php endif; ?>
    </div>
<?php endif; ?>

<div class="top-grid">
    <div class="card">
        <div class="card-title">API</div>
        <div class="card-value <?php echo $health["ok"] ? "ok" : "ko"; ?>">
            <?php echo $health["ok"] ? "OK" : "KO"; ?>
        </div>
    </div>

    <div class="card">
        <div class="card-title">Total jobs</div>
        <div class="card-value"><?php echo count($jobs); ?></div>
    </div>

    <div class="card">
        <div class="card-title">Jobs actifs</div>
        <div class="card-value"><?php echo count($activeJobs); ?></div>
    </div>

    <div class="card">
        <div class="card-title">Terminés</div>
        <div class="card-value"><?php echo count($completedJobs); ?></div>
    </div>

    <div class="card">
        <div class="card-title">Échecs</div>
        <div class="card-value"><?php echo count($failedJobs); ?></div>
    </div>
</div>

<div class="mode-grid">
    <div class="card">
        <div class="card-title">t2v</div>
        <div class="card-value"><?php echo $modeCounts["t2v"]; ?></div>
    </div>
    <div class="card">
        <div class="card-title">i2v</div>
        <div class="card-value"><?php echo $modeCounts["i2v"]; ?></div>
    </div>
    <div class="card">
        <div class="card-title">i2v_end</div>
        <div class="card-value"><?php echo $modeCounts["i2v_end"]; ?></div>
    </div>
    <div class="card">
        <div class="card-title">s2v</div>
        <div class="card-value"><?php echo $modeCounts["s2v"]; ?></div>
    </div>
    <div class="card">
        <div class="card-title">s2v_i2v</div>
        <div class="card-value"><?php echo $modeCounts["s2v_i2v"]; ?></div>
    </div>
    <div class="card">
        <div class="card-title">s2v_i2v_lora</div>
        <div class="card-value"><?php echo $modeCounts["s2v_i2v_lora"]; ?></div>
    </div>
</div>

<div class="card">
    <div class="card-title">Modèle</div>
    <?php if ($model["ok"]): ?>
        <div>
            <strong><?php echo h($model["data"]["display_name"] ?? ""); ?></strong><br>
            <span class="mono"><?php echo h($model["data"]["model_type"] ?? ""); ?></span>
        </div>

        <?php if (!empty($model["data"]["templates"]) && is_array($model["data"]["templates"])): ?>
            <div class="small" style="margin-top: 8px;">
                Templates chargés :
                <?php echo count($model["data"]["templates"]); ?>
            </div>
        <?php endif; ?>
    <?php else: ?>
        <div class="ko">Impossible de récupérer les informations du modèle.</div>
    <?php endif; ?>
</div>

<div class="section">
    <h2>File d’attente et historique</h2>

    <?php if (!$jobsResponse["ok"]): ?>
        <div class="error">
            Impossible de récupérer les jobs.<br>
            <?php echo h($jobsResponse["error"]); ?>
            <?php if (isset($jobsResponse["raw"])): ?>
                <pre><?php echo h($jobsResponse["raw"]); ?></pre>
            <?php endif; ?>
        </div>
    <?php elseif (count($jobs) === 0): ?>
        <div class="card">
            Aucun job connu pour le moment.
        </div>
    <?php else: ?>
        <table>
            <thead>
                <tr>
                    <th>Statut</th>
                    <th>Queue</th>
                    <th>Type</th>
                    <th>Progression</th>
                    <th>Demande</th>
                    <th>Machine</th>
                    <th>Prompt</th>
                    <th>Entrées</th>
                    <th>Temps</th>
                    <th>Résultat</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($jobs as $job): ?>
                <?php
                    $status = $job["status"] ?? "unknown";
                    $apiMode = $job["api_mode"] ?? "";
                    $progress = isset($job["progress"]) ? (float)$job["progress"] : 0;
                    $progress = max(0, min(100, $progress));

                    $downloadUrl = first_download_url($job);
                    $downloadHref = build_download_href($job, $downloadUrl, $WAN2GP_URL, $USE_DOWNLOAD_PROXY);

                    $realDuration = generation_duration($job);
                    $requesterIp = get_requester_ip($job);
                ?>
                <tr>
                    <td>
                        <span class="<?php echo h(status_badge_class($status)); ?>">
                            <?php echo h($status); ?>
                        </span>
                        <div class="small">
                            <?php echo h($job["short_status"] ?? ""); ?>
                        </div>
                    </td>

                    <td>
                        <?php if (array_key_exists("queue_position", $job) && $job["queue_position"] !== null): ?>
                            <strong>#<?php echo h($job["queue_position"]); ?></strong>
                        <?php else: ?>
                            <span class="small">hors file</span>
                        <?php endif; ?>
                    </td>

                    <td>
                        <span class="<?php echo h(mode_badge_class($apiMode)); ?>">
                            <?php echo h($apiMode ?: "legacy"); ?>
                        </span>
                        <div class="small" style="margin-top: 6px;">
                            <?php echo h(format_mode_label($job)); ?>
                        </div>
                        <div class="small">
                            <?php echo h($job["mode"] ?? ""); ?>
                        </div>

                        <?php if (!empty($job["activated_loras"])): ?>
                            <div class="small warn" style="margin-top: 6px;">
                                LoRA actif
                            </div>
                        <?php endif; ?>
                    </td>

                    <td>
                        <div class="progress-wrap">
                            <div class="progress-bar" style="width: <?php echo h($progress); ?>%;"></div>
                        </div>
                        <div class="progress-text">
                            <?php echo h($progress); ?>%
                        </div>
                        <div class="small">
                            Phase : <?php echo h($job["phase"] ?? ""); ?><br>
                            Étape : <?php echo h($job["current_step"] ?? ""); ?>/<?php echo h($job["total_steps"] ?? ""); ?><br>
                            Message : <?php echo h($job["message"] ?? ""); ?>
                        </div>
                    </td>

                    <td>
                        <div class="small">
                            Résolution : <strong><?php echo h($job["resolution"] ?? ""); ?></strong><br>
                            Vidéo demandée : <strong><?php echo h($job["duration_seconds"] ?? ""); ?>s</strong><br>
                            FPS : <strong><?php echo h($job["fps"] ?? ""); ?></strong><br>
                            Seed : <span class="mono"><?php echo h($job["seed"] ?? ""); ?></span><br>
                            Job ID : <span class="mono"><?php echo h($job["job_id"] ?? ""); ?></span>
                        </div>
                    </td>

                    <td>
                        <?php if ($requesterIp): ?>
                            <span class="mono"><?php echo h($requesterIp); ?></span>
                        <?php else: ?>
                            <span class="small warn">Non renseignée</span>
                            <div class="small">
                                Ajoute requester_ip côté API pour afficher l’IP cliente.
                            </div>
                        <?php endif; ?>
                    </td>

                    <td>
                        <div class="prompt">
                            <?php echo nl2br(h(prompt_excerpt($job["prompt"] ?? "", 500))); ?>
                        </div>
                    </td>

                    <td>
                        <div class="input-list small">
                            <?php if (!empty($job["input_image"])): ?>
                                <div>Image : <span class="mono"><?php echo h(basename_or_empty($job["input_image"])); ?></span></div>
                            <?php endif; ?>

                            <?php if (!empty($job["input_image_start"])): ?>
                                <div>Début : <span class="mono"><?php echo h(basename_or_empty($job["input_image_start"])); ?></span></div>
                            <?php endif; ?>

                            <?php if (!empty($job["input_image_end"])): ?>
                                <div>Fin : <span class="mono"><?php echo h(basename_or_empty($job["input_image_end"])); ?></span></div>
                            <?php endif; ?>

                            <?php if (!empty($job["input_audio"])): ?>
                                <div>Audio : <span class="mono"><?php echo h(basename_or_empty($job["input_audio"])); ?></span></div>
                            <?php endif; ?>

                            <?php if (!empty($job["activated_loras"]) && is_array($job["activated_loras"])): ?>
                                <div>LoRA :
                                    <?php foreach ($job["activated_loras"] as $lora): ?>
                                        <div class="mono"><?php echo h(basename_or_empty($lora)); ?></div>
                                    <?php endforeach; ?>
                                </div>
                                <div>Multiplier : <span class="mono"><?php echo h($job["loras_multipliers"] ?? ""); ?></span></div>
                            <?php endif; ?>

                            <?php
                                $hasInput =
                                    !empty($job["input_image"]) ||
                                    !empty($job["input_image_start"]) ||
                                    !empty($job["input_image_end"]) ||
                                    !empty($job["input_audio"]) ||
                                    !empty($job["activated_loras"]);
                            ?>

                            <?php if (!$hasInput): ?>
                                <span class="small">Aucune entrée fichier</span>
                            <?php endif; ?>
                        </div>

                        <?php if (!empty($job["errors"])): ?>
                            <div class="small ko" style="margin-top: 8px;">
                                Erreurs :
                                <pre><?php echo h(json_encode($job["errors"], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)); ?></pre>
                            </div>
                        <?php endif; ?>
                    </td>

                    <td>
                        <div class="small">
                            Créé : <?php echo h(format_date_value($job["created_at"] ?? "")); ?><br>
                            Début : <?php echo h(format_date_value($job["started_at"] ?? "")); ?><br>
                            Fin : <?php echo h(format_date_value($job["finished_at"] ?? "")); ?><br>
                            MAJ : <?php echo h(format_date_value($job["updated_at"] ?? "")); ?><br>
                            <br>
                            Durée réelle : 
                            <?php if ($realDuration): ?>
                                <strong><?php echo h($realDuration); ?></strong>
                            <?php else: ?>
                                <span class="small">non disponible</span>
                            <?php endif; ?>
                        </div>
                    </td>

                    <td>
                        <?php if ($downloadHref): ?>
                            <a class="button-link" href="<?php echo h($downloadHref); ?>" target="_blank">
                                Télécharger MP4
                            </a>

                            <?php if (!$USE_DOWNLOAD_PROXY): ?>
                                <div class="small" style="margin-top: 8px;">
                                    Attention : le lien API direct nécessite le header Authorization.
                                </div>
                            <?php endif; ?>
                        <?php else: ?>
                            <span class="small">Pas encore prêt</span>
                        <?php endif; ?>

                        <?php if (!empty($job["files"])): ?>
                            <div class="small" style="margin-top: 8px;">
                                <?php foreach ($job["files"] as $file): ?>
                                    <div class="mono"><?php echo h($file); ?></div>
                                <?php endforeach; ?>
                            </div>
                        <?php endif; ?>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    <?php endif; ?>
</div>

<div class="footer">
    Wan2GP Queue Monitor V2 |
    Page générée à <?php echo date("d/m/Y H:i:s"); ?> |
    Jobs en mémoire uniquement côté API.
</div>

</body>
</html>
