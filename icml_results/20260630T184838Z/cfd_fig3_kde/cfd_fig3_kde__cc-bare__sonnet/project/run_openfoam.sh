#!/bin/bash
# Run OpenFOAM 8 buoyantSimpleFoam Boussinesq simulation in Docker.
# Mounts the run/ directory into the container.

set -e

PROJECT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$PROJECT/run"
OF_IMG="openfoam/openfoam8-paraview56"

echo "=== Meshing and running in Docker (OF8) ==="

docker run --platform linux/amd64 --rm \
  -v "$RUN_DIR":/case \
  --entrypoint /bin/bash \
  "$OF_IMG" \
  -c "
set -e
. /opt/openfoam8/etc/bashrc

cd /case

echo '--- blockMesh ---'
blockMesh 2>&1 | tee logs/log_blockMesh

echo '--- surfaceFeatureExtract ---'
surfaceFeatureExtract 2>&1 | tee logs/log_features

echo '--- snappyHexMesh ---'
snappyHexMesh -overwrite 2>&1 | tee logs/log_snappy

echo '--- checkMesh ---'
checkMesh 2>&1 | tee logs/log_check

echo '--- copy 0.org to 0 ---'
rm -rf 0
cp -r 0.org 0

echo '--- renumberMesh ---'
renumberMesh -overwrite 2>&1 | tee logs/log_renumber

echo '--- buoyantSimpleFoam ---'
buoyantSimpleFoam 2>&1 | tee logs/log_solver

echo '--- postProcess writeCellVolumes ---'
postProcess -latestTime -func writeCellVolumes 2>&1 | tee logs/log_postV

echo '=== Done ==='
"

echo "OpenFOAM run complete."
