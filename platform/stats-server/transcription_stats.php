<?php
/**
 * Whisper Transcriber Suite — usage stats endpoint.
 *
 * Deployment and data notes: README.md in this folder.
 *
 * POST `form_submitted=1` plus the fields below to insert one usage row; a
 * bare GET prints the SQLite version and the accepted fields (handy for a
 * manual smoke test). The desktop app posts
 * application/x-www-form-urlencoded from core/stats.py.
 *
 * Stored per transcription (every text field is length-capped and stripped
 * of control characters):
 *   - country_code         two-letter code the app reads from the operating
 *                          system's region setting; "" unless it is exactly
 *                          two upper-case letters
 *   - country_name         the same code, so viewers that show this older
 *                          column keep working (old rows hold a full name)
 *   - file_name            basename only (any path part is dropped)
 *   - model, language, status, program_version
 *   - audio_duration       (seconds)
 *   - transcription_time   (seconds of AI compute)
 *   - word_count           (total words in the transcript)
 *   - platform_system/_release/_version/_machine/_processor
 *   - cpu_count / mem_total (CPU count / total RAM in bytes)
 *
 * Not stored, not looked up, not forwarded: the network address of the
 * connection. This script reads nothing from the request but the POST body
 * and makes no outbound requests. The client_ip, ip_location_json and
 * platform_node columns stay in the table only so an existing database keeps
 * its old rows; new rows write "" into them. Web-server access logs are a
 * separate setting of the host (see README.md).
 */

error_reporting(E_ALL & ~E_NOTICE & ~E_WARNING);

if (function_exists('opcache_invalidate')) {
    opcache_invalidate(__FILE__, true);
}

date_default_timezone_set('Europe/Paris');

// --- input limits -----------------------------------------------------------
// Longest value kept per text field, in characters. Longer input is cut, so
// one request can never grow a row without bound.
$text_limits = array(
    'file_name'          => 255,
    'model'              => 128,
    'language'           => 32,
    'status'             => 32,
    'program_version'    => 32,
    'platform_system'    => 32,
    'platform_release'   => 64,
    'platform_version'   => 256,
    'platform_machine'   => 32,
    'platform_processor' => 128,
);

/**
 * $value without control characters, cut to $max_chars characters.
 * Bytes 0x00-0x1F and 0x7F never occur inside a multi-byte UTF-8 sequence,
 * so the byte-wise replace cannot split a character.
 */
function clean_text($value, $max_chars) {
    $value = preg_replace('/[\x00-\x1F\x7F]/', '', $value);
    if (!is_string($value)) {
        return '';
    }
    if (function_exists('mb_substr')) {
        return mb_substr($value, 0, $max_chars, 'UTF-8');
    }
    // No mbstring: cut whole characters when the value is valid UTF-8 (the
    // u modifier makes preg_match fail on invalid input), else cut bytes.
    if (preg_match('/^.{0,' . (int) $max_chars . '}/su', $value, $m)) {
        return $m[0];
    }
    return substr($value, 0, $max_chars);
}

/** The POSTed text field $name, cleaned and capped; "" when absent. */
function post_text($name, $max_chars) {
    if (!isset($_POST[$name]) || !is_string($_POST[$name])) {
        return '';
    }
    return clean_text($_POST[$name], $max_chars);
}

/** The POSTed file name reduced to its last path part, then capped. */
function post_file_basename($name, $max_chars) {
    if (!isset($_POST[$name]) || !is_string($_POST[$name])) {
        return '';
    }
    $value = str_replace('\\', '/', $_POST[$name]);
    $slash = strrpos($value, '/');
    if ($slash !== false) {
        $value = substr($value, $slash + 1);
    }
    return clean_text($value, $max_chars);
}

/** The POSTed number $name as a finite float in [0, $max]; 0.0 otherwise. */
function post_number($name, $max) {
    if (!isset($_POST[$name]) || !is_string($_POST[$name])
            || !is_numeric($_POST[$name])) {
        return 0.0;
    }
    $value = (float) $_POST[$name];
    if (!is_finite($value) || $value < 0) {
        return 0.0;
    }
    return min($value, (float) $max);
}

/** The POSTed whole number $name in [0, $max]; 0 otherwise. */
function post_int($name, $max) {
    $value = floor(post_number($name, $max));
    // A float at or above PHP_INT_MAX does not convert to int reliably
    // (32-bit PHP: anything above ~2.1e9).
    return $value >= PHP_INT_MAX ? PHP_INT_MAX : (int) $value;
}

