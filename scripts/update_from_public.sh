#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/update_from_public.sh [-r remote] [-b branch] [--archive]
#
# This script pulls the latest contents of the public idxr repository and
# synchronizes them into the local indexer/ directory so the private repo
# stays aligned.
#
# Steps performed:
#   1. Determine the remote/branch to fetch (defaults: idxr-public/main).
#   2. Fetch the remote branch into the local Git repository.
#   3. Export the branch into a temporary directory.
#   4. Rsync the exported files into indexer/ (preserving doc/mkdocs layout).
#   5. Report the resulting status so you can review and commit.

usage() {
  cat <<'EOF'
Usage: update_from_public.sh [-r remote] [-b branch] [--archive]

  -r, --remote   Remote name of the public repo (default: idxr-public)
  -b, --branch   Branch to pull from the public repo (default: main)
  --archive      Use git archive instead of rsync (produces tarball output)
  -h, --help     Show this help message
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${PKG_DIR}/.." && pwd)"

REMOTE="${UPDATE_REMOTE:-idxr-public}"
BRANCH="${UPDATE_BRANCH:-main}"
USE_ARCHIVE=0

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
    --archive)
      USE_ARCHIVE=1
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

if [[ -n "$(git -C "${REPO_DIR}" status --porcelain)" ]]; then
  echo "Working tree has uncommitted changes. Commit or stash before syncing." >&2
  exit 1
fi

if ! git -C "${REPO_DIR}" remote get-url "${REMOTE}" >/dev/null 2>&1; then
  echo "Remote '${REMOTE}' is not configured. Use 'git remote add ${REMOTE} <url>' first." >&2
  exit 1
fi

echo "Fetching ${REMOTE}/${BRANCH} ..."
git -C "${REPO_DIR}" fetch "${REMOTE}" "${BRANCH}"

TMP_DIR="$(mktemp -d -t idxr-public-XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "Exporting ${REMOTE}/${BRANCH} ..."

if [[ "${USE_ARCHIVE}" -eq 1 ]]; then
  git -C "${REPO_DIR}" archive "${REMOTE}/${BRANCH}" | tar -x -C "${TMP_DIR}"
else
  git -C "${REPO_DIR}" worktree add --detach "${TMP_DIR}" "${REMOTE}/${BRANCH}"
  trap 'rm -rf "${TMP_DIR}"; git -C "${REPO_DIR}" worktree prune' EXIT
fi

echo "Synchronizing into indexer/ ..."
rsync -a --delete \
  --exclude '.git' \
  --exclude '.github/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '*.egg-info/' \
  "${TMP_DIR}/" "${PKG_DIR}/"

if [[ "${USE_ARCHIVE}" -ne 1 ]]; then
  git -C "${REPO_DIR}" worktree prune
fi

echo "Update complete. Review changes below:"
git -C "${REPO_DIR}" status -- indexer

echo "Remember to run 'git add indexer && git commit' once you're satisfied."
