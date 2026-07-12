# The final audited CSV file can be passed out of the isolated zone via a unidirectional hardware data diode or a secure media transfer procedure, guaranteeing strict one-way data movement without allowing any inbound network access.

- The Cluster Size Operator for disconnecteed Red Hat OpenShift Cluster is a highly specialized, lightweight day-2 utility designed for automated infrastructure auditing and subscription compliance management. 

- Its primary objective is to solve a critical operational challenge: how to securely gather, verify, and export precise cluster-sizing telemetry from strictly disconnected (air-gapped) OpenShift environments without compromising network security or leaking internal topology metadata.

## Financial Optimization and Const Control

- Eliminating Over-Provisioning Waste

   - In massive multi-cluster or OpenStack environments, it is easy to lose track of exactly how many virtual cores (vCPUs) or physical hypervisor hyper-threads are active. 
   
   - Without clear monitoring, organizations often buy safety-buffer subscriptions they don’t actually need. 
   
   - Clear reporting maps your exact footprint, allowing you to downsize unneeded licenses and optimize your software spend.

- Mitigating True-Up Financial Shock

   - Red Hat subscriptions operate on an annual consumption model. 
   
   - If an internal development team scales an OpenShift cluster rapidly to handle a project and forgets to scale it back down, your usage spikes. 
   
   - Without continuous monitoring, you will only discover this violation during your annual renewal audit, resulting in an unexpected, unbudgeted "true-up" invoice from Red Hat. 
   
   - Continuous visibility ensures you capture usage trends long before the renewal deadline.


## Clustersize Operator Architecture

- The operator functions as a Namespace-Scoped Controller with Cluster-Wide Read Visibility. It runs with a strict "Zero Idle Overhead" footprint, meaning it consumes almost no compute resources until explicitly activated by an administrator.

   ~~~
   [ Admin Creates Secret ] 
             │
             ▼
   ┌────────────────────────────────────────────────────────┐
   │               CLUSTERSIZE OPERATOR                     │
   │  - Watches for 'clustersize-secrets'                   │
   │  - Dynamically injects ClusterRoles & Bindings         │
   │  - Provisions local storage PVC & ConfigMap            │
   │  - Spawns the Metric Collector Pod                     │
   └────────────────────────────────────────────────────────┘
             │
             ▼
   ┌────────────────────────────────────────────────────────┐
   │                 METRIC COLLECTOR POD                   │
   │  - Alphabetically sorts and masks node names           │
   │  - Collects: vCPU, RAM, Hypervisor (BM vs VM)          │
   │  - Generates HMAC-SHA256 data-integrity signatures     │
   │  - Compresses whole snapshot via Gzip into 1 UDP packet│
   └────────────────────────────────────────────────────────┘
   ~~~

- The operator uses a standard Kubernetes Secret (clustersize-secrets) and a Custom Resource definition to control execution. 

- While it runs isolated inside its own namespace, it holds read-only cluster-level access to query raw node objects and cluster-version manifests.

- The operator extracts only the hardware data and version metrics required for core-based subscription compliance:

   - Unique OpenShift Cluster ID: (clusterID)
   - Cluster Version: Current platform release version vectors.
   - Hostnode Operational Role: Mapped via index values (e.g.: control-plane, infra, master, ODF, ingress, worker, etc. etc.).
   - Allocated vCPU Count: Total virtual cores per node.
   - Deployment Environment State: (true for Bare-Metal hardware, false for virtualized OpenStack/KVM instances).

## Data & Network Volume Evaluation

- When a telemetry check triggers (either via a manual configuration change or when the interval heartbeat expires), the internal fragmentation engine packages node records together, compresses them via Gzip, and streams them over UDP.

### Transmission Serialization & Sequence Numbers

   - To allow the central receiver to uniquely identify transmission windows, handle multi-packet reassembly, and prevent out-of-order log writes, the collector implements an independent, sequential message tracking mechanism:

      - Sequence Counter (.seq_counter):
     
         - Stored inside the pod's local persistent volume, a monotonically increasing 12-digit sequence tracking identifier (Msg ID) is generated for each execution loop (e.g., 000000000458).

      - Frame Multiplexing Header: 
      
         - The fragmentation engine prefixes each raw binary network chunk with a text envelope containing the sequence ID, the current frame index, and the total expected frames for that snapshot window.


      ~~~
      [Sequence_Number],[Current_Frame],[Total_Frames]|
      Example: 000000000458,000001,000002| followed by the compressed payload block.
      ~~~

### Telemetry String Structure

- The raw text layout nested inside the network frame packet envelope follows this structured layout prior to compression:

   ~~~
   H,[ClusterID],[NodeCount],[VersionIndex],[InitVersionIndex],[InstallDate],None,[CurrentEpoch],[Arch]
   N,[ClusterID],[SequentialIndex],[RoleIndex],[vCPU],[IsBaremetal]
   R,[Base64_Encoded_Lookup_Table_Mapping_Indices_To_Cleartext_Roles]
   T,[HMAC-SHA256_Data_Integrity_Signature]
   ~~~
   
## Dynamic Slicing and Network Metrics

