import os

# Configuration
MAX_DIFF_CHARS = 40000
MAX_DOC_CONTEXT_CHARS = 50000
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
PR_BRANCH_PREFIX = "doc-update-pr"
# Upper bound on brand-new pages proposed per run, to cap runaway creation.
MAX_NEW_DOCS = 5
# Sentinel the update model returns when a doc file should be deleted entirely.
DELETE_FILE_MARKER = "__DELETE_FILE__"
DIFF_FILTER_PATTERNS: list[str] = [
    "**/*.py",
    "**/*.ts",
    "**/*.tsx",
    "**/*.vue",
    "**/*.json",
    "**/*.yaml",
    "pyproject.toml",
    ".env.example",
]

# Optional user-supplied instructions block. Rendered empty when no custom
# instructions were passed via the /documentation command.
CUSTOM_INSTRUCTIONS_TEMPLATE = """
User Instructions (highest priority — provided by the maintainer who triggered this update):
{custom_instructions}
"""

# Triage Prompts
TRIAGE_SYSTEM_PROMPT = (
    "You are a technical documentation assistant. You decide whether a code "
    "change requires an update to a specific documentation file. Answer "
    'precisely with only "YES" or "NO".'
)
TRIAGE_USER_PROMPT_TEMPLATE = """
You are a technical documentation assistant.
I have a git diff from a code PR and a markdown documentation file.
Determine if the changes in the code require an update to this specific documentation file.
{custom_instructions_section}

Conditions for documentation updates:
1. New functionality in the diff that is not documented
2. Removed functionality in the diff that is documented and should be removed
3. Updated functionality in the diff that is now outdated in the documentation
4. Currently undocumented functionality in the diff
5. Developer-Facing Only: Focus exclusively on changes that affect the public API, configuration, installation, or behavior as experienced by a developer using the library/app.
6. Ignore Internal Logic: No documentation updates needed for internal refactors, private helper functions, performance optimizations, or logic changes that do not alter the external interface or outcome.
7. User Instructions Override: If the User Instructions above explicitly ask for a change to this specific file (rewording, restructuring, removing references, or deleting the file entirely), answer "YES" even if the code diff alone would not require it.
8. Deletion counts as an update: if the functionality this file documents was fully removed, or the User Instructions request removing this file, answer "YES".

Note: the documentation content shown below may already include changes from earlier automated update rounds on an open documentation PR. Answer "NO" if the file already fully reflects the code changes and the User Instructions.

Special Case - Skill Frontmatter:
If the file's YAML frontmatter contains skillName, skillDescription, or skillParent, it is published as an installable skill for coding agents. An update is also needed if the code changes alter what this page covers such that its skillDescription is now inaccurate.

Special Case - VitePress Config (.vitepress/config.ts or .vitepress/config.mts):
If the file is a VitePress config file, check if the sidebar navigation needs to be updated based on:
- New documentation pages being added that should appear in the sidebar
- Existing pages being removed or renamed that are referenced in the sidebar
- Reorganization of documentation structure requiring sidebar updates

PR Description:
{pr_description}

Git Diff:
{diff_text}

Documentation File ({path}):
{content}

Does this specific documentation file need to be updated?
Answer with just "YES" or "NO".
"""

