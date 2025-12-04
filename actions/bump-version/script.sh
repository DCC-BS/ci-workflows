#!/usr/bin/env bash
set -euo pipefail

RELEASE_TYPE="${1:-}"
PROJECT_TYPE="${2:-node}"

if [[ -z "${RELEASE_TYPE}" ]]; then
  echo "Error: Version bump type not specified" >&2
  echo "Usage: script.sh <major|minor|patch> [node|python]" >&2
  exit 1
fi

case "${PROJECT_TYPE}" in
  node)
    if [[ ! -f package.json ]]; then
      echo "Error: package.json not found in current directory: $(pwd)" >&2
      exit 1
    fi

    npm version "${RELEASE_TYPE}" --no-git-tag-version
    NEW_VERSION="$(jq -r .version package.json)"
    git add package.json
    ;;
  python)
    if [[ ! -f pyproject.toml ]]; then
      echo "Error: pyproject.toml not found in current directory: $(pwd)" >&2
      exit 1
    fi

    uv version --bump "${RELEASE_TYPE}"
    NEW_VERSION="$(uv version --short)"
    if [[ -z "${NEW_VERSION}" ]]; then
      echo "Error: unable to read new version from uv" >&2
      exit 1
    fi
    if [[ -f uv.lock ]]; then
      uv lock
      git add uv.lock
    else
      echo "Warning: uv.lock not found; skipping lock update" >&2
    fi
    git add pyproject.toml
    ;;
  *)
    echo "Error: unsupported project type '${PROJECT_TYPE}'. Use node or python." >&2
    exit 1
    ;;
esac

echo "New version: ${NEW_VERSION}"

# Emit outputs
echo "new_version=${NEW_VERSION}"
echo "tag_name=v${NEW_VERSION}"