- To guarantee network compatibility, the collector uses an 80-node fragmentation threshold. 
If a cluster contains more than 80 nodes, the payload is sliced into multiple independent UDP frame packets to keep each packet safely below standard network limits.
The baseline topology is structured as:

   - 3 nodes: control-plane infra master (Mapped to Role Index 3)
   - 3 nodes: ODF ingress worker (Mapped to Role Index 4)
   - Remaining scaling nodes ($X$): ruolo1 ruolo2 worker (Mapped to Role Index 5)

- Here is the recorded network footprint across different cluster scales:

   | OCP Cluster size | Total UDP Size (incl. Headers) | Number of Frame Packets sent |
   | :--- | :---: | :---: | 
   | Cluster with 16 nodes | 398 Bytes | 1 Packet (Frame 1/1) |
   | Cluster with 32 nodes | 442 Bytes | 1 Packet (Frame 1/1) |
   | Cluster with 64 nodes | 522 Bytes | 1 Packet (Frame 1/1) |
   | Cluster with 80 nodes | 562 Bytes | 1 Packet (Frame 1/1) |
   | Cluster with 96 nodes | 969 Bytes (562 + 397 Bytes) | 2 Packets (Frame 1/2, 2/2) |
   | Cluster with 128 nodes | 1047 Bytes (565 + 482 Bytes) | 2 Packets (Frame 1/2, 2/2) |


## Network and Security Impact Analysis:

- Network Footprint: 
   - The standard Ethernet Maximum Transmission Unit (MTU) limit is 1,500 bytes. 
   - By combining Gzip compression with an 80-node packet slicing threshold, no individual UDP packet ever exceeds 1,400 bytes. 
   - This completely eliminates IP fragmentation risks on the wire, preventing data drops on standard networks. 
   - A full 150-node snapshot burst takes less than a millisecond to transmit and is virtually invisible against normal background datacenter traffic.

- Confidentiality (High): 
   - Real node hostnames are never transmitted; they are masked using sequential index tags (node-001, node-002). 
   - The underlying structural role mappings are obscured inside a Base64 string payload row. 
   - Even if a network tap captures the packets, an attacker only sees an anonymous binary stream with zero internal infrastructure nomenclature.

- Integrity Verification: The receiver processes incoming frames in memory, decompresses the payload, and validates the cryptographic HMAC-SHA256 signature appended to the end of the text stream. If a single bit is modified in transit, the Gzip checksum fails or the HMAC verification breaks, causing the receiver to drop the corrupted payload immediately.

Availability (Self-Healing): 
   - Because UDP is a connectionless protocol, it does not guarantee packet delivery. 
   - If a network switch drops a frame packet during heavy network congestion, the central receiver discards the incomplete payload. 
   - However, because the cluster operator continuously sends fresh telemetry updates at regular intervals, any missed snapshots self-heal automatically during the next interval cycle.

## Managing Multiple Disconnected Clusters
When operating multiple disconnected clusters across an enterprise, managing distinct streams of UDP telemetry requires a structured central ingestion architecture.

- Centralize Aggregation (The Secure Internal Ingestion Hub):

   - Deploy a single central Linux Bastion or dedicated Virtual Machine within your secure disconnected zone. This host runs a multi-threaded UDP receiver script that listens for incoming payloads from all your clusters.

      ~~~
      ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
      │    CLUSTER A    │      │    CLUSTER B    │      │    CLUSTER C    │
      └────────┬────────┘      └────────┬────────┘      └────────┬────────┘
               │                        │                        │
               └───────────────┐        │        ┌───────────────┘
                               ▼        ▼        ▼
                         ┌──────────────────────────────┐
                         │     CENTRAL BASTION HUB      │
                         │  - Multi-threaded UDP server │
                         │  - Separates files by UUID   │
                         └──────────────┬───────────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │  DATA DIODE / SECURE MEDIA   │
                         │  - One-way compliance CSV    │
                         └──────────────────────────────┘
      ~~~

- Centralized Aggregation & Reassembly:
  
   - Deploy a central Linux Bastion host or virtual machine within your secure isolated network zone.
  
   - This host runs a multi-threaded Python UDP receiver daemon that listens on port 555.
   
   - The daemon evaluates incoming frames against their Sequence Number in memory using a buffer_lock mutex session map.
   
   - When all expected frames for a specific Msg ID arrive, it pops the session, decompresses the unified byte-stream, and appends the cleartext metrics into dedicated logs:

      ~~~
      /var/log/telemetry_report/
      ├── telemetry_2026-07-12.log (Consolidated rolling daily logs)
      ~~~
      
- Automated Consolidation: 

   - A simple cron job on the aggregation hub can parse the daily rolling file, extract the latest valid timestamp entry for each unique cluster ID, and compile a single, unified CSV master compliance file:

      ~~~
      Cluster_ID,Masked_Node,Role,CPU,IsBaremetal
      d08824f5-4252...,node-001,control-plane infra master,40,true
      d08824f5-4252...,node-005,ODF ingress worker,120,true
      d08824f5-4252...,node-007,ruolo1 ruolo2 worker,64,true
      ~~~
      
## Data Diode or Secure Media Transfer: 
The final audited CSV file can be passed out of the isolated zone via a unidirectional hardware data diode or a secure media transfer procedure, guaranteeing strict one-way data movement without allowing any inbound network access.
