<?php
/**
 * Whisper Transcriber Suite — transcription usage stats endpoint (P4-4).
 *
 * A minimal GET/POST recorder. POST `form_submitted=1` (plus the fields
 * below) to insert one usage row; a bare GET shows the SQLite version and a
 * tiny form (handy for a manual smoke test). Callable from the desktop app
 * via python `requests`/`urllib` (application/x-www-form-urlencoded).
 *
 * It records, per transcription:
 *   - client IP            (REMOTE_ADDR of the request)
 *   - country_name         (extracted from the geoip JSON below)
 *   - ip_location_json     (the FULL geoip JSON for that IP)
 *   - file_name            (basename only — the app strips the path)
 *   - model, language
 *   - audio_duration       (seconds)
 *   - transcription_time   (seconds of AI compute)
 *   - status               (finished / error / cancelled / ...)
 *   - word_count           (total words in the transcript)
 *   - program_version      (the sending app's version string)
 *   - platform_system/_node/_release/_version/_machine/_processor
 *                          (Python's ``platform`` module facts about the host)
 *   - cpu_count / mem_total (``psutil`` CPU count / total RAM in bytes)
 *
 * GeoIP is fetched server-side from:
 *   https://smch.ir/stats/geoip/index.php?ip={ip}
 * whose response looks like:
 *   {"status":"success","country":"Switzerland","countryCode":"CH",...}
 *
 * Connection/driver style mirrors the maintainer's other PDO-SQLite stats
 * pages (a plain `new PDO("sqlite:...")`), but the code here is purpose-built
 * and minimal — it deliberately does NOT reuse robot-stats.php.
 */

error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);

if (function_exists('opcache_invalidate')) {
    opcache_invalidate(__FILE__, true);
}

date_default_timezone_set('Europe/Paris');

// --- database ---------------------------------------------------------------
// One file next to this script. PDO SQLite driver, same as the sibling stats
// pages. The table is created on first run (idempotent).
$db = new PDO('sqlite:' . __DIR__ . '/transcription_stats.db');
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

$db->exec(
    'CREATE TABLE IF NOT EXISTS transcription_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_time TEXT,
        client_ip TEXT,
        country_name TEXT,
        ip_location_json TEXT,
        file_name TEXT,
        model TEXT,
        language TEXT,
        audio_duration REAL,
        transcription_time REAL,
        word_count INTEGER,
        status TEXT,
        program_version TEXT,
        platform_system TEXT,
        platform_node TEXT,
        platform_release TEXT,
        platform_version TEXT,
        platform_machine TEXT,
        platform_processor TEXT,
        cpu_count INTEGER,
        mem_total INTEGER
    )'
);

// --- migration: add the newer columns to a DB created before they existed --
// CREATE TABLE IF NOT EXISTS only shapes a BRAND NEW file — an already
// -deployed transcription_stats.db from an older release keeps its original
// columns forever unless retrofitted here. SQLite has no
// "ADD COLUMN IF NOT EXISTS", so check PRAGMA table_info first and only add
// what's actually missing (idempotent across every request).
$existing_cols = array();
foreach ($db->query('PRAGMA table_info(transcription_stats)') as $col_row) {
    $existing_cols[$col_row['name']] = true;
}
$new_columns = array(
    'program_version'    => 'TEXT',
    'platform_system'    => 'TEXT',
    'platform_node'      => 'TEXT',
    'platform_release'   => 'TEXT',
    'platform_version'   => 'TEXT',
    'platform_machine'   => 'TEXT',
    'platform_processor' => 'TEXT',
    'cpu_count'          => 'INTEGER',
    'mem_total'          => 'INTEGER',
);
foreach ($new_columns as $col_name => $col_type) {
    if (!isset($existing_cols[$col_name])) {
        $db->exec("ALTER TABLE transcription_stats ADD COLUMN $col_name $col_type");
    }
}

// --- geoip lookup -----------------------------------------------------------
/**
 * Fetch the geoip JSON for $ip and return [country_name, raw_json_string].
 * Best-effort: on any failure returns ['', ''] so a recorded row never blocks
 * on the lookup.
 */
function lookup_geoip($ip) {
    $country = '';
    $raw = '';
    if ($ip === '') {
        return array($country, $raw);
    }
    $url = 'https://smch.ir/stats/geoip/index.php?ip=' . urlencode($ip);
    try {
        $ctx = stream_context_create(array(
            'http' => array('timeout' => 4),
            'ssl'  => array('verify_peer' => false, 'verify_peer_name' => false),
        ));
        $raw = @file_get_contents($url, false, $ctx);
        if ($raw === false) {
            $raw = '';
        }
        if ($raw !== '') {
            $json = json_decode($raw);
            if (is_object($json) && isset($json->status) && $json->status === 'success'
                && isset($json->country)) {
                $country = (string) $json->country;
            }
        }
    } catch (Exception $e) {
        // Swallow — geoip is decoration, not a requirement.
        $country = '';
    }
    return array($country, $raw);
}

