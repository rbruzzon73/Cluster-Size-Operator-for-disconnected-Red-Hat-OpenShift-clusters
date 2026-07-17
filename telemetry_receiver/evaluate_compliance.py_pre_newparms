#!/usr/bin/env python3
import os
import argparse
import csv
import math
from datetime import datetime, date

DEFAULT_INPUT_FILE = "/var/log/telemetry_report/telemetry_deduplicated.csv"
DEFAULT_MASTER_FILE = "/var/log/telemetry_report/master_compliance.csv"

CSV_HEADER = [
    "CLUSTER_ID", "PLATFORM", "CLUSTER_VERSION", "CLUSTER_INITIAL_VERSION", 
    "CLUSTER_NODE_COUNT", "CLUSTER_INSTALLED_AT", "SUPPORT", "HOSTNAME", 
    "NODE_ROLES", "NODE_ARCHITECTURE", "LAST_UPDATE_RECEIVED", 
    "TOTAL_PHYSICAL_CPU_CORES", "TOTAL_VIRTUAL_VCPUS", "TOTAL_MEMORY", 
    "TOTAL_REQUIRED_SUB_FOR_PHYSICAL_CPU_CORES", "TOTAL_REQUIRED_SUB_FOR_VIRTUAL_VCPUS", 
    "EUS_TERM1_REQUIRED_SUBS_PHYSICAL_CPU_CORES", "EUS_TERM2_REQUIRED_SUBS_PHYSICAL_CPU_CORES", 
    "EUS_TERM3_REQUIRED_SUBS_PHYSICAL_CPU_CORES", "EUS_TERM1_REQUIRED_SUBS_VIRTUAL_VCPUS", 
    "EUS_TERM2_REQUIRED_SUBS_VIRTUAL_VCPUS", "EUS_TERM3_REQUIRED_SUBS_VIRTUAL_VCPUS", 
    "IS_GRAND_TOTAL"
]

def load_subscriptions(filepath):
    """Loads current inventory counts from the subscriptions file."""
    subs = {
        "premium_s390x_subscriptions": 0, "standard_s390x_subscriptions": 0,
        "premium_ocp_subscriptions": 0, "standard_ocp_subscriptions": 0,
        "standard_ocp_term_1": 0, "standard_ocp_term_2": 0, "standard_ocp_term_3": 0,
        "premium_ocp_term_2": 0, "premium_ocp_term_3": 0
    }
    if not filepath or not os.path.exists(filepath):
        print(f"[WARNING] Subscription file {filepath} not found. Setting counts to 0.")
        return subs
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in subs:
                try:
                    subs[k] = int(v.strip())
                except ValueError:
                    pass
    return subs

def load_lifecycle(filepath):
    """Maps major.minor OCP versions to their EUS phases from lifecycle CSV."""
    lifecycle = {}
    if not filepath or not os.path.exists(filepath):
        print(f"[WARNING] Lifecycle file {filepath} not found. Disabling EUS calculations.")
        return lifecycle
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ver = row.get("major_minor", "").strip()
            if ver:
                lifecycle[ver] = {
                    "t1_start": row.get("t1_start", "").strip(),
                    "t1_end": row.get("t1_end", "").strip(),
                    "t2_start": row.get("t2_start", "").strip(),
                    "t2_end": row.get("t2_end", "").strip(),
                    "t3_start": row.get("t3_start", "").strip(),
                    "t3_end": row.get("t3_end", "").strip(),
                }
    return lifecycle

def evaluate_term(lifecycle_ref, major_minor, term_num, range_start, range_end):
    """Checks if the evaluation range falls within an active EUS term."""
    if major_minor not in lifecycle_ref:
        return False
    ref = lifecycle_ref[major_minor]
    start_str = ref.get(f"t{term_num}_start")
    end_str = ref.get(f"t{term_num}_end")
    if not start_str or not end_str:
        return False
    try:
        t_start = datetime.strptime(start_str, "%Y-%m-%d").date()
        t_end = datetime.strptime(end_str, "%Y-%m-%d").date()
        return t_start <= range_end and t_end >= range_start
    except ValueError:
        return False

def clean_val(val):
    """Guarantees standard output format instead of empty or none entries."""
    if not val or val.strip() == "" or val.strip().lower() == "none":
        return "NotAvailable"
    return val.strip()

