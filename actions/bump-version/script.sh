#!/usr/bin/env bash
set -euo pipefail

RELEASE_TYPE="${1:-}"
if [[ -z "${RELEASE_TYPE}" ]]; then
  echo "Error: Version bump type not specified" >&2
  echo "Usage: script.sh <major|minor|patch>" >&2
  exit 1
fi

# Ensure we are in a git repo with package.json
if [[ ! -f package.json ]]; then
  echo "Error: package.json not found in current directory: $(pwd)" >&2
  exit 1
fi

# Bump version in package.json without auto-tagging
npm version "${RELEASE_TYPE}" --no-git-tag-version
NEW_VERSION="$(jq -r .version package.json)"
echo "New version: ${NEW_VERSION}"

# Commit, tag and push
git add package.json
git commit -m "chore: bump version to ${NEW_VERSION}"
git tag "v${NEW_VERSION}"
git push origin HEAD --tags

# Emit outputs
echo "new_version=${NEW_VERSION}"
echo "tag_name=v${NEW_VERSION}"


