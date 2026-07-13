FROM quay.io/operator-framework/opm:v1.38.0

COPY clustersize-catalog /configs

EXPOSE 50051
# Questo è il comando corretto per i file-based catalog in questa versione
ENTRYPOINT ["/bin/opm", "serve", "/configs", "-p", "50051"]
