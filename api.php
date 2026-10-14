<?php
/**
 * HTTPS Relay Endpoint for SSH Tunneling
 * 
 * Provides an intermediary message queue over HTTP(S) long-polling.
 * Requires PHP 7.4+ with write permissions to its script directory or system temp.
 */

error_reporting(0);
ini_set('display_errors', '0');

ignore_user_abort(true);
set_time_limit(60);

// Shared authentication secret (can be configured via environment variable or edited below)
$AUTH_KEY = getenv('RELAY_AUTH_TOKEN') ?: 'YOUR_SECRET_TOKEN_HERE';

$provided_key = $_GET['token'] ?? ($_SERVER['HTTP_X_AUTH_TOKEN'] ?? '');

if (empty($provided_key) || $provided_key !== $AUTH_KEY) {
    http_response_code(403);
    header('Content-Type: application/json');
    exit(json_encode(["error" => "Forbidden - Invalid or missing authentication token"]));
}

// Storage directory: Hidden folder in current directory with .htaccess protection, fallback to temp
$base_dir = __DIR__ . '/.relay_data';
if (!is_dir($base_dir)) {
    @mkdir($base_dir, 0777, true);
    @file_put_contents("{$base_dir}/.htaccess", "Deny from all\n");
}
if (!is_writable($base_dir)) {
    $base_dir = rtrim(sys_get_temp_dir(), '/') . '/ssh_relay_tunnels';
    if (!is_dir($base_dir)) {
        @mkdir($base_dir, 0777, true);
    }
}

$action  = $_GET['action'] ?? '';
$session = preg_replace('/[^a-zA-Z0-9_-]/', '', $_GET['session'] ?? '');
$target  = $_GET['target'] ?? '';

// 0. Diagnostic & Health Check
if ($action === 'diag') {
    header('Content-Type: application/json');
    $is_writable = is_writable($base_dir);
    echo json_encode([
        "status" => "OK",
        "storage_dir" => $base_dir,
        "is_writable" => $is_writable,
        "php_version" => PHP_VERSION,
        "time" => time()
    ]);
    exit;
}

// 1. Server mode: Wait for incoming connection requests (Long-poll)
if ($action === 'wait_connection') {
    header('Content-Type: text/plain');
    $queue_dir = "{$base_dir}/queue";
    if (!is_dir($queue_dir)) @mkdir($queue_dir, 0777, true);

    $start = microtime(true);
    while ((microtime(true) - $start) < 15.0) {
        $files = glob("{$queue_dir}/sess_*");
        if (!empty($files)) {
            $first_file = $files[0];
            $sess_name = basename($first_file);
            @unlink($first_file);
            echo $sess_name;
            exit;
        }
        usleep(25000); // 25ms polling interval
    }
    http_response_code(204);
    exit;
}

// 2. Client mode: Register new session
if ($action === 'register_session') {
    if (empty($session)) {
        http_response_code(400);
        exit("Missing Session ID");
    }
    $queue_dir = "{$base_dir}/queue";
    if (!is_dir($queue_dir)) @mkdir($queue_dir, 0777, true);
    @file_put_contents("{$queue_dir}/{$session}", time());

    @mkdir("{$base_dir}/{$session}/to_server", 0777, true);
    @mkdir("{$base_dir}/{$session}/to_client", 0777, true);
    @file_put_contents("{$base_dir}/{$session}/status.txt", "ACTIVE");
    echo "REGISTERED";
    exit;
}

// 3. Terminate Session & Cleanup
if ($action === 'close_session') {
    $sess_dir = "{$base_dir}/{$session}";
    @unlink("{$base_dir}/queue/{$session}");
    if (is_dir($sess_dir)) {
        @file_put_contents("{$sess_dir}/status.txt", "CLOSED");
        $files = glob("{$sess_dir}/*/*");
        if ($files) {
            foreach ($files as $f) {
                @unlink($f);
            }
        }
        @rmdir("{$sess_dir}/to_server");
        @rmdir("{$sess_dir}/to_client");
        @unlink("{$sess_dir}/status.txt");
        @rmdir($sess_dir);
    }
    echo "CLOSED";
    exit;
}

if (empty($session) || !in_array($target, ['to_server', 'to_client'])) {
    http_response_code(400);
    exit("Bad Request: Missing or invalid Session ID or Target");
}

$sess_dir = "{$base_dir}/{$session}";
$target_dir = "{$sess_dir}/{$target}";

// Check if session has been closed
if (!is_dir($sess_dir) || (file_exists("{$sess_dir}/status.txt") && trim((string)@file_get_contents("{$sess_dir}/status.txt")) === "CLOSED")) {
    http_response_code(410); // 410 Gone
    exit("SESSION_CLOSED");
}

// 4. Push binary chunk to relay queue
if ($action === 'push') {
    $seq = intval($_GET['seq'] ?? 0);
    $data = file_get_contents('php://input');
    if ($data !== false && strlen($data) > 0) {
        if (!is_dir($target_dir)) @mkdir($target_dir, 0777, true);
        $file = sprintf("%s/%08d.dat", $target_dir, $seq);
        $res = @file_put_contents($file, $data, LOCK_EX);
        if ($res === false) {
            http_response_code(500);
            exit("File write error in {$target_dir}");
        }
        clearstatcache(true, $file);
        echo "OK";
    } else {
        http_response_code(204);
    }
    exit;
}

// 5. Pull binary chunk from relay queue
if ($action === 'pull') {
    $seq = intval($_GET['seq'] ?? 0);
    $file = sprintf("%s/%08d.dat", $target_dir, $seq);

    header('Content-Type: application/octet-stream');
    header('Cache-Control: no-cache, no-store, must-revalidate');
    header('X-Accel-Buffering: no');

    $start = microtime(true);
    while ((microtime(true) - $start) < 6.0) {
        clearstatcache(true, $file);
        if (file_exists($file)) {
            $data = @file_get_contents($file);
            @unlink($file);
            $consumed = 1;

            // Batch up to 25 subsequent packets if already in queue
            while ($consumed < 25) {
                $next_seq = $seq + $consumed;
                $next_file = sprintf("%s/%08d.dat", $target_dir, $next_seq);
                clearstatcache(true, $next_file);
                if (file_exists($next_file)) {
                    $next_data = @file_get_contents($next_file);
                    @unlink($next_file);
                    if ($next_data !== false) {
                        $data .= $next_data;
                        $consumed++;
                        continue;
                    }
                }
                break;
            }

            header("X-Consumed: {$consumed}");
            echo $data;
            flush();
            exit;
        }

        // Early exit if session was closed while polling
        if (file_exists("{$sess_dir}/status.txt") && trim((string)@file_get_contents("{$sess_dir}/status.txt")) === "CLOSED") {
            http_response_code(410);
            exit("SESSION_CLOSED");
        }
        usleep(2000); // 2ms fast polling interval
    }
    http_response_code(204);
    exit;
}