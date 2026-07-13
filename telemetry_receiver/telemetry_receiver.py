#!/usr/bin/env python3
import socket
import gzip
import io
import os
import time
import argparse
import base64
import re
import hmac
import hashlib
import subprocess
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# --- PATCH LEVEL IDENTIFICATION ---
SCRIPT_VERSION = "2.9.1-hardcoded-paths"

# --- CLI Configuration ---
parser = argparse.ArgumentParser(description=f"High-Throughput Async UDP Telemetry Receiver Stack - Ver {SCRIPT_VERSION}")
parser.add_argument("--retention", type=int, default=30, help="Log retention period in days (default: 30)")
parser.add_argument("--display", type=str, default="false", choices=["true", "false"], help="Print decoded telemetry payload to stdout (default: false)")
args = parser.parse_args()

DISPLAY_CONTENT = args.display.lower() == "true"
RETENTION_SECONDS = args.retention * 24 * 60 * 60

# --- HARDCODED SECURITY PATHS ---
SALT_FILE_PATH = "/etc/telemetry_salt.enc"
KEY_FILE_PATH = "/etc/.telemetry_key"
OUTPUT_DIR = "/var/log/telemetry_report"

CLUSTER_ID_PATTERN = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')

# Ensure system log directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- SECURE DECRYPTION FUNCTION ---
def load_encrypted_salt(salt_file, key_file):
    """Decrypts the salt file in-memory using a password read from a secure key file."""
    if not os.path.exists(salt_file):
        raise FileNotFoundError(f"Salt file not found at: {salt_file}")
    if not os.path.exists(key_file):
        raise FileNotFoundError(f"Decryption key file not found at: {key_file}. Please ensure it is created with permission 400.")
    
    cmd = [
        "openssl", "enc", "-d", "-aes-256-cbc", 
        "-pbkdf2", "-iter", "100000", 
        "-in", salt_file, 
        "-pass", f"file:{key_file}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        decrypted_salt = result.stdout
        if not decrypted_salt:
            raise ValueError("Decrypted salt value is empty.")
        return decrypted_salt
    except subprocess.CalledProcessError as e:
        print(f"[✗] OpenSSL Decryption Failed: {e.stderr.decode().strip()}")
        raise SystemExit("Error: Key file mismatch or corrupted encrypted salt file.")

# Securely load the salt into memory on start
try:
    HMAC_SALT = load_encrypted_salt(SALT_FILE_PATH, KEY_FILE_PATH)
except Exception as err:
    print(f"[✗] Initialization failure: {err}")
    raise SystemExit(1)

# --- METRICS RESTORATION & DECODING FUNCTIONS ---
def decode_epoch(epoch_str):
    """Converts a raw Unix Epoch string into a human-readable UTC timestamp."""
    try:
        epoch_val = int(epoch_str)
        if epoch_val <= 0:
            return "N/A"
        dt = datetime.fromtimestamp(epoch_val, tz=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except ValueError:
        return epoch_str

def extract_lookup_table(r_line):
    """Parses and decodes the Base64 'R' line to generate a dictionary mapping numeric indices to values."""
    mapping_table = {}
    try:
        base64_data = r_line.split(',', 1)[1].strip()
        decoded_str = base64.b64decode(base64_data).decode('utf-8')
        decoded_str = decoded_str.replace('#', ' ')
        
        segments = decoded_str.split(',')
        for segment in segments:
            if '=' in segment:
                k, v = segment.split('=', 1)
                mapping_table[k.strip()] = v.strip()
    except Exception:
        pass
    return mapping_table

def process_completed_message(msg_id, source_ip, frames, total_frames, display_content, salt_bytes):
    """Asynchronous worker function: validates signature against raw components using HMAC, maps indices, and logs output."""
    try:
        complete_gzip_payload = b"".join(frames[i] for i in range(1, total_frames + 1))

        with gzip.GzipFile(fileobj=io.BytesIO(complete_gzip_payload)) as f:
            raw_text = f.read().decode('utf-8')
        
        raw_lines = raw_text.strip().split('\n')
        
        protected_lines = []
        t_line = None
        for line in raw_lines:
            if line.startswith("T,"):
                t_line = line
            elif line.startswith("H,") or line.startswith("N,") or line.startswith("R,"):
                protected_lines.append(line)

        integrity_status = "VERIFIED"
        calculated_mac = ""
        expected_mac = ""

        if not t_line:
            integrity_status = "FAILED - MISSING SIGNATURE"
        else:
            try:
                hash_input = "\n".join(protected_lines) + "\n"
                
                hmac_obj = hmac.new(salt_bytes, hash_input.encode('utf-8'), hashlib.sha256)
                calculated_mac = hmac_obj.hexdigest()
                expected_mac = t_line.split(',', 1)[1].strip()
                
                if calculated_mac != expected_mac:
                    integrity_status = "FAILED - TAMPERED/CORRUPTED"
            except Exception:
                integrity_status = "FAILED - VALIDATION ERROR"

        lookup_table = {}
        for line in protected_lines:
            if line.startswith("R,"):
                lookup_table = extract_lookup_table(line)
                break

        processed_lines = []
        for line in raw_lines:  
            if line.startswith("H,"):
                fields = line.split(',')
                if len(fields) > 4:
                    if fields[3] in lookup_table: fields[3] = lookup_table[fields[3]]
                    if fields[4] in lookup_table: fields[4] = lookup_table[fields[4]]
                if len(fields) >= 8:
                    fields[5] = decode_epoch(fields[5])
                    fields[7] = decode_epoch(fields[7])
                processed_lines.append(",".join(fields))
                
            elif line.startswith("N,"):
                fields = line.split(',')
                if len(fields) > 2 and not fields[2].startswith("node-"):
                    fields[2] = f"node-{fields[2]}"  
                if len(fields) > 3 and fields[3] in lookup_table:
                    fields[3] = lookup_table[fields[3]]
                processed_lines.append(",".join(fields))
                
            else:
                processed_lines.append(line)

        if integrity_status == "VERIFIED":
            audit_header = f"# [AUDIT] MSG {msg_id} from {source_ip} ({total_frames} frames) [INTEGRITY: OK]"
            print(f"[✓] Successfully processed MSG {msg_id} from {source_ip} (Integrity: OK)")
        else:
            audit_header = f"# [⚠️ CRITICAL INTEGRITY FAILURE] MSG {msg_id} from {source_ip} ({total_frames} frames) - STATUS: {integrity_status}\n# [DEBUG] Expected HMAC: {expected_mac}\n# [DEBUG] Calculated HMAC: {calculated_mac}"
            print(f"[✗] ALERT: MSG {msg_id} from {source_ip} failed validation! Status: {integrity_status}")

        final_report = audit_header + "\n" + "\n".join(processed_lines)
        
        current_day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        output_file = os.path.join(OUTPUT_DIR, f"telemetry_{current_day}.log")
        
        with open(output_file, "a", encoding="utf-8") as out:
            out.write(final_report + "\n\n")

        discovered_ids = set(CLUSTER_ID_PATTERN.findall(raw_text))
        if discovered_ids:
            cid_file = os.path.join(OUTPUT_DIR, f"cluster_ids_{current_day}.log")
            existing_ids = set()
            
            if os.path.exists(cid_file):
                try:
                    with open(cid_file, "r", encoding="utf-8") as f:
                        existing_ids = set(line.strip() for line in f if line.strip())
                except Exception:
                    pass
            
            new_ids = discovered_ids - existing_ids
            if new_ids:
                try:
                    with open(cid_file, "a", encoding="utf-8") as f:
                        for cid in new_ids:
                            f.write(cid + "\n")
                except Exception:
                    pass
        
        if display_content:
            print(f"\n--- SOURCE IP: {source_ip} (MSG: {msg_id} - RESOLVED METRICS) ---\n{final_report}\n")
            
    except Exception as e:
        print(f"[✗] Async runtime failure processing MSG {msg_id} from {source_ip}: {e}")

def run_retention_cleanup():
    """Scans storage directory and deletes daily log files older than the configured threshold."""
    now = time.time()
    deleted_count = 0
    for filename in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, filename)
        if os.path.isfile(file_path) and (now - os.path.getmtime(file_path) > RETENTION_SECONDS):
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception:
                pass
    if deleted_count > 0:
        print(f"[🧹] Retention Policy Cleanup: Removed {deleted_count} obsolete log file(s).")

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 555))

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024 * 32)
        print(f"[*] Kernel socket receive buffer successfully scaled to 32MB.")
    except Exception as e:
        print(f"[!] Warning: Unable to set peak SO_RCVBUF size (insufficient privileges?): {e}")

    print(f"[*] Async High-Throughput Server ready on UDP port 555. Patch Level: {SCRIPT_VERSION}")
    print(f"[*] Absolute daily log reports storage path: {OUTPUT_DIR}")
    print(f"[*] Securely decrypted HMAC Verification Salt from '{SALT_FILE_PATH}' using key '{KEY_FILE_PATH}'")
    print("-" * 75)

    assembly_buffer = {}
    last_cleanup_time = time.time()

    with ProcessPoolExecutor() as executor:
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                source_ip = addr[0]

                if b'|' not in data:
                    continue

                try:
                    header_part, bin_part = data.split(b'|', 1)
                    header_str = header_part.decode('utf-8')
                    msg_id, frame_num_str, total_frames_str = header_str.split(',')
                    frame_num = int(frame_num_str)
                    total_frames = int(total_frames_str)
                except Exception:
                    continue

                if msg_id not in assembly_buffer:
                    assembly_buffer[msg_id] = {
                        "total": total_frames,
                        "frames": {},
                        "source": source_ip
                    }

                assembly_buffer[msg_id]["frames"][frame_num] = bin_part

                if len(assembly_buffer[msg_id]["frames"]) == assembly_buffer[msg_id]["total"]:
                    executor.submit(
                        process_completed_message,
                        msg_id,
                        source_ip,
                        assembly_buffer[msg_id]["frames"],
                        total_frames,
                        DISPLAY_CONTENT,
                        HMAC_SALT
                    )
                    del assembly_buffer[msg_id]

                if time.time() - last_cleanup_time > 300:
                    run_retention_cleanup()
                    last_cleanup_time = time.time()

            except KeyboardInterrupt:
                print("\n[*] Graceful server shutdown initiated.")
                break
            except Exception as general_err:
                print(f"[!] Global runtime socket loop exception caught: {general_err}")

    sock.close()

if __name__ == "__main__":
    main()
