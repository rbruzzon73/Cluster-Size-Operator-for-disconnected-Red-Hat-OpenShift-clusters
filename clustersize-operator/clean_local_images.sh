#!/usr/bin/env bash

# Definisci la versione da ripulire
VERSION="$1"
REGISTRY="ghcr.io/rbruzzon73"

echo "=========================================================="
echo " Clearing Podman Local Images for clustersize:${VERSION} "
echo "=========================================================="

# Elenco delle immagini associate al progetto
IMAGES=(
    "${REGISTRY}/clustersize-operator:${VERSION}"
    "${REGISTRY}/clustersize-bundle:${VERSION}"
    "${REGISTRY}/clustersize-bundle:${VERSION}-amd64"
    "${REGISTRY}/clustersize-bundle:${VERSION}-s390x"
    "${REGISTRY}/clustersize-catalog:${VERSION}"
    "${REGISTRY}/clustersize-catalog:${VERSION}-amd64"
    "${REGISTRY}/clustersize-catalog:${VERSION}-s390x"
)

for img in "${IMAGES[@]}"; do
    # if podman image exists "$img"; then
         echo "--> Removing local image: $img"
         podman rmi -f "$img"
    # else
    #     echo "--> Image $img does not exist locally. Skipping."
    # fi
done

echo "----------------------------------------------------------"
echo "Cleaning up dangling/orphan layers to free space..."
podman image prune -f

echo "Done! You can now rerun your upgrade pipeline safely."
