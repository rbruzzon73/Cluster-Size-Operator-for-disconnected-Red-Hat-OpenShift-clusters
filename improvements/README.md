# Cluster Size Operator improvements and Developements

## First Improvement (Completed Jul 19, 2026)

- Two new parameters will be added to the current ClusterSizeConfig [1]:

   - "Subscription Service Level": A mandatory field with only two allowed values: Premium or Standard.

   - "Is Bare Metal": A mandatory boolean field (true or false).

   - Note: Both parameters are mandatory, and the user interface must guide the user to select only valid, feasible values for these fields.

## Second Improvement (Completed Jul 19, 2026)

   - The logic used to determine if the cluster is Bare Metal or Virtual [2] will be updated as follows:

   - The operator will confirm the Bare Metal platform using a new, step-by-step logic:

      - Check 1: Look for BareMetalHost Resources (Metal3)
         - The operator looks for active physical host objects (BareMetalHost).

      - Check 2: Parse the install-config.yaml ConfigMap
         - If no Bare Metal hosts are found, the operator falls back to reading the original installation configuration. 
         - It inspects the platform fields to see if a specific infrastructure provider (such as vsphere, aws, etc.) other than none was declared.

      - Implemented Logic:

         - The Is Bare Metal: true condition defined in the ClusterSizeConfig is only used if no BareMetalHost resources are found and the platform fields of the cluster-config-v1 resource are set to none.

         - If Is Bare Metal: true is confirmed, the value Bare Metal will be forced in the Deployment Environment State of the H header.

         - If a different platform value is found in the cluster-config-v1 resource (such as vsphere, aws, etc.), that specific retrieved value will be reported in the H header instead.

         - This final value will be used to populate the PLATFORM field of the final report and to identify whether the cluster CPUs are physical or virtual.

      - ClusterSizeConfigs updated:

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
   
         is_bare_metal	<boolean> -required-
           IsBareMetal defines whether the cluster runs on physical bare metal 
           hardware (true) or a virtualized platform (false).
   
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
      
         suspend	<boolean>
           Suspend flips the operational state of the controller loop. When set to
           true, active collection deployments are completely torn down.
         ~~~

## Third Improvement (Completed Jul 19, 2026)

- The Subscription Service Level (Premium or Standard) defined in the ClusterSizeConfigs will be extended to the cluster's H header.

   - This parameter will be propagated and used across all blocks of the solution (telemetry_receiver.py, evaluate_compliance.py, and deduplicate_telemetry.py) to correctly evaluate data integrity and the support value associated with the cluster in the final report.


## New Development (Started pm Jul 19, 2026)

- Implementation of an Aggregator Cluster Size Operator within a central Red Hat OpenShift cluster to collect, deduplicate, and evaluate reports sent from all managed OpenShift clusters.

   - Core Operator Functions

      - The operator core is built on two primary functional scripts:

         - deduplicate_telemetry.py: Consolidates incoming data streams and removes duplicate entries.

         - evaluate_compliance.py: Assesses the collected data against compliance baselines.

   - Presentation Layer

      - The deployment includes a visual dashboard interface that provides:

         - Graphical Access: A web-based UI to view the final compiled reports.

         - Data Export: The ability to download the underlying report data in CSV format.

   - Access Control & Security

      - To ensure data security, access to the presentation layer is restricted using Role-Based Access Control (RBAC), limiting visibility exclusively to:

         - Cluster Admins

         - Designated Custom Roles
  


# Impacts evaluation:

   - First, Second and Third improvements:

      - Files changed to implement the first, second and third improvements:

         - api/v1alpha1/clustersizeconfig/types.go
         - internal/controller/clustersizeconfig_controller.go
         - deduplicate_telemetry.py
         - evaluate_compliance.py
      
      - These changes are ready to be tested.

   - New Development:

      - Aggregator Cluster Size Operator

         - ETA: To be determined.
         - Development will begin once all current activities for the Cluster Size Operator are completed. concluded.


[1] #--------- Current Cluster Size Parameters (Reference) ---------#
YAML
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


[2] #--------- Current Platform Detection Logic & UPI Limitations (Reference) ---------#
The operator determines the cluster's platform using step-by-step logic. However, there is a specific blind spot regarding User-Provisioned Infrastructure (UPI) Bare Metal deployments:

Step 1: Check for BareMetalHost Resources (Metal3)
The operator looks for active physical host objects (BareMetalHost). In a standard UPI deployment, because you provision the operating system and hardware manually outside of OpenShift, these BareMetalHost objects are not present.

Step 2: Parse the install-config.yaml ConfigMap
If no Bare Metal hosts are found, the operator falls back to reading the original installation configuration. It looks at the platform fields to see if a specific infrastructure provider (such as vsphere, aws, etc.) was declared.

The UPI Limitation: For UPI Bare Metal installations, the standard practice is to set the platform to none: {}.

Step 3: Fallback to "None"
If both checks yield nothing (no BareMetalHost objects exist, and the install-config platform is empty or set to none), the operator has no physical or API-driven indicators to know it is running on physical hardware. It must default to None.





