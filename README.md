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
   │  - Collects: vCPU, Hypervisor (BM vs VM)          │
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
   - Deployment Environment State: (true for Bare-Metal hardware, false for virtualized OpenStack/KVM instances).

- The operator determines the cluster's platform using a step-by-step logic. 
- However, there is a specific blind spot when it comes to User-Provisioned Infrastructure (UPI) Baremetal deployments.
- Here is how the logic behaves:

   - Step 1: Check for BareMetalHost Resources (Metal3)
   
      - The operator looks for active physical host objects (BareMetalHost).

      - In a standard UPI deployment, because you provision the operating system and hardware manually outside of OpenShift, these BareMetalHost objects are not present.

   - Step 2: Parse the install-config.yaml ConfigMap

      - If no baremetal hosts are found, the operator falls back to reading the original installation configuration. It looks at the platform fields to see if a specific infrastructure provider (like vsphere, aws, etc.) was declared.

      - The UPI Limitation: For UPI baremetal installations, the standard practice is to set the platform to none: {}.

   - Step 3: Fallback to "None"

      - If both checks yield nothing (no BareMetalHost objects exist, and the install-config platform is empty or set to none), the operator has no physical or API-driven indicators to know it is running on physical hardware. It must default to None.

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
   H,[ClusterID],[NodeCount],[VersionIndex],[InitVersionIndex],[InstallDate],None,[CurrentEpoch],[Arch]
   N,[ClusterID],[SequentialIndex],[RoleIndex],[vCPU],[IsBaremetal]
   R,[Base64_Encoded_Lookup_Table_Mapping_Indices_To_Cleartext_Versiosn and Roles]
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
               
Availability (Self-Healing): 
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
                         │  DATA DIODE / SECURE MEDIA   │
                         │  - One-way transport zone    │
                         └──────────────┬───────────────┘
                                        │
                                        ▼ [Stage 1: Processing]
                         ┌──────────────────────────────┐
                         │  deduplicate_telemetry.py    │
                         │  - Chronological dedup       │
                         │  - Isolates latest state     │
                         └──────────────┬───────────────┘
                                        │
                                        ▼ [Intermediate: telemetry_deduplicated.csv]
                         ┌──────────────────────────────┐
                         │   evaluate_compliance.py     │
                         │  - Loads Subscriptions       │
                         │    inventory & lifecycles    │
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
      