// --- record a row -----------------------------------------------------------
$recorded = false;
if (isset($_POST['form_submitted'])) {
    $client_ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
    list($country_name, $ip_location_json) = lookup_geoip($client_ip);

    $file_name = isset($_POST['file_name']) ? basename((string) $_POST['file_name']) : '';
    $model = isset($_POST['model']) ? (string) $_POST['model'] : '';
    $language = isset($_POST['language']) ? (string) $_POST['language'] : '';
    $audio_duration = isset($_POST['audio_duration']) ? (float) $_POST['audio_duration'] : 0.0;
    $transcription_time = isset($_POST['transcription_time']) ? (float) $_POST['transcription_time'] : 0.0;
    $word_count = isset($_POST['word_count']) ? (int) $_POST['word_count'] : 0;
    $status = isset($_POST['status']) ? (string) $_POST['status'] : '';
    $program_version = isset($_POST['program_version']) ? (string) $_POST['program_version'] : '';
    $platform_system = isset($_POST['platform_system']) ? (string) $_POST['platform_system'] : '';
    $platform_node = isset($_POST['platform_node']) ? (string) $_POST['platform_node'] : '';
    $platform_release = isset($_POST['platform_release']) ? (string) $_POST['platform_release'] : '';
    $platform_version = isset($_POST['platform_version']) ? (string) $_POST['platform_version'] : '';
    $platform_machine = isset($_POST['platform_machine']) ? (string) $_POST['platform_machine'] : '';
    $platform_processor = isset($_POST['platform_processor']) ? (string) $_POST['platform_processor'] : '';
    $cpu_count = isset($_POST['cpu_count']) ? (int) $_POST['cpu_count'] : 0;
    $mem_total = isset($_POST['mem_total']) ? (int) $_POST['mem_total'] : 0;
    $server_time = date(DATE_RFC3339);

    $stmt = $db->prepare(
        'INSERT INTO transcription_stats
            (server_time, client_ip, country_name, ip_location_json,
             file_name, model, language, audio_duration, transcription_time,
             word_count, status, program_version, platform_system,
             platform_node, platform_release, platform_version,
             platform_machine, platform_processor, cpu_count, mem_total)
         VALUES
            (:server_time, :client_ip, :country_name, :ip_location_json,
             :file_name, :model, :language, :audio_duration, :transcription_time,
             :word_count, :status, :program_version, :platform_system,
             :platform_node, :platform_release, :platform_version,
             :platform_machine, :platform_processor, :cpu_count, :mem_total)'
    );
    $stmt->bindValue(':server_time', $server_time);
    $stmt->bindValue(':client_ip', $client_ip);
    $stmt->bindValue(':country_name', $country_name);
    $stmt->bindValue(':ip_location_json', $ip_location_json);
    $stmt->bindValue(':file_name', $file_name);
    $stmt->bindValue(':model', $model);
    $stmt->bindValue(':language', $language);
    $stmt->bindValue(':audio_duration', $audio_duration);
    $stmt->bindValue(':transcription_time', $transcription_time);
    $stmt->bindValue(':word_count', $word_count, PDO::PARAM_INT);
    $stmt->bindValue(':status', $status);
    $stmt->bindValue(':program_version', $program_version);
    $stmt->bindValue(':platform_system', $platform_system);
    $stmt->bindValue(':platform_node', $platform_node);
    $stmt->bindValue(':platform_release', $platform_release);
    $stmt->bindValue(':platform_version', $platform_version);
    $stmt->bindValue(':platform_machine', $platform_machine);
    $stmt->bindValue(':platform_processor', $platform_processor);
    $stmt->bindValue(':cpu_count', $cpu_count, PDO::PARAM_INT);
    $stmt->bindValue(':mem_total', $mem_total, PDO::PARAM_INT);
    $stmt->execute();
    $recorded = true;
}

// --- response ---------------------------------------------------------------
// Plain text so the python client can read a one-word confirmation cheaply.
header('Content-Type: text/plain; charset=UTF-8');

// Version string for the cosmetic banner. Read it from the PDO driver
// (pdo_sqlite) rather than the standalone SQLite3 class: many shared hosts
// ship pdo_sqlite WITHOUT the separate sqlite3 extension, so a static
// SQLite3::version() call would fatal there. Guard the lookup so a driver
// that does not expose ATTR_SERVER_VERSION still produces output.
try {
    $sqlite_version = (string) $db->getAttribute(PDO::ATTR_SERVER_VERSION);
} catch (Throwable $e) {
    $sqlite_version = 'unknown';
}
if ($recorded) {
    echo "OK\n";
} else {
    echo "Whisper Transcriber Suite transcription stats endpoint.\n";
    echo "SQLite " . $sqlite_version . "\n";
    echo "POST form_submitted=1 with: file_name, model, language, ";
    echo "audio_duration, transcription_time, word_count, status, ";
    echo "program_version, platform_system, platform_node, platform_release, ";
    echo "platform_version, platform_machine, platform_processor, ";
    echo "cpu_count, mem_total\n";
}
