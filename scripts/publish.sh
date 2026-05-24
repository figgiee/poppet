#!/usr/bin/env bash
# Build + publish poppet-mcp to PyPI.
#
# Usage:
#   scripts/publish.sh test    # publishes to TestPyPI
#   scripts/publish.sh prod    # publishes to real PyPI
#
# Requires TWINE_USERNAME=__token__ + TWINE_PASSWORD=<api token> in env,
# or a ~/.pypirc with [pypi]/[testpypi] sections.

set -euo pipefail

REPO=${1:-test}

cd "$(dirname "$0")/.."

# Clean stale artifacts so we don't accidentally upload an older wheel.
rm -rf build dist *.egg-info

python -m pip install --quiet --upgrade build twine

echo "Building wheel + sdist..."
python -m build --wheel --sdist

echo "Validating distributions..."
python -m twine check dist/*

case "$REPO" in
    test)
        echo "Uploading to TestPyPI..."
        python -m twine upload --repository testpypi dist/*
        echo
        echo "Verify install:"
        echo "  uvx --index-url https://test.pypi.org/simple/ poppet-mcp"
        ;;
    prod)
        echo "Uploading to PyPI..."
        python -m twine upload dist/*
        echo
        echo "Verify install:"
        echo "  uvx poppet-mcp"
        ;;
    *)
        echo "unknown target: $REPO (use 'test' or 'prod')" >&2
        exit 1
        ;;
esac