- Two-Stage Processing Pipeline
   - To process raw logs into a finalized compliance audit report, the ingestion hub splits operations into two distinct, modular scripts:

      ~~~
      ┌────────────────────────────────────────────────────────┐
      │ 1. DEDUPLICATION (deduplicate_telemetry.py)            │
      │    Parses daily raw .log files and isolates latest      │
      │    state per cluster.                                  │
      └──────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼ [telemetry_deduplicated.csv] (Clean raw format)
      ┌────────────────────────────────────────────────────────┐
      │ 2. COMPLIANCE & GAP ANALYSIS (evaluate_compliance.py)  │
      │    Loads subscriptions, lifecycles, maps baremetal vs   │
      │    virtualized metrics, and generates gap matrices.      │
      └──────────────────────────┬─────────────────────────────┘
                                 │
                                 ▼ [master_compliance.csv] (Final tabular repo
      ~~~

      - Telemetry Deduplication (deduplicate_telemetry.py)
      
         - A scheduled cron job or manual trigger executes the deduplication script. 
         - It parses raw telemetry entries, discarding older historical updates to retain only the latest valid state for each unique Cluster_ID. 
         - It compiles an intermediate, clean raw CSV file:

            ~~~
            H,999924f5-4252-4883-b587-01110c52ef2f,4,4.20.27,4.19.30,2026-01-15 09:00:00 UTC,None,2026-07-14 15:30:00 UTC,amd64
            N,999924f5-4252-4883-b587-01110c52ef2f,hist-node-01,control-plane master,40,true
            N,999924f5-4252-4883-b587-01110c52ef2f,hist-node-02,control-plane master,40,true
            N,999924f5-4252-4883-b587-01110c52ef2f,hist-node-03,worker,50,true
            N,999924f5-4252-4883-b587-01110c52ef2f,hist-node-04,worker,50,true
            R,UiwxPTQuMjAuMjcsMj00LjE5LjMw
            T,token-hist-jul
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


      - Compliance & Gap Evaluation (evaluate_compliance.py)

         -The evaluation script consumes the deduplicated output of Stage A.
         - It correlates raw topology with OCP version support windows and active purchase contracts to output the finalized audit report.
         
         - Infrastructure Core Sizing: 
            - If a cluster platform is flagged as Baremetal, resources are evaluated under TOTAL_PHYSICAL_CPU_CORES and subscription usage is computed as Cores / 2. 
            - All other platforms default to virtualized virtualization environments where core-counts are routed to TOTAL_VIRTUAL_VCPUS and mapped as vCPUs / 4.
            
         - Target Filtering: 
            - Skips hosted instances (e.g., aws, aro, azure) and filters infrastructure, master, and control-plane node allocations from subscription metrics for clusters larger than 3 nodes.
            
         - Financial Gap Analysis: Evaluates OCP version lifecycles and appends summarized metrics highlighting overall loads, active purchase inventories, and compliance deficits (GAP rows) under standard and premium tiers.
         
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

   - Step 1: Locate the Operator in the OpenShift Software Catalog (Ref: Figure 1)

      - Log in to your Red Hat OpenShift web console. Navigate to Ecosystem > Software Catalog in the left-hand menu. Search for "Cluster Size Operator", click on its tile to open the detail pane, and click Install to begin the configuration.

      <p align="left">
        <em><strong>Figure 1 - Red Hat OpenShift Software Catalog</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/1-SoftwareCatalog-ClusterSizeOperator-Install.png" width="850">
      </p>
      <br>

   - Step 2: On the Operator Installation page, confirm the operator deployment in the recommended namespace: openshift-size-monitoring (Ref: Figure 2)
   
     <p align="left">
        <em><strong>Figure 2 - Operator installation in openshift-size-monitoring namespace</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/2-clustersizeoperator-installed-in-openshift-size-monitoring.png" width="850">
     </p>
     <br>

   - Step 3: Verify Successful Operator Deployment (Ref: Figure 3)
     
      - OpenShift will pull the operator image and prepare the deployment. Once the installation completes, the console will display an "Operator installed successfully" message.
      
      - The Custom Resource Definitions (CRDs) are now registered, meaning your cluster's API is ready to accept configuration objects.

      <p align="left">
        <em><strong>Figure 3 - Operator installed successfully</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/3-clustersizeoperator-installed.png" width="425">
      </p>
      <br>

   - Step 4: Open the ClusterSizeConfig Creation Form (Ref: Figure 4)
     
      - Navigate to the installed operator details and click on Create ClusterSizeConfig.
        
      - This opens a user-friendly form where you can define your monitoring settings, including the check interval, remote server IP, UDP port, and target cryptographic validation secret.

      <p align="left">
        <em><strong>Figure 4 - Create ClusterSizeConfig</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/4-ClusterSizeConfig-definintion.png" width="850">
      </p>
      <br>

   - Step 5: Manage Sizing Configurations (Ref: Figure 5)
     
      - In the ClusterSizeConfigs tab of the operator, you can view, edit, or delete existing configuration instances running in your namespace.
        
      - This dashboard lets you track the current status and last update times for each monitoring configuration.

      <p align="left">
        <em><strong>Figure 5 - ClusterSizeConfig example</strong></em><br>
        <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/6-example-clustersizeconfigs.png" width="850">
      </p>
      <br>

   - Step 6: Configure and Save Sizing Parameters (Ref: Figure 6)
   
      - Fill in the configuration details for your monitor:

         - Check Interval: Define how often the operator checks cluster metrics (e.g., 1h or 60s).

         - Remote IP and UDP Port: Specify the destination endpoint receiving your telemetry network packets.

         - Secret: Provide the name of the Kubernetes Secret (e.g., clustersize-secrets or pippo-secret) containing the mandatory HASH_SALT key for HMAC signing.

         - Log limits: Define maximum file size and rotation values before saving.

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

            
## Cluster Size Operator integration with the solution: Evaluating Red Hat OpenShift 4 Subscriptions for Connected Clusters Using Telemetry Data (Pending Implementation)
https://access.redhat.com/solutions/7144723