# Update Prompts
UPDATE_SYSTEM_PROMPT = "You are an expert Technical Writer and Software Engineer specialized in VitePress documentation. Your task is to synchronize a specific Markdown file with recent code changes while leveraging VitePress-specific features for a premium developer experience."
UPDATE_USER_PROMPT_TEMPLATE = """
Role
You are an expert Technical Writer and Software Engineer specialized in VitePress documentation. Your task is to update a specific Markdown file to reflect recent code changes.

Input Data:
1. Target File to Update: {target_path}
2. Current Content of {target_path}:
---
{target_content}
---
3. PR Description:
{pr_description}

4. Git Diff (Code Changes):
{diff_text}

5. Ambient Context (Other files being updated in this session):
{ambient_context}
{custom_instructions_section}

Objectives:
1. Visibility Filtering:
- Focus exclusively on changes affecting the public API, configuration, installation, or behavior.
- Ignore internal refactors or private logic that doesn't alter the external interface.

2. Update Logic for {target_path}:
- Handle Removals: If functionality is removed in the diff, delete the corresponding documentation.
- Handle Changes: Update behavior, signatures, or configuration to reflect the current state.
- Handle Additions: Add new public-facing features or parameters if they belong in this specific file.
- Handle Whole-File Deletion: If this entire file should no longer exist (the functionality it documents was fully removed, or the User Instructions explicitly request deleting it), respond with exactly `__DELETE_FILE__` and nothing else.
- PREVENT DUPLICATION: Use the 'Ambient Context' to see what other files are being updated. If a change more naturally belongs in one of those files, do NOT document it here.
- Preserve unrelated content and tone.
- Iterative Updates: The current content may already include changes from earlier automated update rounds on an open documentation PR. Apply the User Instructions and code changes ON TOP of the current content; do not undo earlier changes unless instructed. If the file already fully reflects everything, return the current content unchanged.

VitePress Guidelines:
- Preserve Frontmatter.
- Use Custom Containers (::: info, ::: tip, etc.) and Code Groups.
- Do not use Badges for new features.

Special Case - Skill Frontmatter:
Some markdown files expose their content as installable "skills" for coding agents via YAML frontmatter. These properties drive skill generation:
- skillName: the skill (or sub-skill) identifier.
- skillDescription: a one-line summary of what the skill covers, shown to coding agents.
- skillParent: links a child sub-skill file to its parent skill (set on the child file).
When a file already contains any of these properties, check whether the code changes meaningfully alter what the skill covers (its scope, the API/behavior it documents). If so, update skillDescription so it still accurately summarizes the page's content. Do NOT add skill frontmatter to files that do not already have it, do NOT rename skillName or skillParent, and keep all other frontmatter intact.

Special Case - VitePress Config (.vitepress/config.ts or .vitepress/config.mts):
If the target file is a VitePress config file, it contains the sidebar navigation configuration.
Update the sidebar when:
- New documentation pages are added and need to appear in the navigation
- Existing pages are removed or renamed and their sidebar entries need updating
- Documentation structure changes require reorganization of the sidebar items
Preserve the existing TypeScript structure and only modify the sidebar/nav sections as needed.
The config.ts file must remain a TypeScript file. Do not wrap the content inside markdown.

Constraints:
- Return ONLY the full, updated content for {target_path}.
- No JSON, no preamble, no meta-commentary, no triple-backtick wrappers around the whole response.
- Just the raw file content.
- For Markdown files: Strictly follow VitePress-flavored Markdown. Ensure all code blocks are wrapped in triple backticks (```).
- For TypeScript config files: Preserve the existing code structure, imports, and formatting.
- Preserve Symbols: Do NOT remove backticks (`) or any other syntax-specific characters. All code examples must remain inside their respective code blocks.
- No Speculation: Only document what is explicitly supported by the code changes in the diff.
- No Meta-Commentary: The response must not contain explanations, reasoning, or "I have updated the files..." messages.
- Pure Output: The output must be the updated content of the files only.

---
Provide the full updated content for {target_path}:
"""

# Summary Prompts (posted back as a comment on the source PR)
SUMMARY_SYSTEM_PROMPT = (
    "You are a documentation assistant summarizing automated documentation "
    "changes for a pull request comment. Write concise GitHub-flavored "
    "Markdown."
)
SUMMARY_USER_PROMPT_TEMPLATE = """
An automated documentation update was generated for a documentation site based on a code PR.

Summarize, in a short GitHub PR comment, what was changed in the documentation and why.

Guidelines:
- Use a brief bullet list, one bullet per updated file: `path` — what changed. Mark deleted files as deleted.
- Be specific and factual; only describe changes supported by the data below.
- If the user instructions raise something the diff does not clearly resolve, add a short "Questions" section asking for clarification.
- Do NOT include a link to the documentation PR; it is added separately.
- No preamble like "Here is the summary" and no "Documentation updated" header; a header is added separately.
- Do NOT repeat or quote text from the user instructions (they may contain quoted earlier bot comments).
{custom_instructions_section}
PR Description:
{pr_description}

Git Diff (Code Changes):
{diff_text}

Updated documentation files: {updated_paths}

Doc changes (unified diffs):
{doc_diffs}
"""