/** The POSTed country code when it is exactly two upper-case letters. */
function post_country($name) {
    if (!isset($_POST[$name]) || !is_string($_POST[$name])) {
        return '';
    }
    // The D modifier stops `$` from also matching before a trailing newline.
    return preg_match('/^[A-Z]{2}$/D', $_POST[$name]) ? $_POST[$name] : '';
}

header('Content-Type: text/plain; charset=UTF-8');

try {
    // --- database -----------------------------------------------------------
    // One SQLite file next to this script (PDO driver). The table is created
    // on first run (idempotent).
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
            mem_total INTEGER,
            country_code TEXT
        )'
    );

    // --- migration: add newer columns to a database created before them -----
    // CREATE TABLE IF NOT EXISTS only shapes a brand-new file; an existing
    // transcription_stats.db keeps its columns unless retrofitted here.
    // SQLite has no "ADD COLUMN IF NOT EXISTS", so check PRAGMA table_info
    // and add only what is missing. Nothing is ever dropped or rewritten.
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
        'country_code'       => 'TEXT',
    );
    foreach ($new_columns as $col_name => $col_type) {
        if (!isset($existing_cols[$col_name])) {
            $db->exec("ALTER TABLE transcription_stats ADD COLUMN $col_name $col_type");
        }
    }

    // --- record a row -------------------------------------------------------
    $recorded = false;
    if (isset($_POST['form_submitted'])) {
        $country_code = post_country('country');

        $stmt = $db->prepare(
            'INSERT INTO transcription_stats
                (server_time, client_ip, country_name, ip_location_json,
                 file_name, model, language, audio_duration, transcription_time,
                 word_count, status, program_version, platform_system,
                 platform_node, platform_release, platform_version,
                 platform_machine, platform_processor, cpu_count, mem_total,
                 country_code)
             VALUES
                (:server_time, :client_ip, :country_name, :ip_location_json,
                 :file_name, :model, :language, :audio_duration, :transcription_time,
                 :word_count, :status, :program_version, :platform_system,
                 :platform_node, :platform_release, :platform_version,
                 :platform_machine, :platform_processor, :cpu_count, :mem_total,
                 :country_code)'
        );
        $stmt->bindValue(':server_time', date(DATE_RFC3339));
        // Kept columns from older versions; never filled any more.
        $stmt->bindValue(':client_ip', '');
        $stmt->bindValue(':ip_location_json', '');
        $stmt->bindValue(':platform_node', '');
        $stmt->bindValue(':country_code', $country_code);
        $stmt->bindValue(':country_name', $country_code);
        $stmt->bindValue(':file_name', post_file_basename('file_name', $text_limits['file_name']));
        foreach (array('model', 'language', 'status', 'program_version',
                       'platform_system', 'platform_release', 'platform_version',
                       'platform_machine', 'platform_processor') as $field) {
            $stmt->bindValue(':' . $field, post_text($field, $text_limits[$field]));
        }
        // Upper bounds: ~115 days of audio, 1e9 words, 4096 CPUs, 1 PB RAM.
        $stmt->bindValue(':audio_duration', post_number('audio_duration', 1e7));
        $stmt->bindValue(':transcription_time', post_number('transcription_time', 1e7));
        $stmt->bindValue(':word_count', post_int('word_count', 1e9), PDO::PARAM_INT);
        $stmt->bindValue(':cpu_count', post_int('cpu_count', 4096), PDO::PARAM_INT);
        $stmt->bindValue(':mem_total', post_int('mem_total', 1e15), PDO::PARAM_INT);
        $stmt->execute();
        $recorded = true;
    }

    // Version string for the GET banner. Read it from the PDO driver
    // (pdo_sqlite) rather than the standalone SQLite3 class: many shared hosts
    // ship pdo_sqlite WITHOUT the separate sqlite3 extension.
    try {
        $sqlite_version = (string) $db->getAttribute(PDO::ATTR_SERVER_VERSION);
    } catch (Throwable $e) {
        $sqlite_version = 'unknown';
    }
} catch (Throwable $e) {
    // No details in the response (they would show server paths); the
    // message goes to the host's PHP error log instead.
    error_log('transcription_stats: ' . $e->getMessage());
    http_response_code(500);
    echo "ERROR\n";
    exit;
}

// --- response ---------------------------------------------------------------
// Plain text so the python client can read a one-word confirmation cheaply.
if ($recorded) {
    echo "OK\n";
} else {
    echo "Whisper Transcriber Suite transcription stats endpoint.\n";
    echo "SQLite " . $sqlite_version . "\n";
    echo "POST form_submitted=1 with: country, file_name, model, language, ";
    echo "audio_duration, transcription_time, word_count, status, ";
    echo "program_version, platform_system, platform_release, ";
    echo "platform_version, platform_machine, platform_processor, ";
    echo "cpu_count, mem_total\n";
}
