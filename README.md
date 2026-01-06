# DCC-BS CI Workflows

Reusable GitHub Actions (workflows + composite actions) to standardize CI for Node/Bun/Playwright frontends and GHCR Docker publishing across repositories.

## Contents
- `actions/`
  - `bump-version/` — Composite action to bump `package.json` semver, commit, tag, and push.
  - `node-bun-biome-playwright/` — Composite action to checkout, set up Node + Bun, run build, Biome, Playwright, and upload report.
- `.github/workflows/`
  - `frontend-ci.yml` — Reusable end‑to‑end Build & Test workflow (calls `node-bun-biome-playwright`).
  - `python-backend-ci.yml` — Reusable uv-based backend checks + matrix runner.
  - `publish-docker.yml` — Reusable Docker publish workflow for GHCR (calls `bump-version`).
  - `npm-publish.yml` — Reusable workflow to bump, build, and publish npm packages.

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

### Python Backend CI

Reusable workflow for Python repositories that use `uv` to manage dependencies. It runs quality checks and, optionally, a Python-version matrix for tests and type checking.

- `python_versions` — JSON array passed to the test matrix (default `["3.12"]`)
- `quality_python_version` — Python version for the quality job (default `3.12`)
- `check_command` — command executed in the quality job (default `make check`)
- `test_command` — optional command; step runs only when set
- `typecheck_command` — optional command; step runs only when set
- `uv_version` and `working_directory` allow further customization

Example usage:

```yaml
name: Main
on:
  push:
    branches: [ main ]
  pull_request:
    types: [ opened, synchronize, reopened, ready_for_review ]

jobs:
  backend-ci:
    uses: DCC-BS/ci-workflows/.github/workflows/python-backend-ci.yml@v1
    with:
      python_versions: '["3.10","3.11","3.12","3.13"]'
      quality_python_version: "3.12"
      check_command: "make check"
      test_command: "uv run pytest tests"
      typecheck_command: "uv run basedpyright"
```

### Publish Docker Image (GHCR)

Requires the caller workflow to inherit `secrets` so the `GITHUB_TOKEN` is available to the called workflow for tagging and pushing.

- `version_project_type` — pass `python` to bump `pyproject.toml` via `uv` (default `node`)
- `version_uv_version` — override the `uv` release used when `version_project_type == python`

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
      version_project_type: "python"             # or "node"
      version_uv_version: "0.9.14"
      registry: ghcr.io
      image_name: ghcr.io/${{ github.repository }}
      context: .
      dockerfile: ./Dockerfile
      platforms: linux/amd64,linux/arm64
      push: true
```

### Bump Version Action

`actions/bump-version` now supports both Node (Nuxt) and Python projects. Set the `project_type` input to `node` (default) or `python`; when `python`, the action uses `uv version --bump` and commits `pyproject.toml`. Consumers can also override the `uv_version` input if they require a specific release.

### Publish Package to NPM

Reusable workflow to build, version, and publish a package using Bun + npm tooling. Requires a secret `NPM_TOKEN` with publish permissions for the configured registry.

- `version_type` — semantic bump applied via `npm version` (default `patch`)
- `node_version`, `registry_url`, `bun_version` — runtime setup knobs
- `install_command`, `build_command`, `prepack_command`, `publish_command` — override/disable individual lifecycle steps by setting the value you need (use `''` to skip)

Example usage:

```yaml
name: Publish Package
on:
  workflow_dispatch:
    inputs:
      version_type:
        description: Version increment type
        type: choice
        options: [ patch, minor, major ]
        default: patch

jobs:
  publish:
    uses: DCC-BS/ci-workflows/.github/workflows/npm-publish.yml@v1
    secrets: inherit        # make sure NPM_TOKEN is defined for the caller repo
    with:
      version_type: ${{ inputs.version_type }}
      registry_url: https://npm.pkg.github.com
      install_command: bun install
      build_command: bun generate
      prepack_command: bun run prepack
      publish_command: bun publish --access public
```

### LLM Documentation Auto-Updater

Reusable workflow to automatically check if a PR requires documentation updates using an LLM (OpenAI). If updates are needed, it creates a PR in the documentation repository.

- `doc_repo` — Owner/Name of the target documentation repository.
- `doc_path` — Path to markdown files in the doc repo.
- `pr_number` — (Optional) PR number to analyze. Inferred from context if missing.
- `source_repo` — (Optional) Source repository. Inferred from context if missing.
- `openai_model` — (Optional) Model to use (default: `gpt-4o`).
- `openai_base_url` — (Optional) Custom OpenAI Base URL.

Secrets required:
- `OPENAI_API_KEY`: API key for OpenAI.
- `GH_TOKEN`: Personal Access Token (PAT) with write access to the documentation repository.

Example usage:

```yaml
name: Sync Documentation
on:
  workflow_dispatch:
  # Or use pull_request types if auto-triggering is desired
  pull_request:
    types: [ closed ] # Example: Check after merge

jobs:
  check-docs:
    uses: DCC-BS/ci-workflows/.github/workflows/llm-doc-update.yml@v1
    with:
      doc_repo: "DCC-BS/documentation"
      doc_path: "docs/relevant-section"
      openai_model: "gpt-4-turbo"
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GH_TOKEN: ${{ secrets.DOC_REPO_PAT }}
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