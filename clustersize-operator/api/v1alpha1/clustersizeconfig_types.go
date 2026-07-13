package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ClusterSizeConfigSpec defines the desired state of ClusterSizeConfig
type ClusterSizeConfigSpec struct {
	// CheckInterval defines how frequently the operator re-evaluates cluster metrics and ships UDP payloads (e.g., "30s", "5m").
	CheckInterval string `json:"check_interval"`

	// RemoteIp specifies the target destination IPv4 address of the remote VM telemetry collector receiver.
	RemoteIp string `json:"remote_ip"`

	// RemoteUdpPort specifies the destination network UDP socket port on the remote VM receiver listening for payload streams.
	RemoteUdpPort int `json:"remote_udp_port"`

	// Secret points to the Name of the Corev1 Secret inside the namespace containing the mandatory 'HASH_SALT' cryptographic key.
	Secret string `json:"secret"`

	// Suspend flips the operational state of the controller loop. When set to true, active collection deployments are completely torn down.
	// +optional
	Suspend bool `json:"suspend,omitempty"`

        // LogMaxRotations sets the maximum number of historical backup log archive files to retain.
	// +optional
	// +kubebuilder:default=10
	LogMaxRotations int `json:"log_max_rotations,omitempty"`

	// LogMaxSizeCcBytes defines the hard file-size cap (in bytes) before triggering a rotation split.
	// +optional
	// +kubebuilder:default=50000
	LogMaxSizeBytes int `json:"log_max_size_bytes,omitempty"`
}

type ClusterSizeConfigStatus struct {
	Phase            string `json:"phase,omitempty"`
	MonitoringActive bool   `json:"monitoringActive"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

type ClusterSizeConfig struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ClusterSizeConfigSpec   `json:"spec,omitempty"`
	Status ClusterSizeConfigStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

type ClusterSizeConfigList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ClusterSizeConfig `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ClusterSizeConfig{}, &ClusterSizeConfigList{})
}
