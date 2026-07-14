FROM scratch

# Core bundle labels.
LABEL operators.operatorframework.io.bundle.mediatype.v1=registry+v1
LABEL operators.operatorframework.io.bundle.manifests.v1=manifests/
LABEL operators.operatorframework.io.bundle.metadata.v1=metadata/
LABEL operators.operatorframework.io.bundle.package.v1=clustersize
LABEL operators.operatorframework.io.bundle.channels.v1=test-channel
LABEL operators.operatorframework.io.bundle.channel.default.v1=test-channel
LABEL operators.operatorframework.io.metrics.builder=operator-sdk-v1.33.0
LABEL operators.operatorframework.io.metrics.mediatype.v1=metrics+v1
LABEL operators.operatorframework.io.metrics.project_layout=go.kubebuilder.io/v4

LABEL operatorframework.io.suggested-namespace="openshift-size-monitoring"
LABEL operatorframework.io.suggested-namespace-template="{\"apiVersion\":\"v1\",\"kind\":\"Namespace\",\"metadata\":{\"name\":\"openshift-size-monitoring\"}}"
# Copy files to locations specified by labels.
COPY bundle/manifests /manifests/
COPY bundle/metadata /metadata/
