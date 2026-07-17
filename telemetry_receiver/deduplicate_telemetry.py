#!/usr/bin/env python3
# deduplicate_telemetry.py
import os
import glob
import argparse
import shutil
from datetime import datetime, timezone

LOG_DIR = "/var/log/telemetry_report"
DEFAULT_DEDUP_FILE = "/var/log/telemetry_report/telemetry_deduplicated.csv"
BACKUP_RETENTION = 10

def get_file_date(file_path):
    match = os.path.basename(file_path).split('_')[-1].replace('.log', '')
    try:
        return datetime.strptime(match, "%Y-%m-%d").date()
    except ValueError:
        return None

def rotate_old_file(filepath):
    if not os.path.exists(filepath):
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{filepath}_{timestamp}.bak"
    print(f"[+] Saving old file backup to: {backup_file}")
    shutil.copy2(filepath, backup_file)

    dir_name = os.path.dirname(filepath)
    base_name = os.path.basename(filepath)
    backup_pattern = os.path.join(dir_name, f"{base_name}_*.bak")
    existing_backups = sorted(glob.glob(backup_pattern), key=os.path.getmtime)
    
    if len(existing_backups) > BACKUP_RETENTION:
        for f in existing_backups[:-BACKUP_RETENTION]:
            try:
                os.remove(f)
            except OSError:
                pass

def format_epoch_string(val):
    """Converts a raw epoch string into a human-readable UTC date string if applicable."""
    if not val:
        return "NotAvailable"
    if val.isdigit():
        try:
            epoch_int = int(val)
            return datetime.fromtimestamp(epoch_int, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        except (ValueError, OverflowError):
            pass
    return val.strip()

def parse_telemetry(start_date=None, end_date=None, last_day_only=False, output_file=DEFAULT_DEDUP_FILE):
    all_log_files = sorted(glob.glob(os.path.join(LOG_DIR, "telemetry_*.log")))
    if not all_log_files:
        print("No telemetry log files found.")
        return

    log_files_to_process = []
    if last_day_only:
        log_files_to_process = [all_log_files[-1]]
    else:
        for f in all_log_files:
            f_date = get_file_date(f)
            if not f_date:
                continue
            if start_date and f_date < start_date:
                continue
            if end_date and f_date > end_date:
                continue
            log_files_to_process.append(f)

    if not log_files_to_process:
        print("No logs matched the selected criteria.")
        return

    print(f"Deduplicating {len(log_files_to_process)} log files...")
    rotate_old_file(output_file)

    latest_headers = {}
    latest_nodes = {}
    latest_r_records = {}
    latest_t_records = {}

    for file_path in log_files_to_process:
        print(f" -> Processing: {os.path.basename(file_path)}")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                record_type = parts[0]

                if record_type == 'H' and len(parts) >= 8:
                    cluster_id = parts[1]
                    
                    # Convert indexes 4 (installed_at) and 6 (last_update) if they are raw numbers
                    parts[4] = format_epoch_string(parts[4])
                    parts[6] = format_epoch_string(parts[6])
                    
                    latest_headers[cluster_id] = ','.join(parts)
                    latest_nodes[cluster_id] = []
                elif record_type == 'N' and len(parts) >= 2:
                    cluster_id = parts[1]
                    if cluster_id not in latest_nodes:
                        latest_nodes[cluster_id] = []
                    latest_nodes[cluster_id].append(line)
                elif record_type in ['R', 'T']:
                    if latest_headers:
                        last_cluster_id = list(latest_headers.keys())[-1]
                        if record_type == 'R':
                            latest_r_records[last_cluster_id] = line
                        else:
                            latest_t_records[last_cluster_id] = line

    print(f"Writing clean deduplicated payload to: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as out:
        for cluster_id in sorted(latest_headers.keys()):
            out.write(latest_headers[cluster_id] + "\n")
            for node_line in latest_nodes.get(cluster_id, []):
                out.write(node_line + "\n")
            if cluster_id in latest_r_records:
                out.write(latest_r_records[cluster_id] + "\n")
            if cluster_id in latest_t_records:
                out.write(latest_t_records[cluster_id] + "\n")
    print("Deduplication process successfully completed!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate raw telemetry log streams.")
    parser.add_argument("--start", help="Start Date (YYYY-MM-DD)", type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
    parser.add_argument("--end", help="End Date (YYYY-MM-DD)", type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
    parser.add_argument("--last-day", action="store_true", help="Process only the latest available log file")
    parser.add_argument("--output", default=DEFAULT_DEDUP_FILE, help="Path to the output deduplicated file")
    args = parser.parse_args()
    parse_telemetry(start_date=args.start, end_date=args.end, last_day_only=args.last_day, output_file=args.output)
