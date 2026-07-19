#!/bin/bash

# exit immediately if a command exits with a non-zero status
set -e

# 1. Recupera la versione corrente dal Makefile (es. 2.0.50)
OLD_VER=$(grep -E "^VERSION \??=" Makefile | head -n 1 | awk -F'= ' '{print $2}' | tr -d '[:space:]')

if [ -z "$OLD_VER" ]; then
    echo "❌ Errore: Impossibile trovare la versione corrente nel Makefile."
    exit 1
fi

# 2. Estrae la base (2.0.) e l'ultimo numero (patch)
VERSION_BASE=$(echo "$OLD_VER" | awk -F. '{print $1"."$2"."}')
CURRENT_PATCH=$(echo "$OLD_VER" | awk -F. '{print $3}')

# 3. Calcola la nuova versione incrementando la patch di 1
NEW_PATCH=$((CURRENT_PATCH + 1))
NEW_VER="${VERSION_BASE}${NEW_PATCH}"

# 4. Calcola la versione ancora precedente (per upgrade_and_push.sh OLD_VER)
PREV_PATCH=$((CURRENT_PATCH - 1))
PREV_VER="${VERSION_BASE}${PREV_PATCH}"

echo "=================================================="
echo "📈 Incremento versione rilevato automatico:"
echo "   Versione precedente (OLD_VER reference):  $PREV_VER"
echo "   Versione corrente   (da sostituire):       $OLD_VER"
echo "   Nuova versione      (target):              $NEW_VER"
echo "=================================================="

# 5. Esecuzione delle SED sui file di configurazione
echo " -> Aggiornamento catalog.yaml..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" clustersize-catalog/catalog.yaml

echo " -> Aggiornamento kustomization manager..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" config/manager/kustomization.yaml

echo " -> Aggiornamento CSV base..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" config/manifests/bases/clustersize.clusterserviceversion.yaml

echo " -> Aggiornamento kustomization manifests..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" config/manifests/kustomization.yaml

echo " -> Aggiornamento stack di monitoraggio OpenShift..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" ../openshift-size-monitoring.yaml

# 6. Esecuzione della SED sul file Go (aggiunto per consistenza interna)
if [ -f "internal/controller/clustersizeconfig_controller.go" ]; then
    echo " -> Aggiornamento costante OperatorVersion nel codice Go..."
    sed -i "s/OperatorVersion = \"${OLD_VER}\"/OperatorVersion = \"${NEW_VER}\"/g" internal/controller/clustersizeconfig_controller.go
fi

echo " -> Aggiornamento Makefile..."
sed -i "s/${OLD_VER}/${NEW_VER}/g" Makefile

echo " -> Aggiornamento upgrade_and_push.sh (VERSIONE NEW e OLD)..."
sed -i "s/NEW_VER=\"${OLD_VER}\"/NEW_VER=\"${NEW_VER}\"/g" upgrade_and_push.sh
sed -i "s/OLD_VER=\"${PREV_VER}\"/OLD_VER=\"${OLD_VER}\"/g" upgrade_and_push.sh

echo "=================================================="
echo "✅ Allineamento completato con successo alla v${NEW_VER}!"
echo "Ora puoi lanciare ./upgrade_and_push.sh"
echo "=================================================="

grep -HRi "2.0." * 2>/dev/null | grep -vE "go.sum|go.mod|base64data|bundle|License, Version 2.0|1:-v2.0.18|falls back safely|cpu:|image tag|bump|Examples|.csv"
