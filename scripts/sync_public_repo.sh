#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sync_public_repo.sh [-r remote] [-b branch] [--tag]

  -r, --remote   Git remote to push to (default: idxr-public)
  -b, --branch   Branch name on the public repo (default: main)
  --tag          Create and push tag v<version> from pyproject.toml if missing
  -h, --help     Show this help message
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${PKG_DIR}/.." && pwd)"

REMOTE="${SYNC_REMOTE:-idxr-public}"
BRANCH="${SYNC_BRANCH:-main}"
PUSH_TAG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--remote)
      REMOTE="$2"
      shift 2
      ;;
    -b|--branch)
      BRANCH="$2"
      shift 2
      ;;
    --tag)
      PUSH_TAG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! git -C "${REPO_DIR}" remote get-url "${REMOTE}" >/dev/null 2>&1; then
  echo "Remote '${REMOTE}' is not configured in $(git -C "${REPO_DIR}" rev-parse --show-toplevel)." >&2
  exit 1
fi

REMOTE_URL="$(git -C "${REPO_DIR}" remote get-url "${REMOTE}")"
SRC_SHA="$(git -C "${REPO_DIR}" rev-parse HEAD)"

TMP_DIR="$(mktemp -d -t idxr-sync-XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

git init "${TMP_DIR}"
git -C "${TMP_DIR}" remote add origin "${REMOTE_URL}"

if git -C "${TMP_DIR}" ls-remote --exit-code origin "refs/heads/${BRANCH}" >/dev/null 2>&1; then
  git -C "${TMP_DIR}" fetch origin "${BRANCH}"
  git -C "${TMP_DIR}" checkout -b "${BRANCH}" "origin/${BRANCH}"
else
  git -C "${TMP_DIR}" checkout --orphan "${BRANCH}"
fi

rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '*.egg-info/' \
  "${PKG_DIR}/" "${TMP_DIR}/"

git -C "${TMP_DIR}" add .

if git -C "${TMP_DIR}" diff --quiet --cached; then
  echo "No changes detected for public repo."
else
  git -C "${TMP_DIR}" commit -m "Sync idxr from ${SRC_SHA}"
  git -C "${TMP_DIR}" push --force-with-lease origin "${BRANCH}"
fi

if [[ "${PUSH_TAG}" -eq 1 ]]; then
  VERSION="$(python - <<'PY'
import pathlib, tomllib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
print(data["project"]["version"])
PY
)"
  TAG="v${VERSION}"
  if git -C "${TMP_DIR}" ls-remote --exit-code --tags origin "${TAG}" >/dev/null 2>&1; then
    echo "Tag ${TAG} already exists on ${REMOTE}; skipping tag push."
  else
    if ! git -C "${TMP_DIR}" rev-parse HEAD >/dev/null 2>&1; then
      echo "Cannot tag because no commits exist on ${BRANCH} yet." >&2
      exit 1
    fi
    git -C "${TMP_DIR}" tag -a "${TAG}" -m "idxr ${VERSION}"
    git -C "${TMP_DIR}" push origin "${TAG}"
  fi
fi

echo "Public repo synchronized (${REMOTE} -> ${BRANCH})."
