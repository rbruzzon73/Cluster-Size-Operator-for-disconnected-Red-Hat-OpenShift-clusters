#!/usr/bin/env python3
import os
import glob
import sys
import argparse
import shutil
from datetime import datetime, date

LOG_DIR = "/var/log/telemetry_report"
DEFAULT_DEDUP_FILE = "/var/log/telemetry_report/telemetry_deduplicated.csv"
BACKUP_RETENTION = 10

def get_file_date(file_path):
    """Extracts date from filename formatted like prefix_YYYY-MM-DD.log."""
    match = os.path.basename(file_path).split('_')[-1].replace('.log', '')
    try:
        return datetime.strptime(match, "%Y-%m-%d").date()
    except ValueError:
        return None

def rotate_old_file(filepath):
    """Saves a timestamped backup of the output file and cleans up older backups."""
    if not os.path.exists(filepath):
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{filepath}_{timestamp}.bak"
    print(f"[+] Saving old file backup to: {os.path.basename(backup_file)}")
    shutil.copy2(filepath, backup_file)

    dir_name = os.path.dirname(filepath)
    base_name = os.path.basename(filepath)
    backup_pattern = os.path.join(dir_name, f"{base_name}_*.bak")
    existing_backups = sorted(glob.glob(backup_pattern), key=os.path.getmtime)
    
    if len(existing_backups) > BACKUP_RETENTION:
        files_to_delete = existing_backups[:-BACKUP_RETENTION]
        for f in files_to_delete:
            try:
                os.remove(f)
                print(f"[-] Removing expired backup file: {os.path.basename(f)}")
            except OSError as e:
                print(f"[WARNING] Failed to remove expired backup {f}: {e}")

def parse_telemetry(start_date=None, end_date=None, last_day_only=False, output_file=DEFAULT_DEDUP_FILE):
    """Deduplicates raw telemetry files while maintaining their native structure."""
    all_log_files = sorted(glob.glob(os.path.join(LOG_DIR, "telemetry_*.log")))
    if not all_log_files:
        print("No telemetry_*.log files discovered.")
        return

    log_files_to_process = []
    if last_day_only:
        log_files_to_process = [all_log_files[-1]]
        print(f"Running in 'Last Day Only' mode. Target file: {os.path.basename(log_files_to_process[0])}")
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
        print("No log files matched the specified date criteria.")
        return

    rotate_old_file(output_file)
    print(f"Deduplicating {len(log_files_to_process)} log files...")

    latest_headers = {}
    latest_nodes = {}
    latest_r_records = {}
    latest_t_records = {}

    for file_path in log_files_to_process:
        print(f" -> Processing: {os.path.basename(file_path)}")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                record_type = parts[0]

                if record_type == 'H' and len(parts) >= 2:
                    cluster_id = parts[1]
                    latest_headers[cluster_id] = line
                    latest_nodes[cluster_id] = []  # Clears any stale older node telemetry for this cluster
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
    parser.add_argument("--output", default=DEFAULT_DEDUP_FILE, help="Path to the output deduplicated raw file")
    
    args = parser.parse_args()
    parse_telemetry(start_date=args.start, end_date=args.end, last_day_only=args.last_day, output_file=args.output)
