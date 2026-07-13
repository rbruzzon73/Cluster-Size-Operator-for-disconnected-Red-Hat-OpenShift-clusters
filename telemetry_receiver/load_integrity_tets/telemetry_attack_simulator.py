#!/usr/bin/env python3
import socket
import gzip
import io
import os
import uuid
import random
import struct
import time
import base64
import hmac
import hashlib
import subprocess

# --- Target Configuration ---
TARGET_IP = "192.168.100.254"
TARGET_PORT = 555

# --- Security Configuration (Aligned with production receiver paths) ---
SALT_FILE_PATH = "/etc/telemetry_salt.enc"
KEY_FILE_PATH = "/etc/.telemetry_key"

def load_verification_salt(salt_file, key_file):
    """Decrypts the validation salt in-memory to sign simulated payloads."""
    if not os.path.exists(salt_file) or not os.path.exists(key_file):
        print("[!] Warning: Decryption keys not found. Falling back to default static test salt.")
        return b"MySecretSaltValue"
    
    cmd = [
        "openssl", "enc", "-d", "-aes-256-cbc", 
        "-pbkdf2", "-iter", "100000", 
        "-in", salt_file, 
        "-pass", f"file:{key_file}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"[!] Warning: OpenSSL decryption failed ({e}). Falling back to default static test salt.")
        return b"MySecretSaltValue"

# Securely load the salt for HMAC signing
HMAC_SALT = load_verification_salt(SALT_FILE_PATH, KEY_FILE_PATH)

def generate_random_ip():
    return f"{random.randint(10, 220)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"

def build_ip_udp_header(src_ip, dst_ip, dst_port, payload_len):
    ip_ihl = 5
    ip_ver = 4
    ip_tos = 0
    ip_tot_len = 20 + 8 + payload_len
    ip_id = random.randint(1000, 50000)
    ip_frag_off = 0
    ip_ttl = 64
    ip_proto = socket.IPPROTO_UDP
    ip_check = 0  
    ip_saddr = socket.inet_aton(src_ip)
    ip_daddr = socket.inet_aton(dst_ip)
    
    ip_ihl_ver = (ip_ver << 4) + ip_ihl
    ip_header = struct.pack('!BBHHHBBH4s4s', ip_ihl_ver, ip_tos, ip_tot_len, ip_id, ip_frag_off, ip_ttl, ip_proto, ip_check, ip_saddr, ip_daddr)
    
    udp_src_port = random.randint(30000, 60000)
    udp_len = 8 + payload_len
    udp_check = 0  
    
    udp_header = struct.pack('!HHHH', udp_src_port, dst_port, udp_len, udp_check)
    return ip_header + udp_header

def build_corrupted_payload(cluster_id, scenario_idx, salt_bytes):
    """Generates a base payload, signs H + N + R using HMAC-SHA256, then mutates the data to break validation."""
    now_epoch = int(time.time())
    node_count = 40  
    
    lookup_str = "1=4.20.27,2=4.19.30,3=control-plane#master,4=worker#infra-odf,5=worker#application01"
    b64_lookup = base64.b64encode(lookup_str.encode('utf-8')).decode('utf-8')
    
    h_row = f"H,{cluster_id},{node_count},1,2,{now_epoch - 100000},0,{now_epoch},amd64"
    
    # 1. Build out structural lines
    payload_lines = [h_row]
    for i in range(1, 4):
        payload_lines.append(f"N,{cluster_id},{i:03d},3,40,true")
    for i in range(4, 10):
        payload_lines.append(f"N,{cluster_id},{i:03d},4,40,true")
    for i in range(10, node_count + 1):
        payload_lines.append(f"N,{cluster_id},{i:03d},5,50,true")
    payload_lines.append(f"R,{b64_lookup}")
    
    # 2. Compute TRUE HMAC-SHA256 hash across pristine H, N, and R rows combined
    hash_input = "\n".join(payload_lines) + "\n"
    hmac_obj = hmac.new(salt_bytes, hash_input.encode('utf-8'), hashlib.sha256)
    hmac_signature = hmac_obj.hexdigest()
    
    # 3. Apply targeted mutations based on scenario indexes
    scenario_desc = ""
    if scenario_idx == 1:
        scenario_desc = "REMOVING A MIDDLE N ROW"
        payload_lines.pop(15)  
        
    elif scenario_idx == 2:
        scenario_desc = "INJECTING AN UNTRACKED N ROW"
        payload_lines.insert(5, f"N,{cluster_id},999,5,50,true")
        
    elif scenario_idx == 3:
        scenario_desc = "REDUCING CPU COUNT VALUE IN AN N ROW"
        payload_lines[1] = payload_lines[1].replace(",40,", ",2,")
        
    elif scenario_idx == 4:
        scenario_desc = "CHANGING READY STATUS TO FALSE"
        payload_lines[11] = payload_lines[11].replace(",true", ",false")
        
    elif scenario_idx == 5:
        scenario_desc = "TAMPERING WITH ROLE INDEX ID"
        payload_lines[2] = payload_lines[2].replace(",3,40,", ",5,40,")
        
    elif scenario_idx == 6:
        scenario_desc = "CORRUPTING THE DICTIONARY LOOKUP BASE64 STRING"
        payload_lines[-1] = payload_lines[-1][:-4] + "AAAA"
        
    elif scenario_idx == 7:
        scenario_desc = "REMOVING THE R LINE COMPLETELY"
        payload_lines.pop(-1)
        
    elif scenario_idx == 8:
        scenario_desc = "MUTATING THE CLUSTER ID WITHIN AN N ROW"
        payload_lines[8] = payload_lines[8].replace(cluster_id, str(uuid.uuid4()))
        
    elif scenario_idx == 9:
        scenario_desc = "ZEROING OUT DATA VALUES ON NODE NAMES"
        payload_lines[12] = f"N,{cluster_id},,5,50,true"
        
    elif scenario_idx == 10:
        scenario_desc = "TOTAL RANDOM PAYLOAD MUTATION (TRUNCATION)"
        payload_lines = payload_lines[:5]  
        
    elif scenario_idx == 11:
        scenario_desc = "CORRUPTING THE H ROW METADATA FIELDS"
        payload_lines[0] = payload_lines[0].replace(f",{node_count},", ",CORRUPTED_COUNT,")

    corrupted_payload_text = "\n".join(payload_lines) + "\n" + f"T,{hmac_signature}\n"
    
    out_io = io.BytesIO()
    with gzip.GzipFile(fileobj=out_io, mode='wb') as f:
        f.write(corrupted_payload_text.encode('utf-8'))
        
    return out_io.getvalue(), scenario_desc

def send_segmented_payload(raw_socket, src_ip, gzip_data):
    msg_id = str(random.randint(100000, 999999))
    chunk_size = 8192
    total_frames = (len(gzip_data) + chunk_size - 1) // chunk_size
    
    for frame_idx in range(1, total_frames + 1):
        start = (frame_idx - 1) * chunk_size
        end = min(start + chunk_size, len(gzip_data))
        bin_chunk = gzip_data[start:end]
        
        protocol_header = f"{msg_id},{frame_idx},{total_frames}|".encode('utf-8')
        udp_payload = protocol_header + bin_chunk
        
        packet = build_ip_udp_header(src_ip, TARGET_IP, TARGET_PORT, len(udp_payload)) + udp_payload
        raw_socket.sendto(packet, (TARGET_IP, TARGET_PORT))

def main():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    except PermissionError:
        print("[✗] Fatal: Script requires root permissions to spoof source IPs. Re-run with 'sudo'.")
        return

    print(f"[*] Starting target validation sweep across 11 corrupted cluster payloads...")
    print(f"[*] Decrypted active signing salt from security subsystem.")
    print(f"[*] Shipping packets directly to -> {TARGET_IP}:{TARGET_PORT}\n" + "-"*75)

    # Loop through all 11 scenarios
    for scenario_idx in range(1, 12):
        cluster_id = str(uuid.uuid4())
        src_ip = generate_random_ip()
        
        gzip_payload, description = build_corrupted_payload(cluster_id, scenario_idx, HMAC_SALT)
        
        print(f"[🔥] Sending Cluster {scenario_idx}/11 | ID: {cluster_id} | Attack Type: {description}")
        send_segmented_payload(s, src_ip, gzip_payload)
        
        time.sleep(0.5)  

    s.close()
    print("\n[*] All 11 error simulation test sweeps completed.")

if __name__ == "__main__":
    main()
