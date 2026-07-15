#!/usr/bin/env python3
import os

LOG_DIR = "/var/log/telemetry_report"

# Assicurati che la cartella esista
os.makedirs(LOG_DIR, exist_ok=True)

# Definiamo gli UUID fissi per i cluster di test
UUID_A = "aaaa24f5-4252-4883-b587-01110c52ef2f" # Production
UUID_B = "bbbb24f5-4252-4883-b587-01110c52ef2f" # Stage
UUID_C = "cccc24f5-4252-4883-b587-01110c52ef2f" # Edge (Nuovo il 14 Luglio)

# --- GIORNO 1: 12 Luglio 2026 ---
# Cluster A ha 3 master e 3 worker (totale 6 nodi)
# Cluster B ha 3 master e 1 worker (totale 4 nodi)
log_12 = f"""H,{UUID_A},6,4.20.27,4.19.30,2026-06-30 13:57:58 UTC,None,2026-07-12 10:00:00 UTC,amd64
N,{UUID_A},prod-master-01,control-plane master,40,true
N,{UUID_A},prod-master-02,control-plane master,40,true
N,{UUID_A},prod-master-03,control-plane master,40,true
N,{UUID_A},prod-worker-01,worker,50,true
N,{UUID_A},prod-worker-02,worker,50,true
N,{UUID_A},prod-worker-03,worker,50,true
R,UiwxPTQuMjAuMjcsMj00LjE5LjMw
T,token-prod-giorno-12
H,{UUID_B},4,4.20.27,4.19.30,2026-06-30 13:57:58 UTC,None,2026-07-12 10:05:00 UTC,amd64
N,{UUID_B},stage-master-01,control-plane master,40,true
N,{UUID_B},stage-master-02,control-plane master,40,true
N,{UUID_B},stage-master-03,control-plane master,40,true
N,{UUID_B},stage-worker-01,worker,50,true
R,UiwxPTQuMjAuMjcsMj
T,token-stage-giorno-12
"""

# --- GIORNO 2: 13 Luglio 2026 ---
# Cluster A: SCENARIO RIDIMENSIONAMENTO -> Un worker si rompe / viene rimosso (passa da 6 a 5 nodi totali)
# Cluster B: Rimane stabile con 4 nodi, ma aggiorna il timestamp
log_13 = f"""H,{UUID_A},5,4.20.27,4.19.30,2026-06-30 13:57:58 UTC,None,2026-07-13 10:00:00 UTC,amd64
N,{UUID_A},prod-master-01,control-plane master,40,true
N,{UUID_A},prod-master-02,control-plane master,40,true
N,{UUID_A},prod-master-03,control-plane master,40,true
N,{UUID_A},prod-worker-01,worker,50,true
N,{UUID_A},prod-worker-02,worker,50,true
R,UiwxPTQuMjAuMjcsMj00LjE5LjMw
T,token-prod-giorno-13
H,{UUID_B},4,4.20.27,4.19.30,2026-06-30 13:57:58 UTC,None,2026-07-13 10:05:00 UTC,amd64
N,{UUID_B},stage-master-01,control-plane master,40,true
N,{UUID_B},stage-master-02,control-plane master,40,true
N,{UUID_B},stage-master-03,control-plane master,40,true
N,{UUID_B},stage-worker-01,worker,50,true
R,UiwxPTQuMjAuMjcsMj
T,token-stage-giorno-13
"""

# --- GIORNO 3: 14 Luglio 2026 (Oggi) ---
# Cluster A: Torna a 6 nodi (nuovo worker aggiunto: prod-worker-04)
# Cluster B: Non invia dati (è spento / rimosso)
# Cluster C: Nuovo cluster Edge rilevato per la prima volta (3 nodi compact master/worker)
log_14 = f"""H,{UUID_A},6,4.20.27,4.19.30,2026-06-30 13:57:58 UTC,None,2026-07-14 13:58:00 UTC,amd64
N,{UUID_A},prod-master-01,control-plane master,40,true
N,{UUID_A},prod-master-02,control-plane master,40,true
N,{UUID_A},prod-master-03,control-plane master,40,true
N,{UUID_A},prod-worker-01,worker,50,true
N,{UUID_A},prod-worker-02,worker,50,true
N,{UUID_A},prod-worker-04,worker,50,true
R,UiwxPTQuMjAuMjcsMj00LjE5LjMw
T,token-prod-giorno-14
H,{UUID_C},3,4.20.27,4.19.30,2026-07-14 08:00:00 UTC,None,2026-07-14 13:58:50 UTC,amd64
N,{UUID_C},edge-compact-01,control-plane master worker,40,true
N,{UUID_C},edge-compact-02,control-plane master worker,40,true
N,{UUID_C},edge-compact-03,control-plane master worker,40,true
R,UiwxPTQuMjU=
T,token-edge-giorno-14
"""

# Scrittura dei file
files = {
    "telemetry_2026-07-12.log": log_12,
    "telemetry_2026-07-13.log": log_13,
    "telemetry_2026-07-14.log": log_14,
}

for filename, content in files.items():
    filepath = os.path.join(LOG_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[+] Generato file di test: {filepath}")
