#!/usr/bin/env bash
set -euo pipefail

# Define explicit version matrices
OLD_VER="2.0.76"
NEW_VER="2.0.77"
NAMESPACE="openshift-size-monitoring"

# Ensure this line exists inside your upgrade_and_push.sh script:
sed -i "s/VERSION ?= ${OLD_VER}/VERSION ?= ${NEW_VER}/g" Makefile
sed -i "s/newTag: v${OLD_VER}/newTag: v${NEW_VER}/g" config/manager/kustomization.yaml

echo "=== 0. Regenerating deepcopy and OpenAPI manifest bindings ==="
make manifests
make bundle

echo "=== 1. Updating local file manifests from v${OLD_VER} to v${NEW_VER} ==="

# Update the Bundle CSV version references
CSV_FILE="bundle/manifests/clustersize.clusterserviceversion.yaml"
if [ -f "$CSV_FILE" ]; then
    sed -i "s/clustersize.v${OLD_VER}/clustersize.v${NEW_VER}/g" "$CSV_FILE"
    sed -i "s/version: ${OLD_VER}/version: ${NEW_VER}/g" "$CSV_FILE"
    sed -i "s/clustersize-operator:v${OLD_VER}/clustersize-operator:v${NEW_VER}/g" "$CSV_FILE"
    echo "✔ Successfully updated ${CSV_FILE}"
else
    echo "❌ Error: CSV file not found at ${CSV_FILE}" && exit 1
fi

# Update the main compilation script version variable
if [ -f "build_and_push.sh" ]; then
    sed -i "s/VERSION=\"v${OLD_VER}\"/VERSION=\"v${NEW_VER}\"/g" "build_and_push.sh"
    echo "✔ Successfully updated build_and_push.sh"
fi

# Update the File-Based Catalog database layout configuration
CATALOG_FILE="clustersize-catalog/catalog.yaml"
if [ -f "$CATALOG_FILE" ]; then
    sed -i "s/clustersize.v${OLD_VER}/clustersize.v${NEW_VER}/g" "$CATALOG_FILE"
    sed -i "s/version: ${OLD_VER}/version: ${NEW_VER}/g" "$CATALOG_FILE"
    sed -i "s/clustersize-bundle:v${OLD_VER}/clustersize-bundle:v${NEW_VER}/g" "$CATALOG_FILE"
    echo "✔ Successfully updated ${CATALOG_FILE}"
else
    echo "❌ Error: Catalog database file not found at ${CATALOG_FILE}" && exit 1
fi

# Update the unified cluster blueprint manifest file
BLUEPRINT_FILE="../openshift-size-monitoring.yaml"
if [ -f "$BLUEPRINT_FILE" ]; then
    sed -i "s/v${OLD_VER}/v${NEW_VER}/g" "$BLUEPRINT_FILE"
    echo "✔ Successfully updated ${BLUEPRINT_FILE}"
fi

echo -e "\n=== 2. Compiling and Pushing Operator Binary & Bundle Layers ==="
./build_and_push.sh "v${NEW_VER}"

echo -e "\n=== 3. Re-compiling Multi-Arch Catalog Database Index ==="
podman manifest rm "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}" 2>/dev/null || true
podman manifest create "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}"

echo "-> Building amd64 layer (No-Cache)..."
podman build --no-cache --platform linux/amd64 --build-arg TARGETARCH=amd64 -t "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}-amd64" -f clustersize-catalog.Dockerfile .
podman manifest add "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}" "containers-storage:ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}-amd64"

echo "-> Building s390x layer (No-Cache)..."
podman build --no-cache --platform linux/s390x --build-arg TARGETARCH=s390x -t "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}-s390x" -f clustersize-catalog.Dockerfile .
podman manifest add "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}" "containers-storage:ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}-s390x"

echo "-> Pushing clean manifest index list to GitHub Packages..."
podman manifest push "ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}" "docker://ghcr.io/rbruzzon73/clustersize-catalog:v${NEW_VER}"

echo -e "\n=== 4. Executing Hard Flush on OpenShift Cluster ==="
oc delete subscription clustersize-operator-sub -n "$NAMESPACE" --ignore-not-found
oc delete catalogsource clustersize-catalog -n openshift-marketplace --ignore-not-found
oc delete csv --all -n "$NAMESPACE"

echo "-> Cycling background OLM lifecycle engine pods..."
oc delete pod -n openshift-operator-lifecycle-manager -l app=catalog-operator

echo "-> Applying fresh production configuration stacks..."
oc apply -f ../openshift-size-monitoring.yaml

echo -e "\n🚀 Upgrade complete! Track your rollout progress with:"
echo "oc get installplans -n $NAMESPACE"
echo "oc get pods -n $NAMESPACE"
