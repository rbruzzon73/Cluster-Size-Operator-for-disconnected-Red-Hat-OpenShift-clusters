# Custer Size Operator for disconnected Red Hat OpenShift Clusters.

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
   │  - Dynamically injects Roles ClusterRoles & Bindings   │
   │  - Provisions local storage PVC & ConfigMap            │
   │  - Spawns the Metric Collector Pod                     │
   └────────────────────────────────────────────────────────┘
             │
             ▼
   ┌────────────────────────────────────────────────────────┐
   │                 METRIC COLLECTOR POD                   │
   │  - Alphabetically sorts and masks node names           │
   │  - Collects: vCPU, Hypervisor (BM vs VM)               │
   │  - Generates HMAC-SHA256 data-integrity signatures     │
   │  - Compresses whole snapshot via Gzip into 1 UDP packet│
   └────────────────────────────────────────────────────────┘
   ~~~

- The execution lifecycle and infrastructure state are driven by two distinct logical components:

   - ClusterSizeConfig Custom Resource (CR): 
   
      - Acts as the central, persistent configuration registry (defining parameters like remoteIp, remoteUdpPort, and checkInterval). 
      
      - Because the configuration is stored as an independent Custom Resource instance, its operational parameters remain preserved in the cluster etc.d data store even if the operator controller deployment itself is completely uninstalled.

         ~~~ 
         # oc explain ClusterSizeConfig.spec
         GROUP:      management.example.com
         KIND:       ClusterSizeConfig
         VERSION:    v1alpha1
  
         FIELD: spec <Object>
   
         DESCRIPTION:
            ClusterSizeConfigSpec defines the desired state of ClusterSizeConfig
         FIELDS:
         check_interval	<string> -required-
           CheckInterval defines how frequently the operator re-evaluates cluster
           metrics and ships UDP payloads (e.g., "30s", "5m").
         
         log_max_rotations	<integer>
           LogMaxRotations sets the maximum number of historical backup log archive
           files to retain.
          
         log_max_size_bytes	<integer>
           LogMaxSizeCcBytes defines the hard file-size cap (in bytes) before
           triggering a rotation split.
         
         remote_ip	<string> -required-
           RemoteIp specifies the target destination IPv4 address of the remote VM
           telemetry collector receiver.
        
         remote_udp_port	<integer> -required-
           RemoteUdpPort specifies the destination network UDP socket port on the
           remote VM receiver listening for payload streams.
      
        secret	<string> -required-
          Secret points to the Name of the Corev1 Secret inside the namespace
          containing the mandatory 'HASH_SALT' cryptographic key.

        subscription_service_level	<string> -required-
          SubscriptionServiceLevel defines the support tier for the cluster. 
          Must be set to either "Premium" or "Standard".

        is_bare_metal	<boolean> -required-
          IsBareMetal defines whether the cluster runs on physical bare metal 
          hardware (true) or a virtualized platform (false).
          
        suspend	<boolean>
          Suspend flips the operational state of the controller loop. When set to
          true, active collection deployments are completely torn down.
        ~~~

- While it runs isolated inside its own namespace, it holds read-only cluster-level access to query raw node objects and cluster-version manifests.

- The operator extracts only the hardware data and version metrics required for core-based subscription compliance:

   - Unique OpenShift Cluster ID: (clusterID)
   - Cluster Version: Current platform release version vectors.
   - Hostnode Operational Role: Mapped via index values (e.g.: control-plane, infra, master, ODF, ingress, worker, etc. etc.).
   - Allocated vCPU Count: Total virtual cores per node.

- The operator enriches the telemetry data extracted from OpenShift with these additional parameters defined in the ClusterSizeConfig Custom Resource:

   - SubscriptionServiceLevel: The contract service tier associated with the cluster (Standard or Premium).
   - IsBareMetal: A boolean flag defining whether the cluster runs directly on physical bare-metal hardware (true) or within a virtualized environment (false)."
   
- The operator will confirm the Bare Metal platform using a new, step-by-step logic:

   - Step 1: Look for BareMetalHost Resources (Metal3)

      - The operator looks for active physical host objects (BareMetalHost).

   - Step 2: Parse the install-config.yaml ConfigMap

      - If no Bare Metal hosts are found, the operator falls back to reading the original installation configuration.
      
      - It inspects the platform fields to see if a specific infrastructure provider (such as vsphere, aws, etc.) other than none was declared.

   - Implemented Logic:

      - The isBareMetal: true condition defined in the ClusterSizeConfig acts strictly as a fallback; it is only applied if no active BareMetalHost resources are discovered and the platform fields inside the cluster-config-v1 ConfigMap are explicitly set to none.

      - Once an unconditional bare-metal state is confirmed, the value Baremetal is forced into the platform field of the telemetry H (Header) line. 
      
      - Conversely, if an explicit infrastructure platform (such as vsphere or aws) is detected within the cluster-config-v1 resource, that specific infrastructure string is reported in the H header instead.

      - This finalized parameter is ultimately propagated downstream to populate the PLATFORM field in the master report, dictating whether the node resource allocations are calculated as physical cores or virtual vCPUs.

## Data & Network Volume Evaluation

- When a telemetry check triggers (either via a manual configuration change or when the interval heartbeat expires), the internal fragmentation engine packages node records together, compresses them via Gzip, and streams them over UDP.

