import os
import sys
import argparse
import json
import subprocess
from github import Github, GithubException
from openai import OpenAI

# Configuration
MAX_DIFF_CHARS = 40000
MAX_DOC_CONTEXT_CHARS = 50000
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") # None by default, usage will handle it
PR_BRANCH_PREFIX = "doc-update-pr"

def get_local_git_diff(gh, repo_name, pr_number, repo_path="."):
    # We assume the current working directory is the source repo (checked out by actions/checkout)
    # We need to know the base branch to diff against.
    
    # Verify repo_path
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        print(f"Error: {repo_path} is not a valid git repository.")
        sys.exit(1)

    print(f"Resolving base branch for PR #{pr_number} in {repo_name}...")
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    base_ref = pr.base.ref
    
    print(f"Base branch is: {base_ref}")
    
    # Ensure we have the base ref fetched
    try:
        subprocess.check_call(["git", "fetch", "origin", base_ref], cwd=repo_path)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching base branch {base_ref}: {e}")
        sys.exit(1)

    print(f"Generating diff against origin/{base_ref}...")
    try:
        # Diff HEAD against the fetched base
        # Using -- . to verify we are diffing the current directory (repo)
        result = subprocess.run(
            ["git", "diff", f"origin/{base_ref}", "-W", "-U20", "--inter-hunk-context=15", "--", "."],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error generating git diff: {e.stderr}")
        sys.exit(1)

def get_doc_files(gh, doc_repo_name, doc_path):
    print(f"Fetching documentation files from {doc_repo_name}/{doc_path}...")
    repo = gh.get_repo(doc_repo_name)
    files_content = {}
    
    try:
        contents = repo.get_contents(doc_path)
    except GithubException as e:
        print(f"Error accessing path {doc_path} in {doc_repo_name}: {e}")
        sys.exit(1)

    while contents:
        file_content = contents.pop(0)
        if file_content.type == "dir":
            contents.extend(repo.get_contents(file_content.path))
        else:
            if file_content.path.endswith(".md"):
                # Decode content
                try:
                    files_content[file_content.path] = file_content.decoded_content.decode('utf-8')
                except Exception as e:
                    print(f"Skipping {file_content.path} due to decoding error: {e}")
                    
    return files_content

def call_openai_triage(client, diff_text, doc_files):
    print("Checking each documentation file for needed updates...")
    files_to_update = []
    
    for path, content in doc_files.items():
        print(f"  Checking {path}...")
        prompt = f"""
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

Git Diff:
{diff_text[:MAX_DIFF_CHARS]} 

Documentation File ({path}):
{content[:MAX_DOC_CONTEXT_CHARS]}

Does this specific documentation file need to be updated? 
Answer with just "YES" or "NO".
"""
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = response.choices[0].message.content.strip().upper()
        if "YES" in answer:
            print(f"    -> Update NEEDED for {path}")
            files_to_update.append(path)
        else:
            print(f"    -> No update needed for {path}")
            
    return files_to_update

def call_openai_update(client, diff_text, doc_files):
    print("Asking OpenAI to generate updated documentation...")
    
    doc_context = ""
    for path, content in doc_files.items():
        doc_context += f"--- FILE: {path} ---\n{content}\n\n"

    prompt = f"""
Role
You are an expert Technical Writer and Software Engineer specialized in VitePress documentation. Your task is to synchronize Markdown documentation with recent code changes while leveraging VitePress-specific features for a premium developer experience.

Input Data
You will be provided with:
1. Git Diff: A standard git diff showing additions, deletions, and modifications in the codebase.
2. Documentation Context: The current content of relevant Markdown files, formatted as:
--- FILE: path/to/file.md ---[Content]

Objectives
1. Visibility Filtering
- Developer-Facing Only: Focus exclusively on changes that affect the public API, configuration, installation, or behavior as experienced by a developer using the library/app.
- Ignore Internal Logic: Do not document internal refactors, private helper functions, performance optimizations, or logic changes that do not alter the external interface or outcome.

2. Update Logic
- Handle Removals: If functionality is removed in the diff, completely delete the corresponding documentation from the Markdown files. Do not add "outdated" notices or explanations for why it was removed.
- Handle Changes: If the behavior, signature, or configuration of existing functionality has changed, update the documentation to reflect the current state.
- Handle Additions: If the diff contains new public-facing features or parameters that are not currently documented, add new sections or entries to the appropriate files.
- Preserve Context: Maintain the existing tone, header structure, and unrelated content. Do not remove valid documentation for code that was not affected by the diff.

VitePress Guidelines
- Frontmatter: Preserve or update existing YAML frontmatter (e.g., title, description, outline). Ensure the outline level is updated if you add new headers.
- Custom Containers: Use VitePress containers to highlight important notes:::: info, ::: tip, ::: warning, ::: dangerCode Groups: When comparing old vs. new behavior or showing multiple language examples, use the code-group Syntax:

::: code-group
``` [v2.0 (Current)]
// New usage
```
``` [v1.0 (Old)]
// Old usage
```
:::

- Badges: Use <Badge type="tip" text="New" /> or version badges next to headers for new features.
- Links: Ensure all internal cross-references and asset links remain valid according to VitePress routing rules.

Constraints
- Markdown Syntax: Strictly follow VitePress-flavored Markdown.
- No Speculation: Only document what is explicitly supported by the code changes in the diff.
- No Meta-Commentary: The response must not contain explanations, reasoning, or "I have updated the files..." messages.
- Pure Output: The output must be the updated content of the files only.

Output Format
Return a valid JSON object where:
- Keys are the file paths (exactly matching the provided context paths).
- Values are the full updated string content of the Markdown files.
- Files that required no changes must be omitted from the object.

Example:
{{
  "docs/api/index.md": "---\ntitle: API\n---\n# API\n\n[Full Updated Content...]",
  "docs/guide/setup.md": "[Full Updated Content...]"
}}

---
Input Data:

Git Diff:
{diff_text[:MAX_DIFF_CHARS]}

Documentation Files:
{doc_context[:MAX_DOC_CONTEXT_CHARS]}
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert Technical Writer and Software Engineer specialized in VitePress documentation. Your task is to synchronize Markdown documentation with recent code changes while leveraging VitePress-specific features for a premium developer experience."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print("Error decoding JSON from OpenAI response")
        print(content)
        sys.exit(1)

def apply_updates_to_repo(doc_repo, updates, new_branch_name):
    for file_path, new_content in updates.items():
        print(f"Updating {file_path}...")
        try:
            # Check if file exists to get sha
            contents = doc_repo.get_contents(file_path, ref=new_branch_name)
            doc_repo.update_file(contents.path, f"Update {file_path}", new_content, contents.sha, branch=new_branch_name)
        except GithubException:
            # Create if not exists
            print(f"Creating new file {file_path}...")
            doc_repo.create_file(file_path, f"Create {file_path}", new_content, branch=new_branch_name)

def create_doc_pr(gh, source_repo, source_pr, doc_repo_name, updates):
    doc_repo = gh.get_repo(doc_repo_name)
    base_branch = doc_repo.default_branch
    sb = doc_repo.get_branch(base_branch)
    
    new_branch_name = f"{PR_BRANCH_PREFIX}-{source_repo}-{source_pr}"
    
    # Check if branch exists
    try:
        doc_repo.get_branch(new_branch_name)
        print(f"Branch {new_branch_name} already exists. Appending timestamp.")
        import time
        new_branch_name = f"{new_branch_name}-{int(time.time())}"
    except GithubException:
        pass
        
    print(f"Creating branch {new_branch_name} from {base_branch}...")
    doc_repo.create_git_ref(ref=f"refs/heads/{new_branch_name}", sha=sb.commit.sha)
    
    apply_updates_to_repo(doc_repo, updates, new_branch_name)
    
    # Create PR
    print("Creating Pull Request...")
    pr_body = f"Automated documentation update triggered by changes in {source_repo} PR #{source_pr}."
    pr = doc_repo.create_pull(
        title=f"Docs Update for {source_repo} #{source_pr}",
        body=pr_body,
        head=new_branch_name,
        base=base_branch
    )
    
    print(f"Successfully created PR: {pr.html_url}")

def main():
    parser = argparse.ArgumentParser(description='Update documentation based on PR diff.')
    parser.add_argument('--source-pr', required=True, help='PR number of source')
    parser.add_argument('--source-repo', required=True, help='Source repository (owner/name)')
    parser.add_argument('--doc-repo', required=True, help='Documentation repository (owner/name)')
    parser.add_argument('--doc-path', required=True, help='Path within doc repo to scan')
    parser.add_argument('--repo-path', default='.', help='Local path to source repo git')
    
    args = parser.parse_args()

    # Secrets from env
    gh_token = os.environ.get("GH_TOKEN")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if not gh_token or not openai_key:
        print("Missing GH_TOKEN or OPENAI_API_KEY environment variables.")
        sys.exit(1)
        
    gh = Github(gh_token)
    client = OpenAI(api_key=openai_key, base_url=OPENAI_BASE_URL)
    
    # 1. Get Diff
    diff_text = get_local_git_diff(gh, args.source_repo, int(args.source_pr), args.repo_path)
    if not diff_text.strip():
        print("Empty diff, nothing to do.")
        sys.exit(0)
        
    print(f"Diff length: {len(diff_text)} chars")
        
    # 2. Get Docs
    doc_files = get_doc_files(gh, args.doc_repo, args.doc_path)
    if not doc_files:
        print(f"No markdown files found in {args.doc_path}.")
        sys.exit(0)
        
    # 3. Triage
    files_to_update = call_openai_triage(client, diff_text, doc_files)
    if not files_to_update:
        print("OpenAI determined no documentation update is needed.")
        sys.exit(0)
        
    print(f"Documentation update required for {len(files_to_update)} files. Proceeding to generation...")
    
    # Filter doc_files to only include those that need updates
    filtered_doc_files = {path: doc_files[path] for path in files_to_update}
    
    # 4. Generate Updates
    updates = call_openai_update(client, diff_text, filtered_doc_files)
    
    if not updates:
        print("OpenAI returned no updates.")
        sys.exit(0)
        
    # 5. Create PR in Doc Repo
    create_doc_pr(gh, args.source_repo, args.source_pr, args.doc_repo, updates)

if __name__ == "__main__":
    main()