def run_evaluation(input_file, output_file, subs_file, lifecycle_file, start_date, end_date):
    """Computes subscription balances and EUS compliance, and builds output."""
    subs = load_subscriptions(subs_file)
    lifecycle = load_lifecycle(lifecycle_file)

    r_start = start_date if start_date else date.today()
    r_end = end_date if end_date else date.today()

    if not os.path.exists(input_file):
        print(f"[ERROR] Deduplicated input file {input_file} missing. Run deduplicate script first.")
        return

    latest_headers = {}
    latest_nodes = {}

    print(f"Reading deduplicated intermediate file: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            record_type = parts[0]

            if record_type == 'H' and len(parts) >= 9:
                cluster_id = parts[1]
                platform = parts[6].strip().lower()
                
                # Filter out hosted platforms
                if platform in ['aws', 'aro', 'azure']:
                    continue

                latest_headers[cluster_id] = {
                    "cluster_id": cluster_id,
                    "platform": clean_val(parts[6]),
                    "cluster_version": clean_val(parts[3]),
                    "cluster_initial_version": clean_val(parts[4]),
                    "cluster_node_count": int(parts[2]) if parts[2].isdigit() else 0,
                    "cluster_installed_at": clean_val(parts[5]),
                    "support": "NO SUPPORT DEFINED",
                    "last_update_received": clean_val(parts[7])
                }
                latest_nodes[cluster_id] = []

            elif record_type == 'N' and len(parts) >= 6:
                cluster_id = parts[1]
                if cluster_id not in latest_headers:
                    continue
                
                latest_nodes[cluster_id].append({
                    "hostname": clean_val(parts[2]),
                    "roles": clean_val(parts[3]),
                    "architecture": clean_val(parts[5]).upper(),
                    "cpu_raw": int(parts[4]) if parts[4].isdigit() else 0,
                    "memory": "NotAvailable"
                })

    evaluated_rows = []

    for cluster_id in sorted(latest_headers.keys()):
        h_data = latest_headers[cluster_id]
        node_count = h_data["cluster_node_count"]
        nodes = latest_nodes.get(cluster_id, [])

        ver_parts = h_data["cluster_version"].split('.')
        major_minor = f"{ver_parts[0]}.{ver_parts[1]}" if len(ver_parts) >= 2 else "NotAvailable"

        for node in nodes:
            roles = node["roles"].lower()
            if node_count > 3:
                # Exclude infrastructural/management roles if cluster has more than 3 nodes
                if "master" in roles or "control-plane" in roles or "infra" in roles:
                    continue

            arch_group = "s390x" if "S390X" in node["architecture"] else "AMD64"
            cpu_raw = node["cpu_raw"]
            is_baremetal = h_data["platform"].lower() == "baremetal"

            # Compute virtual vs physical core counts
            if is_baremetal:
                total_cores = cpu_raw
                total_vcpus = 0
            else:
                total_cores = 0
                total_vcpus = cpu_raw

            if arch_group == "s390x":
                total_vcpus = 0
                total_cores = cpu_raw

            # Compute subscription requirements
            if arch_group == "s390x":
                sub_physical = cpu_raw
                sub_virtual = 0
            elif is_baremetal:
                sub_physical = math.ceil(total_cores / 2)
                sub_virtual = 0
            else:
                sub_physical = 0
                sub_virtual = math.ceil(total_vcpus / 4)

            # Evaluate active EUS phase targets
            t1_active = evaluate_term(lifecycle, major_minor, 1, r_start, r_end)
            t2_active = evaluate_term(lifecycle, major_minor, 2, r_start, r_end)
            t3_active = evaluate_term(lifecycle, major_minor, 3, r_start, r_end)

            # Map active EUS terms to subscription values
            eus_t1_phys = sub_physical if t1_active else 0
            eus_t2_phys = sub_physical if t2_active else 0
            eus_t3_phys = sub_physical if t3_active else 0

            eus_t1_virt = sub_virtual if t1_active else 0
            eus_t2_virt = sub_virtual if t2_active else 0
            eus_t3_virt = sub_virtual if t3_active else 0

            evaluated_rows.append({
                "cluster_id": h_data["cluster_id"],
                "platform": h_data["platform"],
                "cluster_version": h_data["cluster_version"],
                "cluster_initial_version": h_data["cluster_initial_version"],
                "cluster_node_count": node_count,
                "cluster_installed_at": h_data["cluster_installed_at"],
                "support": h_data["support"],
                "hostname": node["hostname"],
                "node_roles": node["roles"],
                "node_architecture": arch_group,
                "last_update_received": h_data["last_update_received"],
                "total_physical_cpu_cores": total_cores,
                "total_virtual_vcpus": total_vcpus,
                "total_memory": node["memory"],
                "sub_phys": sub_physical,
                "sub_virt": sub_virtual,
                "eus_t1_phys": eus_t1_phys,
                "eus_t2_phys": eus_t2_phys,
                "eus_t3_phys": eus_t3_phys,
                "eus_t1_virt": eus_t1_virt,
                "eus_t2_virt": eus_t2_virt,
                "eus_t3_virt": eus_t3_virt,
                "is_grand_total": 0
            })

    print(f"Writing final compliance matrix report to: {output_file}")
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(CSV_HEADER)

        # Write out individual node records
        for row in evaluated_rows:
            writer.writerow([
                row["cluster_id"], row["platform"], row["cluster_version"], row["cluster_initial_version"],
                row["cluster_node_count"], row["cluster_installed_at"], row["support"], row["hostname"],
                row["node_roles"], row["node_architecture"], row["last_update_received"],
                row["total_physical_cpu_cores"], row["total_virtual_vcpus"], row["total_memory"],
                row["sub_phys"], row["sub_virt"],
                row["eus_t1_phys"], row["eus_t2_phys"], row["eus_t3_phys"],
                row["eus_t1_virt"], row["eus_t2_virt"], row["eus_t3_virt"], 0
            ])

        # Define architectural support dimensions
        aggr_groups = [("AMD64", "STANDARD"), ("AMD64", "PREMIUM"), ("s390x", "STANDARD"), ("s390x", "PREMIUM")]

        # SECTION 1: GRAND TOTAL LOAD
        grand_totals = {}
        for arch, supp in aggr_groups:
            filtered = [r for r in evaluated_rows if r["node_architecture"] == arch]
            tot_cores = sum(r["total_physical_cpu_cores"] for r in filtered)
            tot_vcpus = sum(r["total_virtual_vcpus"] for r in filtered)
            tot_phys_sub = sum(r["sub_phys"] for r in filtered)
            tot_virt_sub = sum(r["sub_virt"] for r in filtered)
            
            t1_phys = sum(r["eus_t1_phys"] for r in filtered)
            t2_phys = sum(r["eus_t2_phys"] for r in filtered)
            t3_phys = sum(r["eus_t3_phys"] for r in filtered)
            
            t1_virt = sum(r["eus_t1_virt"] for r in filtered)
            t2_virt = sum(r["eus_t2_virt"] for r in filtered)
            t3_virt = sum(r["eus_t3_virt"] for r in filtered)

            grand_totals[(arch, supp)] = {
                "cores": tot_cores, "vcpus": tot_vcpus, "phys_sub": tot_phys_sub, "virt_sub": tot_virt_sub,
                "t1_p": t1_phys, "t2_p": t2_phys, "t3_p": t3_phys,
                "t1_v": t1_virt, "t2_v": t2_virt, "t3_v": t3_virt
            }

            writer.writerow([
                f"{arch} GRAND TOTAL LOAD - {supp}", None, None, None, None, None, supp, None, None, arch, None,
                tot_cores, tot_vcpus, 0, tot_phys_sub, tot_virt_sub,
                t1_phys, t2_phys, t3_phys, t1_virt, t2_virt, t3_virt, 1
            ])

        # SECTION 2: SUBSCRIPTION AVAILABLE
        avail_subs = {}
        for arch, supp in aggr_groups:
            if arch == "s390x":
                avail = subs["premium_s390x_subscriptions"] if supp == "PREMIUM" else subs["standard_s390x_subscriptions"]
                t1, t2, t3 = 0, 0, 0
            else:
                avail = subs["premium_ocp_subscriptions"] if supp == "PREMIUM" else subs["standard_ocp_subscriptions"]
                t1 = subs["standard_ocp_term_1"] if supp == "STANDARD" else 0
                t2 = subs["premium_ocp_term_2"] if supp == "PREMIUM" else subs["standard_ocp_term_2"]
                t3 = subs["premium_ocp_term_3"] if supp == "PREMIUM" else subs["standard_ocp_term_3"]

            avail_subs[(arch, supp)] = {"avail": avail, "t1": t1, "t2": t2, "t3": t3}

            writer.writerow([
                f"{arch} SUBSCRIPTION AVAILABLE - {supp}", None, None, None, None, None, supp, None, None, arch, None,
                None, None, None, avail, 0, t1, t2, t3, 0, 0, 0, 2
            ])

        # SECTION 3: CALCULATED GAP
        for arch, supp in aggr_groups:
            g_tot = grand_totals[(arch, supp)]
            av = avail_subs[(arch, supp)]

            gap_phys = (g_tot["phys_sub"] + g_tot["virt_sub"]) - av["avail"]
            gap_t1 = (g_tot["t1_p"] + g_tot["t1_v"]) - av["t1"]
            gap_t2 = (g_tot["t2_p"] + g_tot["t2_v"]) - av["t2"]
            gap_t3 = (g_tot["t3_p"] + g_tot["t3_v"]) - av["t3"]

            writer.writerow([
                f"GAP {arch} SUBSCRIPTIONS - {supp}", None, None, None, None, None, supp, None, None, arch, None,
                None, None, None, gap_phys, 0, gap_t1, gap_t2, gap_t3, 0, 0, 0, 3
            ])

    print("Compliance metrics and license gaps computed successfully!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate cluster capacity license compliance and resource gaps.")
    parser.add_argument("--input", default=DEFAULT_INPUT_FILE, help="Path to the deduplicated raw telemetry file")
    parser.add_argument("--output", default=DEFAULT_MASTER_FILE, help="Path to write the final compliance CSV report")
    parser.add_argument("--subscriptions", default="subscriptions.txt", help="Path to customer subscription file")
    parser.add_argument("--lifecycle", default="ocp_lifecycle.csv", help="Path to OpenShift lifecycle matrix mapping")
    parser.add_argument("--start", help="Start Date (YYYY-MM-DD) for active EUS calculations", type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
    parser.add_argument("--end", help="End Date (YYYY-MM-DD) for active EUS calculations", type=lambda s: datetime.strptime(s, '%Y-%m-%d').date())
    
    args = parser.parse_args()
    run_evaluation(
        input_file=args.input, output_file=args.output,
        subs_file=args.subscriptions, lifecycle_file=args.lifecycle,
        start_date=args.start, end_date=args.end
    )