# Propose-New-Pages Prompts
# Decide whether the diff introduces functionality that no existing page covers
# and therefore warrants an entirely new documentation page.
PROPOSE_NEW_DOCS_SYSTEM_PROMPT = (
    "You are a technical documentation architect. You decide whether a code "
    "change introduces functionality not covered by any existing documentation "
    "page and therefore warrants an entirely new page. You respond only with JSON."
)
PROPOSE_NEW_DOCS_USER_PROMPT_TEMPLATE = """
You are planning documentation changes for a VitePress site.

A code PR introduced changes. Below you have the git diff, the PR description,
the list of existing documentation pages (paths), and the VitePress config
(sidebar/nav structure).
{custom_instructions_section}

Decide whether the code changes introduce public-facing functionality (a new
feature, module, command, endpoint, or configuration surface) that does NOT
belong on any existing page and is significant enough to deserve its own new
documentation page.

Rules:
- Propose a new page ONLY when the topic does not fit an existing page. If an
  existing page should merely be extended, do NOT propose a new file for it.
- Every proposed path MUST live under the documentation directory "{doc_path}",
  use a URL-friendly kebab-case filename, and end with ".md".
- Do NOT propose a path that already exists in the list below.
- Base every proposal strictly on the diff/PR; do not speculate.
- Propose at most {max_new_docs} new pages. Prefer none over a weak fit.
- If the User Instructions explicitly request a new page, honor that.

Return ONLY a JSON array (no prose, no code fences). Each element:
{{"path": "<path under {doc_path} ending in .md>", "title": "<page title>", "reason": "<one line why a new page is warranted>"}}
If no new page is warranted, return exactly: []

PR Description:
{pr_description}

Git Diff:
{diff_text}

Existing documentation pages:
{existing_paths}

VitePress config:
{vitepress_config}
"""

# Create-New-Page Prompts
CREATE_DOC_SYSTEM_PROMPT = (
    "You are an expert Technical Writer specialized in VitePress documentation. "
    "You write a brand-new documentation page from scratch based on code changes."
)
CREATE_DOC_USER_PROMPT_TEMPLATE = """
Role
You are an expert Technical Writer specialized in VitePress documentation.
Write a brand-new documentation page.

New Page Path: {target_path}
Intended Page Title: {title}
Why this page exists: {reason}

PR Description:
{pr_description}

Git Diff (Code Changes):
{diff_text}

Ambient Context (existing documentation pages, for style and cross-references):
{ambient_context}
{custom_instructions_section}

Objectives:
- Document ONLY the public-facing functionality introduced by the diff that
  belongs on this page. Do not speculate beyond the code changes.
- Match the tone, structure, and conventions of the existing pages shown above.
- Start with a VitePress frontmatter block only if existing pages use one;
  otherwise start with a top-level "# {title}" heading.
- Use VitePress-flavored Markdown: custom containers (::: info, ::: tip), code
  groups, and fenced code blocks with language tags.
- Do NOT add skill frontmatter (skillName/skillDescription/skillParent).

Constraints:
- Return ONLY the raw Markdown content for {target_path}.
- No preamble, no meta-commentary, no triple-backtick wrapper around the whole response.

Provide the full content for {target_path}:
"""

# VitePress-Navigation Prompts
# Add sidebar/nav entries for newly created pages and fix entries for renamed or
# removed pages. The config file lives above the documentation subdirectory.
CONFIG_UPDATE_SYSTEM_PROMPT = (
    "You are an expert in VitePress site configuration. You update the sidebar "
    "and nav in a VitePress config file. You return only the raw TypeScript "
    "file content."
)
CONFIG_UPDATE_USER_PROMPT_TEMPLATE = """
Role
You maintain the navigation of a VitePress documentation site by editing its
config file.

Config File Path: {config_path}
Current Config Content:
---
{config_content}
---

{new_docs_section}
PR Description:
{pr_description}

Git Diff (Code Changes):
{diff_text}
{custom_instructions_section}

Objectives:
- Add sidebar/nav entries for the newly created pages listed above (if any),
  placing them in the most sensible existing section. Infer the correct link
  format (base path, no ".md" extension, leading slash) from the existing
  entries in this config.
- Update or remove sidebar/nav entries for pages that the diff renamed or removed.
- If no navigation change is warranted, return the config content unchanged.

Constraints:
- Preserve the existing TypeScript structure, imports, and formatting; only
  modify the sidebar/nav sections.
- The file must remain valid TypeScript. Do NOT wrap the content in markdown.
- Return ONLY the raw TypeScript file content. No markdown fences, no preamble.

Provide the full updated content for {config_path}:
"""
