#!/usr/bin/env python3
import socket
import gzip
import io
import os
import time
import argparse
import base64
import re
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor

# --- PATCH LEVEL IDENTIFICATION ---
SCRIPT_VERSION = "2.6.0-full-integrity"

# --- CLI Configuration ---
parser = argparse.ArgumentParser(description=f"High-Throughput Async UDP Telemetry Receiver Stack - Ver {SCRIPT_VERSION}")
parser.add_argument("--retention", type=int, default=30, help="Log retention period in days (default: 30)")
parser.add_argument("--display", type=str, default="false", choices=["true", "false"], help="Print decoded telemetry payload to stdout (default: false)")
args = parser.parse_args()

DISPLAY_CONTENT = args.display.lower() == "true"
RETENTION_SECONDS = args.retention * 24 * 60 * 60

UDP_IP = "0.0.0.0"
UDP_PORT = 555
BUFFER_SIZE = 65535
OUTPUT_DIR = "/var/log/telemetry_report"

CLUSTER_ID_PATTERN = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')

# Ensure system log directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

def process_completed_message(msg_id, source_ip, frames, total_frames, display_content):
    """Asynchronous worker function: validates signature against raw H, N, and R lines, maps indices, and logs output."""
    try:
        # 1. Atomic byte reconstruction of the segmented Gzip payload
        complete_gzip_payload = b"".join(frames[i] for i in range(1, total_frames + 1))

        # 2. Decompression execution
        with gzip.GzipFile(fileobj=io.BytesIO(complete_gzip_payload)) as f:
            raw_text = f.read().decode('utf-8')
        
        raw_lines = raw_text.strip().split('\n')
        
        # 3. Extract validation lines (Everything except the T line itself)
        protected_lines = []
        t_line = None
        for line in raw_lines:
            if line.startswith("T,"):
                t_line = line
            elif line.startswith("H,") or line.startswith("N,") or line.startswith("R,"):
                protected_lines.append(line)

        # 4. Perform Full SHA-256 Integrity Validation (H + N + R Included)
        integrity_status = "VERIFIED"
        calculated_hash = ""
        expected_hash = ""

        if not t_line:
            integrity_status = "FAILED - MISSING SIGNATURE"
        else:
            try:
                # Reconstruct full block text exactly as it was generated before compression
                hash_input = "\n".join(protected_lines) + "\n"
                calculated_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
                expected_hash = t_line.split(',', 1)[1].strip()
                
                if calculated_hash != expected_hash:
                    integrity_status = "FAILED - TAMPERED/CORRUPTED"
            except Exception:
                integrity_status = "FAILED - VALIDATION ERROR"

        # 5. Pre-extract the translation dictionary (R line mapping)
        lookup_table = {}
        for line in protected_lines:
            if line.startswith("R,"):
                lookup_table = extract_lookup_table(line)
                break

        # 6. Metric conversion and string restoration (Done on raw lines for human display/logs)
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

        # 7. Build Dynamic Audit Header embedding the validation status
        if integrity_status == "VERIFIED":
            audit_header = f"# [AUDIT] MSG {msg_id} from {source_ip} ({total_frames} frames) [INTEGRITY: OK]"
            print(f"[✓] Successfully processed MSG {msg_id} from {source_ip} (Integrity: OK)")
        else:
            audit_header = f"# [⚠️ CRITICAL INTEGRITY FAILURE] MSG {msg_id} from {source_ip} ({total_frames} frames) - STATUS: {integrity_status}\n# [DEBUG] Expected: {expected_hash}\n# [DEBUG] Calculated: {calculated_hash}"
            print(f"[✗] ALERT: MSG {msg_id} from {source_ip} failed validation! Status: {integrity_status}")

        final_report = audit_header + "\n" + "\n".join(processed_lines)
        
        # 8. Append telemetry metrics to system daily log file
        current_day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        output_file = os.path.join(OUTPUT_DIR, f"telemetry_{current_day}.log")
        
        with open(output_file, "a", encoding="utf-8") as out:
            out.write(final_report + "\n\n")

        # 9. Extract and store unique Cluster IDs from raw text
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
    sock.bind((UDP_IP, UDP_PORT))

    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024 * 32)
        print(f"[*] Kernel socket receive buffer successfully scaled to 32MB.")
    except Exception as e:
        print(f"[!] Warning: Unable to set peak SO_RCVBUF size (insufficient privileges?): {e}")

    print(f"[*] Async High-Throughput Server ready on UDP port {UDP_PORT}. Patch Level: {SCRIPT_VERSION}")
    print(f"[*] Absolute daily log reports storage path: {OUTPUT_DIR}")
    print("-" * 75)

    assembly_buffer = {}
    last_cleanup_time = time.time()

    with ProcessPoolExecutor() as executor:
        while True:
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
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
                        DISPLAY_CONTENT
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
