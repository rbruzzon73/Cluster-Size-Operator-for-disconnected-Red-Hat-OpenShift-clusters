#!/usr/bin/env python3
import os

LOG_DIR = "/var/log/telemetry_report"
os.makedirs(LOG_DIR, exist_ok=True)

# UUID del vecchio cluster creato a Gennaio 2026
UUID_HISTORICAL = "999924f5-4252-4883-b587-01110c52ef2f"

# Simula i log inviati nei mesi passati dal "Cluster Storico"
logs_by_date = {
    # Gennaio 2026: Creazione del cluster con 3 nodi
    "2026-01-15": f"""H,{UUID_HISTORICAL},3,4.20.0,4.19.0,2026-01-15 09:00:00 UTC,None,2026-01-15 10:00:00 UTC,amd64
N,{UUID_HISTORICAL},hist-node-01,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-02,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-03,worker,50,true
R,UiwxPTQuMjAuMCwyPTQuMTkuMA==
T,token-hist-jan
""",

    # Marzo 2026 (4 mesi fa): Primo aggiornamento software (da 4.20.0 a 4.20.10)
    "2026-03-10": f"""H,{UUID_HISTORICAL},3,4.20.10,4.19.0,2026-01-15 09:00:00 UTC,None,2026-03-10 10:00:00 UTC,amd64
N,{UUID_HISTORICAL},hist-node-01,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-02,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-03,worker,50,true
R,UiwxPTQuMjAuMTAsMj00LjE5LjA=
T,token-hist-mar
""",

    # Maggio 2026 (2 mesi fa): Aggiunta di un nodo worker (passa a 4 nodi totali)
    "2026-05-20": f"""H,{UUID_HISTORICAL},4,4.20.10,4.19.0,2026-01-15 09:00:00 UTC,None,2026-05-20 10:00:00 UTC,amd64
N,{UUID_HISTORICAL},hist-node-01,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-02,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-03,worker,50,true
N,{UUID_HISTORICAL},hist-node-04,worker,50,true
R,UiwxPTQuMjAuMTAsMj00LjE5LjA=
T,token-hist-may
""",

    # Luglio 2026 (Oggi): Ultimo aggiornamento (Minor release upgrade a 4.20.27)
    "2026-07-14": f"""H,{UUID_HISTORICAL},4,4.20.27,4.19.30,2026-01-15 09:00:00 UTC,None,2026-07-14 15:30:00 UTC,amd64
N,{UUID_HISTORICAL},hist-node-01,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-02,control-plane master,40,true
N,{UUID_HISTORICAL},hist-node-03,worker,50,true
N,{UUID_HISTORICAL},hist-node-04,worker,50,true
R,UiwxPTQuMjAuMjcsMj00LjE5LjMw
T,token-hist-jul
"""
}

# Genera i singoli file di log
for date_str, content in logs_by_date.items():
    filename = f"telemetry_{date_str}.log"
    filepath = os.path.join(LOG_DIR, filename)
    
    # Se il file esiste già (come quello del 14 Luglio del test precedente), 
    # appendiamo questo blocco in coda invece di sovrascrivere tutto
    mode = "a" if os.path.exists(filepath) else "w"
    
    with open(filepath, mode, encoding="utf-8") as f:
        f.write(content)
        
    print(f"[+] Generato/Aggiornato log storico: {filepath} ({'In coda' if mode == 'a' else 'Nuovo'})")

