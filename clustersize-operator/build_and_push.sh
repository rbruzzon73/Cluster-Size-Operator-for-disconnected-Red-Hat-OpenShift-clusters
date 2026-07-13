#!/usr/bin/env bash
set -euo pipefail

REGISTRY="ghcr.io/rbruzzon73"

# 1. Dynamically read the version string passed by upgrade_and_push.sh
# If no argument is passed, it falls back safely to v2.0.18
VERSION="${1:-v2.0.18}"

# Standardize the version string to always include the 'v' prefix
if [[ ! "$VERSION" =~ ^v ]]; then
    VERSION="v${VERSION}"
fi

OP_IMG="$REGISTRY/clustersize-operator:$VERSION"
BUNDLE_IMG="$REGISTRY/clustersize-bundle:$VERSION"
CAT_IMG="$REGISTRY/clustersize-catalog:$VERSION"

echo "================================================================="
echo "  RUNNING MULTI-ARCH COMPILATION PIPELINE FOR TARGET: ${VERSION}"
echo "================================================================="

echo -e "\n=== 1. Building Cross-Architecture Operator Controller Images ==="
podman manifest rm "$OP_IMG" 2>/dev/null || true
podman manifest create "$OP_IMG"

# Build both architecture layers un-cached
podman build --no-cache --platform linux/amd64 --manifest "$OP_IMG" -f Dockerfile .
podman build --no-cache --platform linux/s390x --manifest "$OP_IMG" -f Dockerfile .
podman manifest push "$OP_IMG" "docker://$OP_IMG"


echo -e "\n=== 2. Building Multi-Arch Metadata Bundle Layer ==="
podman manifest rm "$BUNDLE_IMG" 2>/dev/null || true
podman manifest create "$BUNDLE_IMG"

# Build discrete bundle layers un-cached to capture your fresh CRD fields
echo "-> Building amd64 bundle layer..."
podman build --no-cache --platform linux/amd64 -t "$BUNDLE_IMG-amd64" -f bundle.Dockerfile .
podman manifest add "$BUNDLE_IMG" "containers-storage:$BUNDLE_IMG-amd64"

echo "-> Building s390x bundle layer..."
podman build --no-cache --platform linux/s390x -t "$BUNDLE_IMG-s390x" -f bundle.Dockerfile .
podman manifest add "$BUNDLE_IMG" "containers-storage:$BUNDLE_IMG-s390x"

podman manifest push "$BUNDLE_IMG" "docker://$BUNDLE_IMG"


echo -e "\n=== 3. Validating File-Based Catalog Structures Locally ==="
podman run --rm --platform linux/amd64 -v ./clustersize-catalog:/configs:z quay.io/operator-framework/opm:v1.38.0 validate /configs


echo -e "\n=== 4. Building File-Based Catalog Serving Layer ==="
podman manifest rm "$CAT_IMG" 2>/dev/null || true
podman manifest create "$CAT_IMG"

# Build catalog serving maps un-cached
podman build --no-cache --platform linux/amd64 --build-arg TARGETARCH=amd64 -t "$CAT_IMG-amd64" -f clustersize-catalog.Dockerfile .
podman manifest add "$CAT_IMG" "containers-storage:$CAT_IMG-amd64"

podman build --no-cache --platform linux/s390x --build-arg TARGETARCH=s390x -t "$CAT_IMG-s390x" -f clustersize-catalog.Dockerfile .
podman manifest add "$CAT_IMG" "containers-storage:$CAT_IMG-s390x"

podman manifest push "$CAT_IMG" "docker://$CAT_IMG"

echo -e "\n================================================================="
echo " >>> All multi-arch arrays compiled and pushed cleanly! <<<"
echo "=================================================================":
