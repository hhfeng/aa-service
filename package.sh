#!/bin/bash
# Package aa-service source files for distribution.
# Includes: src, tests, config. Excludes: venv, dist, build, caches.

set -euo pipefail

VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
OUTFILE="aa-service-${VERSION}-src.tar.gz"

tar czf "$OUTFILE" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.so' \
    --exclude='*.egg' \
    --exclude='*.egg-info' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='env' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='uv.lock' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='.claude' \
    --exclude='.git' \
    --exclude='#*#' \
    --exclude='*~' \
    --exclude='*.tar.gz' \
    auth.py \
    config.py \
    jobs.py \
    main.py \
    ops.py \
    kbs.json \
    tests/ \
    pyproject.toml \
    requirements.txt \
    README.md \
    README-RELEASE.md \
    aa-service.spec \
    package.sh

echo "Packaged: $OUTFILE ($(du -h "$OUTFILE" | cut -f1))"
echo "Contents:"
tar tzf "$OUTFILE" | wc -l | xargs -I{} echo "  {} files"
