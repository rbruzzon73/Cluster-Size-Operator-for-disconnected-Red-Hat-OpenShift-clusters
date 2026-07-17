package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ClusterSizeConfigSpec defines the desired state of ClusterSizeConfig
type ClusterSizeConfigSpec struct {
	// +kubebuilder:validation:Required
	CheckInterval string `json:"checkInterval"`

	LogMaxRotations int `json:"logMaxRotations,omitempty"`
	LogMaxSizeBytes int `json:"logMaxSizeBytes,omitempty"`

	// +kubebuilder:validation:Required
	RemoteIp string `json:"remoteIp"`

	// +kubebuilder:validation:Required
	RemoteUdpPort int `json:"remoteUdpPort"`

	// +kubebuilder:validation:Required
	Secret string `json:"secret"`

	Suspend bool `json:"suspend,omitempty"`

	// IsBareMetal specifies whether the cluster runs on raw physical hardware.
	// This parameter acts as a fallback for UPI bare metal configurations.
	// +kubebuilder:validation:Required
	IsBareMetal bool `json:"isBareMetal"`

	// SubscriptionServiceLevel dictates the contract service tier associated with the cluster.
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
