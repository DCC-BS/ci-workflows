import argparse
import difflib
import os
import re
import subprocess
import sys

import github
from constants import (
    CUSTOM_INSTRUCTIONS_TEMPLATE,
    DELETE_FILE_MARKER,
    DIFF_FILTER_PATTERNS,
    MAX_DIFF_CHARS,
    MAX_DOC_CONTEXT_CHARS,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    PR_BRANCH_PREFIX,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_PROMPT_TEMPLATE,
    TRIAGE_SYSTEM_PROMPT,
    TRIAGE_USER_PROMPT_TEMPLATE,
    UPDATE_SYSTEM_PROMPT,
    UPDATE_USER_PROMPT_TEMPLATE,
)
from github import Github, GithubException
from openai import OpenAI


def render_custom_instructions(custom_instructions):
    """Render the optional user-instructions block, or empty string."""
    text = (custom_instructions or "").strip()
    if not text:
        return ""
    return CUSTOM_INSTRUCTIONS_TEMPLATE.format(custom_instructions=text)


def sanitize_branch_component(value):
    """Make a string safe for use inside a git branch name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def get_message_content(response):
    """Safely extract message content from an OpenAI chat response."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError):
        return ""
    return content.strip() if content else ""


def strip_code_fences(text):
    """Remove a single wrapping ``` / ```lang fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    # Drop opening fence (possibly with a language tag) and trailing fence.
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def get_local_git_diff(gh, repo_name, pr_number, repo_path="."):
    # Assumes repo_path is the source repo checked out by actions/checkout.
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        print(f"Error: {repo_path} is not a valid git repository.")
        sys.exit(1)

    print(f"Resolving base and head for PR #{pr_number} in {repo_name}...")
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    base_ref = pr.base.ref
    head_sha = pr.head.sha

    print(f"Base branch is: {base_ref}")
    print(f"Head SHA is: {head_sha}")

    try:
        print(f"Fetching origin/{base_ref}...")
        subprocess.check_call(["git", "fetch", "origin", base_ref], cwd=repo_path)
    except subprocess.CalledProcessError as e:
        print(f"Warning: Error fetching base branch {base_ref}: {e}")
        # Fetch can fail when the ref is already present locally; fall back to it.
        try:
            subprocess.check_call(
                ["git", "rev-parse", "--verify", f"origin/{base_ref}"],
                cwd=repo_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"Base ref origin/{base_ref} exists locally, continuing...")
        except subprocess.CalledProcessError:
            print(
                f"Error: Base ref origin/{base_ref} does not exist locally and fetch failed."
            )
            sys.exit(1)
    try:
        print(f"Fetching PR head (pull/{pr_number}/head)...")
        subprocess.check_call(
            ["git", "fetch", "origin", f"pull/{pr_number}/head"], cwd=repo_path
        )
    except subprocess.CalledProcessError as e:
        print(f"Error fetching PR head: {e}")
        sys.exit(1)

    print(f"Generating diff between origin/{base_ref} and FETCH_HEAD...")
    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                f"origin/{base_ref}",
                "FETCH_HEAD",
                "-W",
                "-U20",
                "--inter-hunk-context=15",
                "--",
                *DIFF_FILTER_PATTERNS,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout, pr.body
    except subprocess.CalledProcessError as e:
        print(f"Error generating git diff: {e.stderr}")
        sys.exit(1)


def get_vitepress_config(repo, ref):
    """Check for and fetch .vitepress/config.ts if it exists."""
    for vitepress_config_path in (".vitepress/config.ts", ".vitepress/config.mts"):
        try:
            config_file = repo.get_contents(vitepress_config_path, ref=ref)
            content = config_file.decoded_content.decode("utf-8")
            print(f"Found VitePress config at {vitepress_config_path}")
            return {vitepress_config_path: content}
        except GithubException:
            continue
    print("No VitePress config file found (.vitepress/config.ts or .mts)")
    return {}


def get_doc_files(repo, doc_path, ref):
    print(f"Fetching documentation files from {repo.full_name}/{doc_path} @ {ref}...")
    files_content = {}

    vitepress_config = get_vitepress_config(repo, ref)
    files_content.update(vitepress_config)

    try:
        contents = repo.get_contents(doc_path, ref=ref)
    except GithubException as e:
        print(f"Error accessing path {doc_path} in {repo.full_name}: {e}")
        sys.exit(1)

    while contents:
        file_content = contents.pop(0)
        if file_content.type == "dir":
            contents.extend(repo.get_contents(file_content.path, ref=ref))
        else:
            if file_content.path.endswith(".md"):
                try:
                    files_content[file_content.path] = (
                        file_content.decoded_content.decode("utf-8")
                    )
                except Exception as e:
                    print(f"Skipping {file_content.path} due to decoding error: {e}")

    return files_content


def call_openai_triage(
    client, diff_text, pr_description, doc_files, custom_instructions=""
):
    print("Checking each documentation file for needed updates...")
    files_to_update = []
    custom_section = render_custom_instructions(custom_instructions)

    for path, content in doc_files.items():
        print(f"  Checking {path}...")
        prompt = TRIAGE_USER_PROMPT_TEMPLATE.format(
            diff_text=diff_text[:MAX_DIFF_CHARS],
            pr_description=pr_description or "No description provided.",
            path=path,
            content=content[:MAX_DOC_CONTEXT_CHARS],
            custom_instructions_section=custom_section,
        )
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        answer = get_message_content(response).upper()
        if "YES" in answer:
            print(f"    -> Update NEEDED for {path}")
            files_to_update.append(path)
        else:
            print(f"    -> No update needed for {path}")

    return files_to_update


def call_openai_update(
    client, diff_text, pr_description, doc_files, custom_instructions=""
):
    print(
        f"Asking OpenAI to generate updated documentation for {len(doc_files)} files ..."
    )

    updates = {}
    custom_section = render_custom_instructions(custom_instructions)

    for target_path, target_content in doc_files.items():
        print(f"  Updating {target_path}...")

        # Build ambient context from the *other* files being updated, so the
        # target's own (untruncated) content is never clipped by the budget.
        ambient_context = ""
        for path, content in doc_files.items():
            if path == target_path:
                continue
            ambient_context += f"\n--- FILE: {path} ---\n{content}\n\n"

        prompt = UPDATE_USER_PROMPT_TEMPLATE.format(
            target_path=target_path,
            target_content=target_content,
            diff_text=diff_text[:MAX_DIFF_CHARS],
            pr_description=pr_description or "No description provided.",
            ambient_context=ambient_context[:MAX_DOC_CONTEXT_CHARS],
            custom_instructions_section=custom_section,
        )

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": UPDATE_SYSTEM_PROMPT,
                },
                {"role": "user", "content": prompt},
            ],
        )

        new_content = strip_code_fences(get_message_content(response))

        if new_content.strip() == DELETE_FILE_MARKER:
            updates[target_path] = None
            print(f"    -> Marked {target_path} for DELETION")
        elif new_content and new_content != target_content:
            updates[target_path] = new_content
            print(f"    -> Generated updates for {target_path}")
        else:
            print(f"    -> No changes generated for {target_path}")

    return updates


def call_openai_summary(
    client, diff_text, pr_description, doc_files, updates, custom_instructions=""
):
    """Generate a short Markdown summary of the doc changes for a PR comment."""
    custom_section = render_custom_instructions(custom_instructions)

    doc_diffs = ""
    for path, new_content in updates.items():
        old_content = doc_files.get(path, "")
        if new_content is None:
            doc_diffs += f"--- a/{path}\n+++ /dev/null\n(entire file deleted)\n\n"
            continue
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        doc_diffs += "\n".join(diff) + "\n\n"

    updated_paths = ", ".join(
        f"{path} (deleted)" if content is None else path
        for path, content in updates.items()
    )
    prompt = SUMMARY_USER_PROMPT_TEMPLATE.format(
        diff_text=diff_text[:MAX_DIFF_CHARS],
        pr_description=pr_description or "No description provided.",
        updated_paths=updated_paths,
        doc_diffs=doc_diffs[:MAX_DOC_CONTEXT_CHARS],
        custom_instructions_section=custom_section,
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return get_message_content(response)
    except Exception as e:  # noqa: BLE001 - summary is best-effort
        print(f"Warning: failed to generate summary: {e}")
        return ""


def post_source_pr_comment(gh, source_repo, source_pr, body):
    """Post a comment back on the source PR. Best-effort."""
    try:
        repo = gh.get_repo(source_repo)
        repo.get_issue(source_pr).create_comment(body)
        print("Posted status comment on source PR.")
    except GithubException as e:
        print(f"Warning: could not post comment on source PR: {e}")


def apply_updates_to_repo(doc_repo, updates, new_branch_name):
    """Apply updates (content or None for deletion) to the branch.

    Skips no-op writes so re-runs don't push empty duplicate commits.
    Returns the number of commits actually made.
    """
    changed = 0
    for file_path, new_content in updates.items():
        try:
            contents = doc_repo.get_contents(file_path, ref=new_branch_name)
        except GithubException:
            contents = None

        if new_content is None:
            if contents is None:
                print(f"Skipping deletion of {file_path}: already absent.")
                continue
            print(f"Deleting {file_path}...")
            doc_repo.delete_file(
                contents.path,
                f"Delete {file_path}",
                contents.sha,
                branch=new_branch_name,
            )
            changed += 1
        elif contents is None:
            print(f"Creating new file {file_path}...")
            doc_repo.create_file(
                file_path, f"Create {file_path}", new_content, branch=new_branch_name
            )
            changed += 1
        else:
            try:
                current = contents.decoded_content.decode("utf-8")
            except Exception:
                current = None
            if current == new_content:
                print(f"Skipping {file_path}: branch content already up to date.")
                continue
            print(f"Updating {file_path}...")
            doc_repo.update_file(
                contents.path,
                f"Update {file_path}",
                new_content,
                contents.sha,
                branch=new_branch_name,
            )
            changed += 1
    return changed


def create_doc_pr(source_repo, source_pr, doc_repo, branch_name, existing_pr, updates):
    """Create or update a single doc PR per source PR (idempotent).

    Reuses a deterministic branch so repeated /documentation comments refine
    the same documentation PR instead of opening a new one each time.
    Returns the PR's html_url, or None if nothing changed and no PR exists.
    """
    base_branch = doc_repo.default_branch

    if existing_pr is None:
        # No open PR: start from a fresh branch state. If a stale branch is
        # left over from a merged/closed PR, reset it onto the current base.
        sb = doc_repo.get_branch(base_branch)
        try:
            ref = doc_repo.get_git_ref(f"heads/{branch_name}")
            print(f"Resetting stale branch {branch_name} to {base_branch}...")
            ref.edit(sha=sb.commit.sha, force=True)
        except GithubException:
            print(f"Creating branch {branch_name} from {base_branch}...")
            doc_repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sb.commit.sha)
    else:
        print(f"Working on existing PR branch {branch_name}.")

    changed = apply_updates_to_repo(doc_repo, updates, branch_name)

    if existing_pr is not None:
        print(f"Reusing existing PR: {existing_pr.html_url}")
        return existing_pr.html_url

    if changed == 0:
        print("No effective changes; not creating a PR.")
        return None

    print("Creating Pull Request...")
    pr_body = (
        f"Automated documentation update triggered by changes in "
        f"{source_repo} PR #{source_pr}."
    )
    pr = doc_repo.create_pull(
        title=f"Docs Update for {source_repo} #{source_pr}",
        body=pr_body,
        head=branch_name,
        base=base_branch,
    )

    print(f"Successfully created PR: {pr.html_url}")
    return pr.html_url


def main():
    parser = argparse.ArgumentParser(
        description="Update documentation based on PR diff."
    )
    parser.add_argument("--source-pr", required=True, help="PR number of source")
    parser.add_argument(
        "--source-repo", required=True, help="Source repository (owner/name)"
    )
    parser.add_argument(
        "--doc-repo", required=True, help="Documentation repository (owner/name)"
    )
    parser.add_argument(
        "--doc-path", required=True, help="Path within doc repo to scan"
    )
    parser.add_argument(
        "--repo-path", default=".", help="Local path to source repo git"
    )
    parser.add_argument(
        "--custom-instructions",
        default="",
        help="Optional free-text instructions from the /documentation command.",
    )

    args = parser.parse_args()
    custom_instructions = args.custom_instructions
    source_repo = args.source_repo
    source_pr = int(args.source_pr)

    gh_token = os.environ.get("GH_TOKEN")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if not gh_token or not openai_key:
        print("Missing GH_TOKEN or OPENAI_API_KEY environment variables.")
        sys.exit(1)

    gh = Github(auth=github.Auth.Token(gh_token))
    client = OpenAI(api_key=openai_key, base_url=OPENAI_BASE_URL)

    if custom_instructions.strip():
        print(f"Custom instructions: {custom_instructions.strip()}")

    # 1. Get Diff
    diff_text, pr_description = get_local_git_diff(
        gh, source_repo, source_pr, args.repo_path
    )
    if not diff_text.strip():
        print("Empty diff, nothing to do.")
        sys.exit(0)

    print(f"Diff length: {len(diff_text)} chars")

    # 2. Get Docs — read from the open doc PR branch when one exists, so
    # follow-up /documentation rounds build on earlier automated changes
    # instead of regenerating them from the default branch.
    doc_repo = gh.get_repo(args.doc_repo)
    branch_name = sanitize_branch_component(
        f"{PR_BRANCH_PREFIX}-{source_repo}-{source_pr}"
    )
    existing_prs = list(
        doc_repo.get_pulls(state="open", head=f"{doc_repo.owner.login}:{branch_name}")
    )
    existing_pr = existing_prs[0] if existing_prs else None
    doc_ref = branch_name if existing_pr else doc_repo.default_branch

    doc_files = get_doc_files(doc_repo, args.doc_path, doc_ref)
    if not doc_files:
        print(f"No markdown files found in {args.doc_path}.")
        sys.exit(0)

    # 3. Triage
    files_to_update = call_openai_triage(
        client, diff_text, pr_description, doc_files, custom_instructions
    )
    if not files_to_update:
        print("OpenAI determined no documentation update is needed.")
        post_source_pr_comment(
            gh,
            source_repo,
            source_pr,
            "📝 **Documentation check complete** — no documentation updates "
            "appear to be needed for these changes.",
        )
        sys.exit(0)

    print(
        f"Documentation update required for {len(files_to_update)} files. Proceeding to generation..."
    )

    # Filter doc_files to only include those that need updates
    filtered_doc_files = {path: doc_files[path] for path in files_to_update}

    # 4. Generate Updates
    updates = call_openai_update(
        client, diff_text, pr_description, filtered_doc_files, custom_instructions
    )

    if not updates:
        print("OpenAI returned no updates.")
        post_source_pr_comment(
            gh,
            source_repo,
            source_pr,
            "📝 **Documentation check complete** — the docs already look "
            "up to date; no changes were generated.",
        )
        sys.exit(0)

    # 5. Create or update PR in Doc Repo
    pr_url = create_doc_pr(
        source_repo, source_pr, doc_repo, branch_name, existing_pr, updates
    )
    if pr_url is None:
        post_source_pr_comment(
            gh,
            source_repo,
            source_pr,
            "📝 **Documentation check complete** — the docs already look "
            "up to date; no changes were pushed.",
        )
        sys.exit(0)

    # 6. Summarize and report back on the source PR
    summary = call_openai_summary(
        client,
        diff_text,
        pr_description,
        filtered_doc_files,
        updates,
        custom_instructions,
    )
    comment = "📝 **Documentation updated**\n\n"
    if summary:
        comment += summary + "\n\n"
    comment += f"➡️ Documentation PR: {pr_url}"
    post_source_pr_comment(gh, source_repo, source_pr, comment)


if __name__ == "__main__":
    main()
