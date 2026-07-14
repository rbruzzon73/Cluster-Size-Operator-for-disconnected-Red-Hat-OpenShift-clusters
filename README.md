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

         - Cluster Metadata (nodes): Read-only visibility into node capacity and structural topology to compute structural calculations.

         - Platform Engine (clusterversions): Read-only verification of OpenShift target architecture layers.

      ~~~
      clusterPermissions:
      - rules:
        - apiGroups:
          - ""
          resources:
          - nodes
          - secrets
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

         - Run these commands as root in the collector node to configure the decryption key and encrypt your HMAC salt.

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

          -  To create the secret in OpenShift (OCP), you can use either the command-line interface (oc CLI) or a YAML manifest file.

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
                                        ▼
                         ┌──────────────────────────────┐
                         │  DATA DIODE / SECURE MEDIA   │
                         │  - One-way compliance CSV    │
                         └──────────────────────────────┘
      ~~~

- Centralized Aggregation & Reassembly:

   - This host runs telemetry_receiver.py as a systemd daemon listening on an unprivileged port (e.g., UDP 5555).

   - The daemon evaluates incoming fragmented frames against their unique Message ID in memory using a thread-safe session map to prevent race conditions.

   - Once all expected frames for a specific payload arrive, the daemon terminates the session context, decompresses the unified byte-stream, validates the HMAC-SHA256 signature, and appends the raw cleartext metrics into a central daily rolling log:

      ~~~
      /var/log/telemetry_report/
      └── telemetry_2026-07-12.log (Consolidated multi-cluster daily log)
      ~~~
      
- Automated Consolidation: (Pending Implementation)

   - A scheduled cron job parses the daily rolling log, deduplicates the entries by extracting the latest valid timestamp for each unique Cluster_ID, and compiles a single, unified CSV master compliance file:

      ~~~
      Cluster_ID,Masked_Node,Role,CPU,IsBaremetal
      d08824f5-4252...,node-001,control-plane infra master,40,true
      d08824f5-4252...,node-005,ODF ingress worker,120,true
      d08824f5-4252...,node-007,ruolo1 ruolo2 worker,64,true
      ~~~
      
## Data Diode or Secure Media Transfer: 
   - The finalized CSV compliance report is then transferred out of the isolated zone via a unidirectional hardware data diode or a secure media transfer protocol, guaranteeing strict one-way data movement without allowing inbound network access.


## Custer Size Operator Installation (Pending Implementation)

   - Step 1: Locate the Operator in the OpenShift Software Catalog (Ref: Figure 1)

      - Log in to your Red Hat OpenShift web console. Navigate to Ecosystem > Software Catalog in the left-hand menu. Search for "Cluster Size Operator", click on its tile to open the detail pane, and click Install to begin the configuration.

         <p align="left">
           <em><strong>Figure 1 - Red Hat OpenShift Software Catalog</strong></em><br>
           <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/1-SoftwareCatalog-ClusterSizeOperator-Install.png" width="850">
         </p>
         <br>

   - Step 2: On the Operator Installation page, confirm the operator deployment in the recommended namespace: openshift-size-monitoring
   
         <p align="left">
           <em><strong>Figure 2 - Operator installation in openshift-size-monitoring namespace</strong></em><br>
           <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/2-clustersizeoperator-installed-in-openshift-size-monitoring.png" width="850">
         </p>
         <br>

<p align="left">
  <em><strong>Figure 3 - Operator installed successfully</strong></em><br>
  <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/3-clustersizeoperator-installed.png" width="850">
</p>
<br>

<p align="left">
  <em><strong>Figure 4 - Create ClusterSizeConfig</strong></em><br>
  <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/4-ClusterSizeConfig-definintion.png" width="850">
</p>
<br>

<p align="left">
  <em><strong>Figure 5 - ClusterSizeConfig example</strong></em><br>
  <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/6-example-clustersizeconfigs.png" width="850">
</p>
<br>

<p align="left">
  <em><strong>Figure 6 - ClusterSizeConfig created</strong></em><br>
  <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/5-configurationexample.png" width="850">
</p>
<br>

<p align="left">
  <em><strong>Figure 7 - Cluster Size Operator PODs</strong></em><br>
  <img src="https://raw.githubusercontent.com/rbruzzon73/Cluster-Size-Operator-for-disconnected-Red-Hat-OpenShift-clusters/main/clustersize-operator-images/7-clustersizeconfigs-pods.png" width="850">
</p>
<br>

## Cluster Size Operator integration with the solution: Evaluating Red Hat OpenShift 4 Subscriptions for Connected Clusters Using Telemetry Data (Pending Implementation)
https://access.redhat.com/solutions/7144723

