# DCC-BS CI Workflows

Reusable GitHub Actions (workflows + composite actions) to standardize CI across repositories: Node/Bun/Playwright frontends, uv-based Python backends, GHCR Docker and npm publishing, and LLM-assisted documentation updates.

## Contents
- `actions/`
  - `bump-version/` — Composite action to bump `package.json` semver, commit, tag, and push.
  - `node-bun-biome-playwright/` — Composite action to checkout, set up Node + Bun, run build, Biome, Playwright, and upload report.
  - `setup-python-env/` — Composite action to install Python and `uv` and sync dependencies.
- `.github/workflows/`
  - `frontend-ci.yml` — Reusable end‑to‑end Build & Test workflow (calls `node-bun-biome-playwright`).
  - `python-backend-ci.yml` — Reusable uv-based backend checks + matrix runner.
  - `publish-docker.yml` — Reusable Docker publish workflow for GHCR (calls `bump-version`).
  - `npm-publish.yml` — Reusable workflow to bump, build, and publish npm packages.
  - `llm-doc-update.yml` — Reusable workflow that drafts documentation updates from a PR diff using an LLM.
  - `llm-doc-update-conditional.yml` — Wrapper that runs `llm-doc-update.yml` when a PR is commented with `/documentation`.

## Usage

Pin to the major version `v9` for safe updates.

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

Beyond editing existing pages, the workflow can also **create entirely new pages** when the diff introduces functionality that no existing page covers, and it updates the VitePress config's sidebar/nav to link those new pages. The config file (`.vitepress/config.ts`/`.mts`) is fetched from above the `doc_path` subdirectory so navigation entries can be added, renamed, or removed.

- `doc_repo` — Owner/Name of the target documentation repository.
- `doc_path` — Path to markdown files in the doc repo.
- `pr_number` — PR number to analyze. The source repository is taken from `github.repository`.
- `openai_model` — (Optional) Model to use (default: `gpt-4o`).
- `openai_base_url` — (Optional) Custom OpenAI Base URL.
- `client_id` — GitHub App ID used to mint a short-lived installation token (see below).
- `custom_instructions` — (Optional) Free-text instructions injected into the LLM prompts. Usually set automatically from the `/documentation` comment (see below).

#### Triggering via PR comment

Use the conditional workflow (`llm-doc-update-conditional.yml`) on the `issue_comment` event. Comment on a PR with:

```
/documentation
```

You may append custom instructions in the same comment to steer the update and converse across runs:

```
/documentation "Make sure the documentation reflects the updated API."
```

The text after `/documentation` is added to a dedicated, high-priority section of the prompts. After running, the workflow comments back on the source PR with a summary of the documentation changes (and any clarifying questions) plus a link to the documentation PR. A single documentation PR is reused per source PR, so follow-up `/documentation` comments refine the same PR — enabling an iterative, comment-driven loop.

Secrets required:
- `OPENAI_API_KEY`: API key for OpenAI.
- `DOC_APP_PRIVATE_KEY`: Private key (PEM) of the GitHub App (see setup below).

#### Authentication: GitHub App

The workflow mints a short-lived installation token from a GitHub App, scoped to exactly the source and documentation repositories. One-time setup:

1. Create a GitHub App (org **Settings → Developer settings → GitHub Apps → New**). Disable Webhook.
2. Grant **Repository permissions**:
   - Contents: **Read and write**
   - Pull requests: **Read and write**
   - Issues: **Read and write** (used to post status comments back on the source PR)
3. **Install** the App on both the source repo(s) and the documentation repo. They must share the same owner/org — a single installation token cannot span owners.
4. Generate a **private key** (PEM) and note the **App ID**.
5. Store the private key as the `DOC_APP_PRIVATE_KEY` Actions secret, and pass the App ID via the `client_id` input.

> **Note:** For DCC-BS this is already configured at the **organization** level (Org → Settings → Secrets and variables → Actions): the App private key is the org secret `DOC_APP_PRIVATE_KEY` and the App ID is the org variable `DOC_client_id`. Consumer repos in the org can reference them directly (as in the examples below) without any per-repo setup.

Example usage (auto-trigger):

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
      client_id: ${{ vars.DOC_client_id }}
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      DOC_APP_PRIVATE_KEY: ${{ secrets.DOC_APP_PRIVATE_KEY }}
```

Example usage (`/documentation` comment trigger):

Use `llm-doc-update-conditional.yml` on the `issue_comment` event. It only runs when the comment starts with `/documentation`, and supplies the PR number from the comment's issue.

```yaml
name: Documentation on demand
on:
  issue_comment:
    types: [ created ]

jobs:
  docs:
    uses: DCC-BS/ci-workflows/.github/workflows/llm-doc-update-conditional.yml@v1
    with:
      doc_repo: "DCC-BS/documentation"
      doc_path: "docs/relevant-section"
      pr_number: ${{ github.event.issue.number }}
      client_id: ${{ vars.DOC_client_id }}
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      DOC_APP_PRIVATE_KEY: ${{ secrets.DOC_APP_PRIVATE_KEY }}
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