### Transmission Serialization & Sequence Numbers

   - To allow the central receiver to uniquely identify transmission windows, handle multi-packet reassembly, and prevent out-of-order log writes, the collector implements an independent, sequential message tracking mechanism:

      - Sequence Counter (.seq_counter):
     
         - Stored inside the pod's local persistent volume, a monotonically increasing 12-digit sequence tracking identifier (Msg ID) is generated for each execution loop (e.g., 000000000458).

      - Frame Multiplexing Header: 
      
         - The fragmentation engine prefixes each raw binary network chunk with a text envelope containing the sequence ID, the current frame index, and the total expected frames for that snapshot window.

      <br>
      
      ~~~
      [Sequence_Number],[Current_Frame],[Total_Frames]|
      [Example: 000000000458,000001,000002| followed by the compressed payload block.
      ~~~

### Telemetry String Structure

- The raw text layout nested inside the network frame packet envelope follows this structured layout prior to compression:

   ~~~
   H,[ClusterID],[NodeCount],[SubscriptionServiceLevel],[InstallDate],[Platform],[CurrentEpoch],[Arch]
   N,[ClusterID],[SequentialIndex],[RoleIndex],[Raw_CPU_Capacity],true
   R,[Base64_Encoded_Lookup_Table_Mapping...]
   T,[HMAC-SHA256_Signature]
   ~~~

   - H (Header Record) defines the global identity, contractual support tier, and resolved infrastructure layer of the OpenShift cluster.

      - ClusterID: The unique OpenShift Cluster UUID (extracted from the ClusterVersion resource).
      - NodeCount: The total number of active node objects discovered in the cluster.
      - SubscriptionServiceLevel]: The contract service tier defined in the CR (STANDARD or PREMIUM), used downstream to aggregate license gap balances.
      - InstallDate: Unix Epoch timestamp representing the cluster's initial completion/installation datetime.
      - Platform: The hierarchically resolved infrastructure provider (Baremetal, vsphere, aws, etc.), used downstream to dictate whether core metrics are calculated as physical or virtual.
      - CurrentEpoch: A dynamic time-token updated on each collection loop execution to preserve chronological order.
      - Arch: The underlying hardware instruction set architecture of the cluster hosts (e.g., amd64).

   - N (Node Record) represents the computational capacity metrics and operational groups of an individual host inside the cluster. One N line is generated for each node.

      - ClusterID: The associated cluster UUID, used downstream for row correlation.
      - SequentialIndex: A zero-padded incremental sequence number (e.g., 001, 002) identifying the node position in the frame.
      - RoleIndex: A numerical identifier referencing the node's specific role combination (e.g., 3, 4), mapped using the R record.
      - Raw_CPU_Capacity: The raw hardware CPU allocation metric reported directly from the node status capacity capacity vectors.
      - IsBaremetal: A fixed boolean placeholder set to true. The structural destination logic relies on the [Platform] element in the H line above to determine virtual vs physical processing constraints.


   - R (Reference / Lookup Record), acts as the translation dictionary for the obfuscated index values passed inside the frame.

      - Base64_Encoded_Lookup_Table: A Base64-obfuscated string. When decoded, it reveals a sequential, comma-separated lookup dictionary structured in a strict field order. 
      
         - The elements are ordered sequentially by index type: it leads with the cluster release versions (1=Current_Version followed by 2=Initial_Version), and continues immediately with the node role mappings in ascending numerical order based on their generated index values (e.g., 3=Role_Group_A, 4=Role_Group_x). 
         - This translates raw numerical indicators cleanly back to cleartext platform releases (e.g., 1=4.20.27) and combined node role labels (e.g., 3=control-plane#master).ship vectors matching numerical indices back to cleartext OpenShift release versions (e.g., 1=4.20.27) and labeled node roles (e.g., 3=control-plane master).

   - T (Trailer / Integrity Record), the cryptographic lock sealing the transmission stream against payload modifications or transport injection attempts across network boundaries.

      - HMAC-SHA256_Signature: The secure message authentication checksum generated by hashing the preceding payload lines (H, N, R) using the private HASH_SALT key managed inside the cluster namespace.

- Example of Telemtry data reassembled:

      ~~~
      # [AUDIT] MSG 000000000008 from 192.168.100.22 (1 frames) [INTEGRITY: OK]
      H,d08824f5-4252-4883-b587-01110c52ef2f,6,PREMIUM,1782827878,None,1784290200,amd64
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-001,control-plane master,40,true
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-002,control-plane master,40,true
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-003,control-plane master,40,true
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-004,worker,50,true
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-005,worker,50,true
      N,d08824f5-4252-4883-b587-01110c52ef2f,node-006,worker,50,true
      R,UiwxPTQuMjAuMjcsMj00LjE5LjMwLDM9Y29udHJvbC1wbGFuZSNtYXN0ZXIsND13b3JrZXI=
      T,13b2198ea71cece188d02b7de2cb50585a017b7b866b4f570dd4e8ba8af1b25f
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


## Network Impact Analysis:

- Network Footprint: 
   - The standard Ethernet Maximum Transmission Unit (MTU) limit is 1,500 bytes. 
   - By combining Gzip compression with an 80-node packet slicing threshold, no individual UDP packet ever exceeds 1,400 bytes. 
   - This completely eliminates IP fragmentation risks on the wire, preventing data drops on standard networks. 
   - A full 150-node snapshot burst takes less than a millisecond to transmit and is virtually invisible against normal background datacenter traffic.

## Security Impact Analysis:

- The Cluster Size Operator is configured strictly under the Principle of Least Privilege, 
- granting only the bare minimum permissions required for its operational lifecycle. 
- Scope boundaries isolate application workloads locally while exposing cluster-wide assets strictly as read-only streams.

   - Isolated Local Permissions (permissions scope)
   
      - All mutating administrative operations (Create, Read, Update, Delete) are locked explicitly inside the operator's dedicated deployment namespace (openshift-size-monitoring). 
      
      - The operator has zero capability to alter external application spaces:

         - Custom Resources (clustersizeconfigs, /status, /finalizers): Full state-reconciliation, status reporting, and safe-deletion tracking for the operator's primary interface.

         - Workload Infrastructure (deployments, serviceaccounts): Full lifecycle actions required to spawn, scale, and maintain backend sizing application pods.

         - Operational Controls (configmaps, persistentvolumeclaims, secrets): Storage management, configuration ingestion, and local credential manipulation confined entirely to the operator's namespace.

         - High-Availability & Audit (leases, events): Required exclusively for coordination blocks (leader election) and publishing contextual warning/info alerts directly into the cluster logging stream.
       
      ~~~
      permissions:
      - rules:
        - apiGroups:
          - ""
          resources:
          - configmaps
          - persistentvolumeclaims
          - serviceaccounts
          verbs:
          - create
          - delete
          - get
          - list
          - patch
          - update
          - watch
        - apiGroups:
          - ""
          resources:
          - events
          verbs:
          - create
          - patch
        - apiGroups:
          - apps
          resources:
          - deployments
          verbs:
          - create
          - delete
          - get
          - list
          - patch
          - update
          - watch
        - apiGroups:
          - coordination.k8s.io
          resources:
          - leases
          verbs:
          - create
          - delete
          - get
          - list
          - patch
          - update
          - watch
        - apiGroups:
          - management.example.com
          resources:
          - clustersizeconfigs
          verbs:
          - create
          - delete
          - get
          - list
          - patch
          - update
          - watch
        - apiGroups:
          - management.example.com
          resources:
          - clustersizeconfigs/finalizers
          verbs:
          - update
        - apiGroups:
          - management.example.com
          resources:
          - clustersizeconfigs/status
          verbs:
          - get
          - patch
          - update
        serviceAccountName: clustersize-controller-manager
      ~~~      

   - Read-Only Global Context (clusterPermissions scope)

      - To correctly size target infrastructures, the operator evaluates cluster topology using non-mutating, cluster-wide read queries (get, list, watch). 
      
      - No creation, modification, or deletion rights exist at the cluster layer:

         - Cluster Metadata (nodes): Read-only visibility into node capacity and structural topology to compute core-to-vCPU calculations.

         - Platform Engine (clusterversions): Read-only verification of OpenShift target architecture layers and version histories.

         - Platform Discovery (configmaps): Read-only access to read the global cluster-config-v1 configuration in kube-system to determine platform installation characteristics.

         - Physical Infrastructure (baremetalhosts): Read-only inspection of Metal3 entities to detect baremetal physical host presence.

      ~~~
      clusterPermissions:
      - rules:
        - apiGroups:
          - ""
          resources:
          - nodes
          - configmaps
          verbs:
          - get
          - list
          - watch
        - apiGroups:
          - config.openshift.io
          resources:
          - clusterversions
          verbs:
          - get
          - list
          - watch
        - apiGroups:
          - metal3.io
          resources:
          - baremetalhosts
          verbs:
          - get
          - list
          - watch
      ~~~

- Confidentiality (High): 
   - Real node hostnames are not transmitted; instead, they are anonymized using sequential index identifiers (e.g., 001, 002, reconstructed as node-001, node-002).
   - The underlying structural role mappings and versions are obscured inside a Base64 string payload row. 
   - Even if a network tap captures the packets, an attacker only sees an anonymous binary stream with zero internal infrastructure nomenclature.

- Integrity Verification: 
   - The receiver processes incoming frames in memory, decompresses the payload, and validates the cryptographic HMAC-SHA256 signature appended to the end of the text stream. 
   - If even a single bit is altered in transit, either the Gzip checksum fails or the HMAC verification breaks, prompting the receiver to drop the corrupted payload immediately.

   - Salts secret definition for telemetry_receiver.py

      - The telemetry_receiver.py script uses HMAC-SHA256 to verify payload integrity.
      - To avoid exposing the plain-text verification salt or its decryption password in the process list (ps aux), the salt is encrypted on disk and decrypted in-memory at startup.
      - **Note:** The Red Hat OpenShift secret is automatically created by the operator during its first installation with the default `HASH_SALT` value of `"MySecretSaltValue"`. 

         - Run these commands as root in the collector node to configure the decryption key and encrypt the HMAC salt.
         - Point Of Attention: Do not include leading or trailing spaces inside the quotation marks (e.g., use "MyPassword", not " MyPassword "), otherwise the spaces will become part of your cryptographic keys.
         
            ~~~
            # Step 1: Write the decryption password to a highly restricted keyfile
            echo -n "MyDecryptionPassword" | sudo tee /etc/.telemetry_key > /dev/null

            # Step 2: Lock down permissions (Read-only by root)
            sudo chmod 400 /etc/.telemetry_key
            sudo chown root:root /etc/.telemetry_key
            
            # Step 3: Encrypt the actual HMAC salt value using the keyfile
            echo -n "MySecretSaltValue" | sudo openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt -pass file:/etc/.telemetry_key -out /etc/telemetry_salt.enc
            ~~~

         - The full path to the .telemetry_key and telemetry_salt.enc can be modified in the telemetry_receiver.py

            ~~~
            SALT_FILE_PATH = "/etc/telemetry_salt.enc"
            KEY_FILE_PATH = "/etc/.telemetry_key"
            ~~~

         - You can verify that the decryption works seamlessly without prompting for a password by running this command.
   
            ~~~
            # Remember to update the file paths used in the example below if you deploy them in different locations.
            sudo openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass file:/etc/.telemetry_key -in /etc/telemetry_salt.enc
            ~~~

       - Salts secret definition in the openshift-size-monitoring project of Red Hat OpenShift Cluster:

          - **Note:** The Red Hat OpenShift secret is automatically created by the operator during its first installation with the default `HASH_SALT` value of `"MySecretSaltValue"`.          
          - You only need to perform the steps below if you want to update or customize this value. 
          - To update the secret in OpenShift, you can use either the command-line interface (oc CLI) or a YAML manifest file.
          
             - Using the oc CLI commands

                ~~~
                oc create secret generic clustersize-secrets \
                --namespace=openshift-size-monitoring \
                --from-literal=HASH_SALT="MySecretSaltValue" \
                --dry-run=client -o yaml | oc apply -f -
                ~~~

             - Using a YAML Manifest:
             
                -  Encode the salt using printf

                   ~~~
                   printf "MySecretSaltValue" | base64

                   # Output: TXlTZWNyZXRTYWx0VmFsdWU=
                   ~~~

                - Create the secret manifest file

                   ~~~
                   apiVersion: v1
                   kind: Secret
                   metadata:
                     name: clustersize-secrets
                     namespace: openshift-size-monitoring
                   type: Opaque
                   data:
                     HASH_SALT: TXlTZWNyZXRTYWx0VmFsdWU=
                   ~~~

                - Apply the manifest to the cluster
              
                   ~~~
                   oc apply -f clustersize-secret.yaml
                   ~~~
               
- Data Availability (Self-Healing): 

   - Because UDP is a connectionless protocol, it does not guarantee packet delivery. 

   - If a network switch drops a frame packet during heavy network congestion, the central receiver discards the incomplete payload. 
   
   - However, because the cluster operator continuously sends fresh telemetry updates at regular intervals, any missed snapshots self-heal automatically during the next interval cycle.

## Managing Multiple Disconnected Clusters
When operating multiple disconnected clusters across an enterprise, managing distinct streams of UDP telemetry requires a structured central ingestion architecture.

- Centralize Aggregation (The Secure Internal Ingestion Hub):

   - Deploy a single central Linux Bastion or dedicated Virtual Machine within your secure disconnected zone. This host runs a multi-threaded Python UDP receiver script (telemetry_receiver.py) that listens for incoming payload frames from all clusters.

      ~~~
      ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
      │    CLUSTER A    │      │    CLUSTER B    │      │    CLUSTER C    │
      └────────┬────────┘      └────────┬────────┘      └────────┬────────┘
               │                        │                        │
               └───────────────┐        │        ┌───────────────┘
                               ▼        ▼        ▼
                         ┌──────────────────────────────┐
                         │     CENTRAL BASTION HUB      │
                         │ - Multi-threaded UDP server  │
                         │ - Reassembles frames in-mem  │ 
                         └──────────────┬───────────────┘
                                        │
                                        ▼ [Raw Consolidated Logs: telemetry_YYYY-MM-DD.log]
                         ┌──────────────────────────────┐
                         │  deduplicate_telemetry.py    │
                         │  - Chronological dedup       │ [Stage 1: Processing]
                         │  - Isolates latest state     │
                         └──────────────┬───────────────┘
                                        │
                                        ▼ [Intermediate: telemetry_deduplicated.csv]
                         ┌──────────────────────────────┐
                         │  DATA DIODE / SECURE MEDIA   │ [Stage 2: One-way Data Transfer]
                         │  - One-way compliance CSV    │
                         └──────────────┬───────────────┘
                                        │
                                        ▼ 
                         ┌──────────────────────────────┐
                         │   evaluate_compliance.py     │
                         │  - Loads Subscriptions       │
                         │    inventory & lifecycles    │ [Stage 3: Compliance]
                         │  - Baremetal vs Virtualized  │
                         │  - Calculates Subscription   │
                         │    GAPs                      │
                         └──────────────┬───────────────┘
                                        │
                                        ▼ [Final Output: master_compliance.csv]
                         ┌──────────────────────────────┐
                         │  COMPLIANCE AUDIT REPORT     │
                         │  - Detailed node list        │
                         │  - Aggregated GAP analysis   │
                         └──────────────────────────────┘
      ~~~

- Reassembly and Daily Logging:

   - The telemetry_receiver.py daemon runs as a systemd service listening on an unprivileged port (e.g., UDP 5555).

   - The daemon evaluates incoming fragmented frames against their unique Message ID in memory using a thread-safe session map to prevent race conditions. 
   - Once all expected frames for a specific payload arrive, the daemon:

      - Terminates the session context.
      - Decompresses the unified byte-stream.
      - Validates the HMAC-SHA256 signature using the shared secret salt.
      - Appends the raw cleartext metrics into a central daily rolling log directory:

         ~~~
         /var/log/telemetry_report/
         └── telemetry_2026-07-12.log (Consolidated multi-cluster daily log)
         ~~~
      
- Three-Stage Processing Pipeline:
   - To process raw logs into a finalized compliance audit report, the ingestion hub splits operations into three distinct, modular stages:

      ~~~
      ┌────────────────────────────────────────────────────────┐
      │ 1. DEDUPLICATION (deduplicate_telemetry.py)            │ [Stage 1: Processing]
      │    Parses daily raw .log files and isolates latest     │
      │    state per cluster.                                  │
      └──────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼ [Intermediate: telemetry_deduplicated.csv]
      ┌────────────────────────────────────────────────────────┐
      │ 2. DATA DIODE / SECURE MEDIA                           │ [Stage 2: One-way Data Transfer]
      │    Unidirectional gateway for exporting the clean      │
      │    intermediate CSV to the compliance audit zone.      │
      └──────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼ [Transferred: telemetry_deduplicated.csv]
      ┌────────────────────────────────────────────────────────┐
      │ 3. COMPLIANCE & GAP ANALYSIS (evaluate_compliance.py)  │ [Stage 3: Compliance]
      │    Loads subscription inventories, lifecycles, maps    │
      │    baremetal vs virtual nodes, and calculates GAPs.    │
      └──────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼ [Final Output: master_compliance.csv]
      ~~~

      - Stage 1: Processing - Telemetry Deduplication (deduplicate_telemetry.py)
      
         - A scheduled cron job or manual trigger executes the deduplication script. 
         - It parses raw telemetry entries, discarding older historical updates to retain only the latest valid state for each unique Cluster_ID. 
         - It compiles an intermediate, clean raw CSV file:

            ~~~
            H,d08824f5-4252-4883-b587-01110c52ef2f,6,PREMIUM,2026-06-30 13:57:58 UTC,None,2026-07-17 11:29:59 UTC,amd64
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-001,control-plane master,40,true
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-002,control-plane master,40,true
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-003,control-plane master,40,true
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-004,worker,50,true
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-005,worker,50,true
            N,d08824f5-4252-4883-b587-01110c52ef2f,node-006,worker,50,true
            R,UiwxPTQuMjAuMjcsMj00LjE5LjMwLDM9Y29udHJvbC1wbGFuZSNtYXN0ZXIsND13b3JrZXI=
            T,8d0413d1b2f160001ddc1b6ba2c5ffd2a4b2a7a487705895a78bc4c6bd75dfd5
            ~~~

         - Deduplication CLI Options:

            ~~~
            usage: deduplicate_telemetry.py [-h] [--start START] [--end END] [--last-day] [--output OUTPUT]

            Deduplicate raw telemetry log streams.

            optional arguments:
              -h, --help       show this help message and exit
              --start START    Start Date (YYYY-MM-DD) to begin log selection
              --end END        End Date (YYYY-MM-DD) to end log selection
              --last-day       Process only the latest available log file
              --output OUTPUT  Path to the output deduplicated raw file
            ~~~

      - Stage 2: One-way Data Transfer - Data Diode / Secure Media

         - Physically isolates the production ingestion environment from the compliance evaluation systems.

         - Only the deduplicated, pre-filtered telemetry_deduplicated.csv is allowed to traverse the secure boundary.

         - Ensures that the target audit zone (Stage 3) has zero inbound network access back to the active OpenShift clusters.

         - **Note on Stage 2 implementation:**

            - Because the choice of one-way transport technology depends entirely on internal security compliance and physical isolation standards, the best technical solution for Stage 2 must be evaluated and defined exclusively by the Customer.


      - Stage 3: Compliance Compliance & Gap Evaluation (evaluate_compliance.py)

         - The evaluation script consumes the deduplicated output of Stage A.
         
         - It correlates raw topology with OCP version support windows and active purchase contracts to output the finalized audit report.
         
         - Infrastructure Core Sizing: 
         
            - If a cluster platform is flagged as Baremetal, resources are evaluated under TOTAL_PHYSICAL_CPU_CORES and subscription usage is computed as Cores / 2. 
            
            - All other platforms default to virtualized virtualization environments where core-counts are routed to TOTAL_VIRTUAL_VCPUS and mapped as vCPUs / 4.
            
         - Target Filtering:
        
            - Skips hosted instances (e.g., aws, aro, azure) and filters infrastructure, master, and control-plane node allocations from subscription metrics for clusters larger than 3 nodes.
            
         - Subscription Gap Analysis:

            - Evaluates OCP version lifecycles and appends summarized metrics highlighting overall node loads, active subscription inventories, and compliance deficits (GAP rows) under standard and premium tiers.

         - Example of CSV output generated from evaluate_compliance.py

            ~~~
            CLUSTER_ID,PLATFORM,CLUSTER_VERSION,CLUSTER_INITIAL_VERSION,CLUSTER_NODE_COUNT,CLUSTER_INSTALLED_AT,SUPPORT,HOSTNAME,NODE_ROLES,NODE_ARCHITECTURE,LAST_UPDATE_RECEIVED,TOTAL_PHYSICAL_CPU_CORES,TOTAL_VIRTUAL_VCPUS,TOTAL_MEMORY,TOTAL_REQUIRED_SUB_FOR_PHYSICAL_CPU_CORES,TOTAL_REQUIRED_SUB_FOR_VIRTUAL_VCPUS,EUS_TERM1_REQUIRED_SUBS_PHYSICAL_CPU_CORES,EUS_TERM2_REQUIRED_SUBS_PHYSICAL_CPU_CORES,EUS_TERM3_REQUIRED_SUBS_PHYSICAL_CPU_CORES,EUS_TERM1_REQUIRED_SUBS_VIRTUAL_VCPUS,EUS_TERM2_REQUIRED_SUBS_VIRTUAL_VCPUS,EUS_TERM3_REQUIRED_SUBS_VIRTUAL_VCPUS,IS_GRAND_TOTAL
            d08824f5-4252-4883-b587-01110c52ef2f,NotAvailable,4.20.27,4.19.30,6,2026-06-30 13:57:58 UTC,PREMIUM,node-004,worker,AMD64,2026-07-17 11:29:59 UTC,0,50,NotAvailable,0,13,0,0,0,0,0,0,0
            d08824f5-4252-4883-b587-01110c52ef2f,NotAvailable,4.20.27,4.19.30,6,2026-06-30 13:57:58 UTC,PREMIUM,node-005,worker,AMD64,2026-07-17 11:29:59 UTC,0,50,NotAvailable,0,13,0,0,0,0,0,0,0
            d08824f5-4252-4883-b587-01110c52ef2f,NotAvailable,4.20.27,4.19.30,6,2026-06-30 13:57:58 UTC,PREMIUM,node-006,worker,AMD64,2026-07-17 11:29:59 UTC,0,50,NotAvailable,0,13,0,0,0,0,0,0,0
            AMD64 GRAND TOTAL LOAD - STANDARD,,,,,,STANDARD,,,AMD64,,0,0,0,0,0,0,0,0,0,0,0,1
            AMD64 GRAND TOTAL LOAD - PREMIUM,,,,,,PREMIUM,,,AMD64,,0,150,0,0,39,0,0,0,0,0,0,1
            s390x GRAND TOTAL LOAD - STANDARD,,,,,,STANDARD,,,s390x,,0,0,0,0,0,0,0,0,0,0,0,1
            s390x GRAND TOTAL LOAD - PREMIUM,,,,,,PREMIUM,,,s390x,,0,0,0,0,0,0,0,0,0,0,0,1
            AMD64 SUBSCRIPTION AVAILABLE - STANDARD,,,,,,STANDARD,,,AMD64,,,,,917,0,693,100,200,0,0,0,2
            AMD64 SUBSCRIPTION AVAILABLE - PREMIUM,,,,,,PREMIUM,,,AMD64,,,,,985,0,0,1,1,0,0,0,2
            s390x SUBSCRIPTION AVAILABLE - STANDARD,,,,,,STANDARD,,,s390x,,,,,18,0,0,0,0,0,0,0,2
            s390x SUBSCRIPTION AVAILABLE - PREMIUM,,,,,,PREMIUM,,,s390x,,,,,36,0,0,0,0,0,0,0,2
            GAP AMD64 SUBSCRIPTIONS - STANDARD,,,,,,STANDARD,,,AMD64,,,,,-917,0,-693,-100,-200,0,0,0,3
            GAP AMD64 SUBSCRIPTIONS - PREMIUM,,,,,,PREMIUM,,,AMD64,,,,,-946,0,0,-1,-1,0,0,0,3
            GAP s390x SUBSCRIPTIONS - STANDARD,,,,,,STANDARD,,,s390x,,,,,-18,0,0,0,0,0,0,0,3
            GAP s390x SUBSCRIPTIONS - PREMIUM,,,,,,PREMIUM,,,s390x,,,,,-36,0,0,0,0,0,0,0,3
            ~~~
              
         - Evaluation CLI Options:

            ~~~
            Usage: evaluate_compliance.py [-h] [--input INPUT] [--output OUTPUT] [--subscriptions SUBSCRIPTIONS] [--lifecycle LIFECYCLE] [--start START] [--end END]

            Evaluate cluster capacity license compliance and resource gaps.
            
            optional arguments:
              -h, --help                     show this help message and exit
              --input INPUT                  Path to the deduplicated raw telemetry file
              --output OUTPUT                 Path to write the final compliance CSV report
              --subscriptions SUBSCRIPTIONS  Path to customer subscription file
              --lifecycle LIFECYCLE          Path to OpenShift lifecycle matrix mapping
              --start START                  Start Date (YYYY-MM-DD) for active EUS calculations
              --end END                      End Date (YYYY-MM-DD) for active EUS calcula
            ~~~      

## Custer Size Operator Installation:

   - Step 1: Add the clustersize-catalog to the Red Hat OpenShift cluster:

      - In the top-right header banner of the Web Console, look for the Quick Create icon (the + icon).
      - Select Import YAML.
      - Paste the following resource configuration:

         ~~~
         apiVersion: operators.coreos.com/v1alpha1
         kind: CatalogSource
         metadata:
           name: clustersize-catalog
           namespace: openshift-marketplace
         spec:
           displayName: Cluster Size Operator Catalog
           publisher: Platform Team
           sourceType: grpc
           image: ghcr.io/rbruzzon73/clustersize-catalog:v2.0.102
           updateStrategy:
             registryPoll:
               interval: 45m
         ~~~
      - Click on create.
      

   - Step 2: Locate the Operator in the OpenShift Software Catalog (Ref: Figure 1)

      - Log in to your Red Hat OpenShift web console. Navigate to Ecosystem > Software Catalog in the left-hand menu. Search for "Cluster Size Operator", click on its tile to open the detail pane, and click Install to begin the configuration.

      <p align="left">
        <em><strong>Figure 2 - Red Hat OpenShift Software Catalog</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/1-SoftwareCatalog-ClusterSizeOperator-Install.png" width="850">
      </p>
      <br>

   - Step 3: On the Operator Installation page, confirm the operator deployment in the recommended namespace: openshift-size-monitoring (Ref: Figure 2)
   
     <p align="left">
        <em><strong>Figure 3 - Operator installation in openshift-size-monitoring namespace</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/2-clustersizeoperator-installed-in-openshift-size-monitoring.png" width="850">
     </p>
     <br>

   - Step 4: Verify Successful Operator Deployment (Ref: Figure 3)
     
      - OpenShift will pull the operator image and prepare the deployment. Once the installation completes, the console will display an "Operator installed successfully" message.
      
      - The Custom Resource Definitions (CRDs) are now registered, meaning your cluster's API is ready to accept configuration objects.

      <p align="left">
        <em><strong>Figure 4 - Operator installed successfully</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/3-clustersizeoperator-installed.png" width="425">
      </p>
      <br>

   - Step 5: Open the ClusterSizeConfig Creation Form (Ref: Figure 4)
     
      - Navigate to the installed operator details and click on Create ClusterSizeConfig.
        
      - This opens a user-friendly form where you can define your monitoring settings, including the check interval, remote server IP, UDP port, and target cryptographic validation secret.

      <p align="left">
        <em><strong>Figure 5 - Create ClusterSizeConfig</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/4-ClusterSizeConfig-definintion.png" width="850">
      </p>
      <br>


   - Step 6: Configure and Save Sizing Parameters (Ref: Figure 6)
   
      - Fill in the configuration details for your monitor:

         - Check Interval: Define how often the operator checks cluster metrics (e.g., 1h or 60s).

         - Remote IP and UDP Port: Specify the destination endpoint receiving your telemetry network packets.

         - Secret: Provide the name of the Kubernetes Secret (e.g., clustersize-secrets or pippo-secret) containing the mandatory HASH_SALT key for HMAC signing.

         - Log limits: Define maximum file size and rotation values before saving.
         
         - IsBareMetal: Used to identify if the cluster runs directly on physical bare-metal hardware (true) or within a virtualized environment (false).

         - SubscriptionServiceLevel: The contract service tier associated with the cluster (Standard or Premium).

      <p align="left">
        <em><strong>Figure 6 - ClusterSizeConfig created</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/5-configurationexample.png" width="850">
      </p>
      <br>

   - Step 7: Verify Active Workload Pods (Ref: Figure 7)
      - Once the configuration is saved, the operator deploys the necessary backend workloads. In your OpenShift topology view or pod list, you will see two running pods:

         - controller-manager: The control plane pod that watches your configurations and manages resources.

         - clustersize: The worker data-plane pod that collects cluster metrics, signs them securely using the key in your secret, and streams them out via UDP.

      <p align="left">
        <em><strong>Figure 7 - Cluster Size Operator PODs</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/7-clustersizeconfigs-pods.png" width="425">
      </p>
      <br>

## Telemetry Receiver Configuration and Deployment

   - This procedure describes how to install, configure, and verify the telemetry_receiver.py component to successfully capture sizing data sent by the clustersize-operator.

      - Prerequisites

         - A target server running a Linux operating system (RHEL/CentOS/Ubuntu).

         - Python version 3.8 or higher installed on the server.

         - Network connectivity open between the OpenShift cluster nodes and the telemetry server on the configured UDP port.
       
      - Installation and Startup Procedure

         - Firewall Port Configuration

            - To allow the server to accept incoming UDP traffic from the operator, open the telemetry port (e.g., 555):

               ~~~
               sudo firewall-cmd --add-port=555/udp --permanent
               sudo firewall-cmd --reload
               ~~~

         - Script Deployment

            - Create a dedicated directory (e.g., /opt/telemetry/) to the Telemetry Receiver

               ~~~
               mkdir /opt/telemetry/
               ~~~

            - Dowload the file [telemetry_receiver.py](https://github.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/blob/main/telemetry_receiver/telemetry_receiver.py)

            - Move the telemetry_receiver.py in the directory dedicated to the Telemetry Receiver (e.g., /opt/telemetry/)
          
         - HMAC Salt definition 

            - Write the decryption password to a highly restricted keyfile
            
               ~~~
               echo -n "MyDecryptionPassword" | sudo tee /etc/.telemetry_key > /dev/null
               ~~~
               
            - Lock down permissions (Read-only by root)
                        
               ~~~
               sudo chmod 400 /etc/.telemetry_key
               sudo chown root:root /etc/.telemetry_key
               ~~~
            
            - Encrypt the actual HMAC salt value using the keyfile 
            
               - `MySecretSaltValue` is the default value used by the Cluster Size Operator in Red Hat OpenShift

                  ~~~
                  echo -n "MySecretSaltValue" | sudo openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt -pass file:/etc/.telemetry_key -out /etc/telemetry_salt.enc
                  ~~~

         - Background Service Configuration 

            - To ensure the receiver runs continuously in the background and restarts automatically on failures, configure it as a systemd service.

            - In the context of a telemetry receiver command, those flags configure how long received data is kept and whether it is printed to the screen:

               - `--retention 90`: Specifies that the receiver should keep or store the collected telemetry data for 90 days before automatically deleting (pruning) it to save disk space.
               - `--display=false`: Tells the script not to print the incoming telemetry data to the standard output (terminal screen) in real time to prevent the log files from growing excessively large with repetitive data dumps.

            - Follow these steps to create the Telemetry Receiver Background Service:

               ~~~
               sudo cat << 'EOF' > /etc/systemd/system/telemetry.service
               [Unit]
               Description=Telemetry Receiver Service
               After=network.target
               
               [Service]
               Type=simple
               ExecStart=/usr/bin/python3 /opt/telemetry/telemetry_receiver.py --retention 90 --display=false
               Restart=on-failure
               
               [Install]
               WantedBy=multi-user.target
               EOF
               
               # Reload systemd, enable, and start the service
               sudo systemctl daemon-reload
               sudo systemctl enable --now telemetry.service
               ~~~

         - Verification

            - Verify that the service is active, running, and listening without errors:

               ~~~
               sudo systemctl status telemetry.service

               # Monitor incoming metrics and telemetry logs in real time
               sudo journalctl -u telemetry.service -f
               ~~~       

            
## Telemetry deduplication and evaluation compliance - **WORK IN PROGRESS**

- Initial versions are available at the [telemetry_receiver repository](https://github.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/tree/main/telemetry_receiver)

   - deduplicate_telemetry.py syntax

      ~~~
      $ python3 deduplicate_telemetry.py --help
      usage: deduplicate_telemetry.py [-h] [--start START] [--end END] [--last-day] [--output OUTPUT]

      Deduplicate raw telemetry log streams.

      optional arguments:
        -h, --help       show this help message and exit
        --start START    Start Date (YYYY-MM-DD)
        --end END        End Date (YYYY-MM-DD)
        --last-day       Process only the latest available log file
        --output OUTPUT  Path to the output deduplicated raw file
      ~~~

   - evaluate_compliance.py syntax

       ~~~
       $ python3 evaluate_compliance.py --help
       usage: evaluate_compliance.py [-h] [--input INPUT] [--output OUTPUT] [--subscriptions SUBSCRIPTIONS] [--lifecycle LIFECYCLE] [--start START] [--end END]

       Evaluate cluster capacity license compliance and resource gaps.

       optional arguments:
         -h, --help                         show this help message and exit
         --input INPUT                      Path to the deduplicated raw telemetry file
         --output OUTPUT                    Path to write the final compliance CSV report
         --subscriptions SUBSCRIPTIONS      Path to customer subscription file
         --lifecycle LIFECYCLE              Path to OpenShift lifecycle matrix mapping
         --start START                      Start Date (YYYY-MM-DD) for active EUS calculations
         --end END                         End Date (YYYY-MM-DD) for active EUS calculations
       ~~~

       - Example of subscription file (default: subscriptions.txt) content:

       ~~~
       premium_s390x_subscriptions=36
       standard_s390x_subscriptions=18
       premium_ocp_subscriptions=985
       standard_ocp_subscriptions=917
       standard_ocp_term_1=693
       standard_ocp_term_2=100
       standard_ocp_term_3=200
       premium_ocp_term_2=1
       premium_ocp_term_3=1
       ~~~

       - How to genare the OpenShift lifecycle matrix mapping file (default: ocp_lifecycle.csv):

          - The creation of `ocp_lifecycle.csv` can be automated using the following steps:

             - Fetch the lifecycle data from access.redhat.com and save it as a JSON file:

                ~~~
                $ curl -L -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" -o ocp_lifecycle-orig.json "https://access.redhat.com/product-life-cycles/api/v1/products?name=Red%20Hat%20OpenShift%20Container%20Platform"

                % Total    % Received % Xferd  Average Speed  Time    Time    Time   Current
                                 Dload  Upload  Total   Spent   Left   Speed
               100  41973 100  41973   0      0 147.6k      0                              0
               ~~~

          - Parse the JSON data, extract the required support phases, and format it into a CSV file with headers:

             ~~~
             $ jq -r '
               .data[0].versions[] | 
               select(.name | startswith("4.")) |
               [
                 .name,
                 (.phases[] | select(.name == "Extended update support") | if .start_date == "N/A" then "" else .start_date[:10] end),
                 (.phases[] | select(.name == "Extended update support") | if .end_date == "N/A" then "" else .end_date[:10] end),
                 (.phases[] | select(.name == "Extended update support Term 2") | if .start_date == "N/A" then "" else .start_date[:10] end),
                 (.phases[] | select(.name == "Extended update support Term 2") | if .end_date == "N/A" then "" else .end_date[:10] end),
                 (.phases[] | select(.name == "Extended update support Term 3") | if .start_date == "N/A" then "" else .start_date[:10] end),
                 (.phases[] | select(.name == "Extended update support Term 3") | if .end_date == "N/A" then "" else .end_date[:10] end)
               ] | @csv
             ' ocp_lifecycle-orig.json | tr -d '"' | sed '1i major_minor,t1_start,t1_end,t2_start,t2_end,t3_start,t3_end' > ~/ocp_lifecycle.csv
             ~~~


   
