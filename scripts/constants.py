import os

# Configuration
MAX_DIFF_CHARS = 40000
MAX_DOC_CONTEXT_CHARS = 50000
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL")
PR_BRANCH_PREFIX = "doc-update-pr"
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

# Triage Prompts
TRIAGE_SYSTEM_PROMPT = "You are a helpful assistant."
TRIAGE_USER_PROMPT_TEMPLATE = """
You are a technical documentation assistant. 
I have a git diff from a code PR and a markdown documentation file.
Determine if the changes in the code require an update to this specific documentation file.

Conditions for documentation updates:
1. New functionality in the diff that is not documented
2. Removed functionality in the diff that is documented and should be removed
3. Updated functionality in the diff that is now outdated in the documentation
4. Currently undocumented functionality in the diff
5. Developer-Facing Only: Focus exclusively on changes that affect the public API, configuration, installation, or behavior as experienced by a developer using the library/app.
6. Ignore Internal Logic: No documentation updates needed for internal refactors, private helper functions, performance optimizations, or logic changes that do not alter the external interface or outcome.

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

Objectives:
1. Visibility Filtering:
- Focus exclusively on changes affecting the public API, configuration, installation, or behavior.
- Ignore internal refactors or private logic that doesn't alter the external interface.

2. Update Logic for {target_path}:
- Handle Removals: If functionality is removed in the diff, delete the corresponding documentation.
- Handle Changes: Update behavior, signatures, or configuration to reflect the current state.
- Handle Additions: Add new public-facing features or parameters if they belong in this specific file.
- PREVENT DUPLICATION: Use the 'Ambient Context' to see what other files are being updated. If a change more naturally belongs in one of those files, do NOT document it here.
- Preserve unrelated content and tone.

VitePress Guidelines:
- Preserve Frontmatter.
- Use Custom Containers (::: info, ::: tip, etc.) and Code Groups.
- Use Badges for new features.

Special Case - VitePress Config (.vitepress/config.ts or .vitepress/config.mts):
If the target file is a VitePress config file, it contains the sidebar navigation configuration.
Update the sidebar when:
- New documentation pages are added and need to appear in the navigation
- Existing pages are removed or renamed and their sidebar entries need updating
- Documentation structure changes require reorganization of the sidebar items
Preserve the existing TypeScript structure and only modify the sidebar/nav sections as needed.

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
