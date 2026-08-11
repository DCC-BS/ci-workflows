# DCC-BS CI Workflows

Reusable GitHub Actions (workflows + composite actions) to standardize CI across
DCC-BS repositories. **v2 is mise-based**: every project is driven through
`mise run <task>`, and a single language-agnostic pipeline serves both frontends
and backends.

## v1 → v2

- **v2 (current, mise-based)** — projects provision `bun`/`node`/`python`/`uv`
  from their own `mise.toml` via the `setup-mise` action, and CI runs the
  standard tasks (`mise run install | check | test:unit | build`). The
  Python-version matrix is gone (single version from `mise.toml`).
- **v1 (frozen, make/bun-based)** — still available under the `@v1` tag for
  repositories that have not migrated yet. It will not receive new features.

New consumers should use **v2**. Existing consumers can move from `@v1` to `@v2`
once their repository ships a `mise.toml` (see the
[mise tooling standard](https://dcc-bs.github.io/documentation/dev-setup/mise)).

## Contents
- `actions/`
  - `setup-mise/` — Install mise and provision all tools from the project's `mise.toml` (cached). The single setup step for every workflow.
  - `bump-version/` — Composite action to bump `package.json`/`pyproject.toml` semver, commit, tag, and push.
- `.github/workflows/`
  - `ci.yml` — **The unified, language-agnostic CI pipeline** (recommended for all projects).
  - `frontend-ci.yml` — Thin wrapper around `ci.yml` with frontend defaults (build + e2e).
  - `python-backend-ci.yml` — Thin wrapper around `ci.yml` with backend defaults (check + test).
  - `publish-docker.yml` — Reusable Docker publish workflow for GHCR (calls `bump-version`).
  - `npm-publish.yml` — Reusable workflow to bump, build, and publish npm packages.

## Usage

Pin to the major version `v2` for safe updates.

### Unified CI (`ci.yml`) — recommended

Runs `setup-mise` → `mise run install` → `check` → `test:unit` → (optional) `build` / `e2e`.
Works identically for Nuxt frontends and FastAPI backends because every project
exposes the same `mise run` task names. `APP_MODE=ci` is set automatically so
that secret-dependent steps (e.g. `varlock scan` inside `check`) run without a
`pass-cli` login.

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ci:
    uses: DCC-BS/ci-workflows/.github/workflows/ci.yml@v2
    with:
      working_directory: '.'
      # install/check/test:unit run by default; build and e2e are opt-in:
      run_build: true        # frontends typically enable this
      run_e2e: true          # enables Playwright; set upload_playwright_report too
      upload_playwright_report: true
```

Inputs (all optional): `working-directory`, `run-install`/`run-check`/`run-test`/
`run-build`/`run-e2e` (booleans), and `install-command`/`check-command`/
`test-command`/`build-command`/`e2e-command` (default to the matching
`mise run <task>`). `run-build` and `run-e2e` default to `false` since not every
project has a build or e2e task.

### Python Backend CI

Thin wrapper around `ci.yml` with backend defaults (install → check → test; no
build, no e2e). Tool versions come from the project's `mise.toml`, so there is no
version matrix.

```yaml
name: Main
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  backend-ci:
    uses: DCC-BS/ci-workflows/.github/workflows/python-backend-ci.yml@v2
    with:
      check_command: "mise run check"   # default
      test_command: "mise run test:unit"     # default
```

`APP_MODE=ci` is set by the pipeline so `varlock scan` (run inside `check`) works
without a `pass-cli` login.

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
    uses: DCC-BS/ci-workflows/.github/workflows/publish-docker.yml@v2
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
    uses: DCC-BS/ci-workflows/.github/workflows/npm-publish.yml@v2
    secrets: inherit        # make sure NPM_TOKEN is defined for the caller repo
    with:
      version_type: ${{ inputs.version_type }}
      registry_url: https://npm.pkg.github.com
      install_command: bun install
      build_command: bun generate
      prepack_command: bun run prepack
      publish_command: bun publish --access public
```

### Publish Package to PyPI

Reusable workflow to build, tag, and publish a package using `uv`. Requires `id-token: write` permission for Trusted Publishing (or configured secrets if not using OIDC, though this workflow assumes Trusted Publishing by default for permissions).

- `python_version` — Python version to use (default: `"3.12"`)
- `uv_version` — Version of uv to install (default: `"latest"`)
- `create_release_tag` — Whether to create and push a git tag based on the version (default: `true`)
- `install_command`, `build_command`, `publish_command` — Override default commands.

Example usage:

```yaml
name: Publish to PyPI
on:
  workflow_dispatch:

jobs:
  publish:
    uses: DCC-BS/ci-workflows/.github/workflows/pypi-publish.yml@v1
    permissions:
      id-token: write
      contents: write
    with:
      python_version: "3.12"
      create_release_tag: true
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
    uses: DCC-BS/ci-workflows/.github/workflows/llm-doc-update.yml@v2
    with:
      doc_repo: "DCC-BS/documentation"
      doc_path: "docs/relevant-section"
      openai_model: "gpt-4-turbo"
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      GH_TOKEN: ${{ secrets.DOC_REPO_PAT }}
```

## Versioning
- Tagged releases follow SemVer (e.g., `v2.0.0`).
- Consumers should pin to the major tag `@v2` to receive compatible improvements.
- `@v1` is frozen (make/bun-based) and only receives critical fixes; migrate to `@v2`.
- Breaking changes will result in a new major tag (e.g., `v3`).

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