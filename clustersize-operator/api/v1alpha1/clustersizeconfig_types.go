package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ClusterSizeConfigSpec defines the desired state of ClusterSizeConfig
type ClusterSizeConfigSpec struct {
	// CheckInterval defines the frequency of telemetry checks. 
	// It supports pure numbers for hours (e.g., "10") or explicit units (e.g., "24h", "36000s", "90m").
	// +kubebuilder:validation:Required
	CheckInterval string `json:"checkInterval"`

	// LogMaxRotations defines the maximum number of log file rotations to keep.
	LogMaxRotations int `json:"logMaxRotations,omitempty"`

	// LogMaxSizeBytes defines the maximum size in bytes before the log file is rotated.
	LogMaxSizeBytes int `json:"logMaxSizeBytes,omitempty"`

	// RemoteIp is the IP address of the central aggregation server to send the UDP payload to.
	// +kubebuilder:validation:Required
	RemoteIp string `json:"remoteIp"`

	// RemoteUdpPort is the UDP port of the central aggregation server (e.g., 555).
	// +kubebuilder:validation:Required
	RemoteUdpPort int `json:"remoteUdpPort"`

	// Secret is the name of the Kubernetes Secret containing the cryptographic key (salt) for hashing.
	// If the specified Secret does not exist, the operator will automatically create it with a default value the first time.
	// +kubebuilder:validation:Required
	Secret string `json:"secret"`

	// Suspend allows temporarily suspending the monitoring cycle execution if set to true.
	Suspend bool `json:"suspend,omitempty"`

	// IsBareMetal specifies whether the cluster runs on native physical hardware.
	// This parameter acts as a fallback for bare metal UPI configurations.
	// +kubebuilder:validation:Optional
	// +kubebuilder:default=false
	IsBareMetal bool `json:"isBareMetal,omitempty"`

	// SubscriptionServiceLevel defines the contract level associated with the cluster (Premium or Standard).
	// +kubebuilder:validation:Required
	// +kubebuilder:validation:Enum=Premium;Standard
	SubscriptionServiceLevel string `json:"subscriptionServiceLevel"`
}

// ClusterSizeConfigStatus defines the observed state of ClusterSizeConfig
type ClusterSizeConfigStatus struct {
	// Add observed state status fields here if required by your controller
}

//+kubebuilder:object:root=true
//+kubebuilder:subresource:status

// ClusterSizeConfig is the Schema for the clustersizeconfigs API
type ClusterSizeConfig struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ClusterSizeConfigSpec   `json:"spec,omitempty"`
	Status ClusterSizeConfigStatus `json:"status,omitempty"`
}

//+kubebuilder:object:root=true

// ClusterSizeConfigList contains a list of ClusterSizeConfig
type ClusterSizeConfigList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ClusterSizeConfig `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ClusterSizeConfig{}, &ClusterSizeConfigList{})
}
