# DCC-BS CI Workflows

Reusable GitHub Actions (workflows + composite actions) to standardize CI for Node/Bun/Playwright frontends and GHCR Docker publishing across repositories.

## Contents
- `actions/`
  - `bump-version/` — Composite action to bump `package.json` semver, commit, tag, and push.
  - `node-bun-biome-playwright/` — Composite action to checkout, set up Node + Bun, run build, Biome, Playwright, and upload report.
- `.github/workflows/`
  - `frontend-ci.yml` — Reusable end‑to‑end Build & Test workflow (calls `node-bun-biome-playwright`).
  - `publish-docker.yml` — Reusable Docker publish workflow for GHCR (calls `bump-version`).

## Usage

Pin to the major version `v1` for safe updates.

### Frontend CI (Build & Test)

```yaml
name: Build & Test
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  ci:
    uses: DCC-BS/ci-workflows/.github/workflows/frontend-ci.yml@v1
    with:
      node_version: '24.x'
      working_directory: '.'
      run_biome: true
      run_playwright: true
      install_method: 'bun'           # 'bun' | 'npm' | 'pnpm' | 'yarn'
      install_command: ''             # optional override; default per install_method
      build_command: 'bun run build'
      test_command: 'bunx playwright test'
      artifact_name: 'playwright-report'
      artifact_retention_days: 30
```

### Publish Docker Image (GHCR)

Requires the caller workflow to inherit `secrets` so the `GITHUB_TOKEN` is available to the called workflow for tagging and pushing.

```yaml
name: Build and Publish Docker Image
on:
  workflow_dispatch:
    inputs:
      version_bump:
        description: Version bump type
        required: true
        default: patch
        type: choice
        options: [ major, minor, patch ]

permissions:
  contents: write
  packages: write

jobs:
  publish:
    uses: DCC-BS/ci-workflows/.github/workflows/publish-docker.yml@v1
    secrets: inherit
    with:
      release_type: ${{ inputs.version_bump }}   # major|minor|patch
      registry: ghcr.io
      image_name: ghcr.io/${{ github.repository }}
      context: .
      dockerfile: ./Dockerfile
      platforms: linux/amd64,linux/arm64
      push: true
```

## Versioning
- Tagged releases follow SemVer (e.g., `v1.0.0`).
- Consumers should pin to the major tag (e.g., `@v1`) to receive compatible improvements.
- Breaking changes will result in a new major tag (e.g., `v2`).

## Releasing (one‑time bootstrap for this repo)
1. Create the public repository `DCC-BS/ci-workflows` on GitHub.
2. Push this directory as the repository content (from within `ci-workflows` folder):
   ```bash
   git init
   git checkout -b main
   git add .
   git commit -m "feat: initial reusable CI/CD workflows and actions"
   git remote add origin git@github.com:DCC-BS/ci-workflows.git
   git push -u origin main
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. Consumers can then reference `DCC-BS/ci-w​orkflows@v1` as shown above.