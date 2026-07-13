#!/usr/bin/env python3
import socket
import gzip
import io
import uuid
import random
import struct
import time
import base64
import hashlib

# --- Target Configuration ---
TARGET_IP = "192.168.100.254"
TARGET_PORT = 555

def generate_random_ip():
    """Generates a random source IP to simulate distributed cluster sources."""
    return f"{random.randint(10, 220)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"

def build_ip_udp_header(src_ip, dst_ip, dst_port, payload_len):
    """Manually constructs raw IP and UDP headers to achieve source IP spoofing."""
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

def build_cluster_payload(cluster_id, total_nodes):
    """Assembles a payload matching the structure and full hashing (H+N+R) of production telemetry."""
    now_epoch = int(time.time())
    
    lookup_str = "1=4.20.27,2=4.19.30,3=control-plane#master,4=worker#infra-odf,5=worker#application01,6=worker#application02,7=worker#application03"
    b64_lookup = base64.b64encode(lookup_str.encode('utf-8')).decode('utf-8')
    
    # Initialize lines list with the H Row to include it in the integrity check block
    payload_lines = [
        f"H,{cluster_id},{total_nodes},1,2,{now_epoch - 1000000},0,{now_epoch},amd64"
    ]
    
    # 3 Controllers
    for i in range(1, 4):
        payload_lines.append(f"N,{cluster_id},{i:03d},3,40,true")
    # 6 Infra nodes
    for i in range(4, 10):
        payload_lines.append(f"N,{cluster_id},{i:03d},4,40,true")
        
    # Remaining application workers distributed randomly
    worker_roles = [5, 6, 7]
    for i in range(10, total_nodes + 1):
        role_idx = random.choice(worker_roles)
        payload_lines.append(f"N,{cluster_id},{i:03d},{role_idx},50,true")
        
    # Append the R row dictionary line
    payload_lines.append(f"R,{b64_lookup}")
    
    # Calculate SHA-256 signature across H, N, and R rows combined
    hash_input = "\n".join(payload_lines) + "\n"
    sha256_hash = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
    
    # Assemble the full raw text package structure with the trailing T row
    full_payload_text = hash_input + f"T,{sha256_hash}\n"
    
    # Compress full payload using Gzip
    out_io = io.BytesIO()
    with gzip.GzipFile(fileobj=out_io, mode='wb') as f:
        f.write(full_payload_text.encode('utf-8'))
    return out_io.getvalue()

def send_segmented_payload(raw_socket, src_ip, gzip_data):
    """Chunks the payload into transmission segments and dispatches them via raw socket operations."""
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
        print("[✗] Fatal: This script requires root permissions to spoof source IPs. Please re-run using 'sudo'.")
        return

    # Establish cluster node counts allocations
    cluster_allocations = ([40] * 40) + ([100] * 60) + ([150] * 200)
    random.shuffle(cluster_allocations) 
    
    print(f"[*] Initializing telemetry simulator targeting -> {TARGET_IP}:{TARGET_PORT}")
    print(f"[*] Processing transmissions for {len(cluster_allocations)} synthetic OpenShift clusters...")
    
    for idx, node_count in enumerate(cluster_allocations, 1):
        cluster_id = str(uuid.uuid4())
        src_ip = generate_random_ip()
        
        gzip_payload = build_cluster_payload(cluster_id, node_count)
        send_segmented_payload(s, src_ip, gzip_payload)
        
        if idx % 20 == 0 or idx == len(cluster_allocations):
            print(f"[✓] Transmitted {idx}/300 clusters (Last sent: ID={cluster_id}... Nodes={node_count} via IP={src_ip})")
            
        time.sleep(0.02)

    s.close()
    print("[*] Completed all test cluster generation sweeps.")

if __name__ == "__main__":
    main()
