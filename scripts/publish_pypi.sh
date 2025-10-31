#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${PKG_DIR}/.." && pwd)"

REMOTE="${PUBLISH_REMOTE:-origin}"

for tool in python twine; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "Missing required tool: ${tool}" >&2
    exit 1
  fi
done

if [[ -n "$(git -C "${REPO_DIR}" status --porcelain)" ]]; then
  echo "Working tree has uncommitted changes. Commit or stash before publishing." >&2
  exit 1
fi

VERSION="$(python - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
print(data["project"]["version"])
PY
)"

TAG="v${VERSION}"

cd "${PKG_DIR}"

rm -rf dist build *.egg-info

python -m build
twine check dist/*
twine upload dist/*

if git -C "${REPO_DIR}" rev-parse "${TAG}" >/dev/null 2>&1; then
  echo "Tag ${TAG} already exists; skipping tag creation."
else
  git -C "${REPO_DIR}" tag -a "${TAG}" -m "idxr ${VERSION}"
  git -C "${REPO_DIR}" push "${REMOTE}" "${TAG}"
fi

echo "Published idxr ${VERSION} to PyPI."
