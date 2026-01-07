import argparse
import os
import subprocess
import sys

from constants import (
    MAX_DIFF_CHARS,
    MAX_DOC_CONTEXT_CHARS,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    PR_BRANCH_PREFIX,
    TRIAGE_SYSTEM_PROMPT,
    TRIAGE_USER_PROMPT_TEMPLATE,
    UPDATE_SYSTEM_PROMPT,
    UPDATE_USER_PROMPT_TEMPLATE,
)
from github import Github, GithubException
from openai import OpenAI


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
            [
                "git",
                "diff",
                f"origin/{base_ref}",
                "-W",
                "-U20",
                "--inter-hunk-context=15",
                "--",
                ".",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
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
                    files_content[file_content.path] = (
                        file_content.decoded_content.decode("utf-8")
                    )
                except Exception as e:
                    print(f"Skipping {file_content.path} due to decoding error: {e}")

    return files_content


def call_openai_triage(client, diff_text, doc_files):
    print("Checking each documentation file for needed updates...")
    files_to_update = []

    for path, content in doc_files.items():
        print(f"  Checking {path}...")
        prompt = TRIAGE_USER_PROMPT_TEMPLATE.format(
            diff_text=diff_text[:MAX_DIFF_CHARS],
            path=path,
            content=content[:MAX_DOC_CONTEXT_CHARS],
        )
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        answer = response.choices[0].message.content.strip().upper()
        if "YES" in answer:
            print(f"    -> Update NEEDED for {path}")
            files_to_update.append(path)
        else:
            print(f"    -> No update needed for {path}")

    return files_to_update


def call_openai_update(client, diff_text, doc_files):
    print(
        f"Asking OpenAI to generate updated documentation for {len(doc_files)} files ..."
    )

    updates = {}

    # Prepare ambient context (all files being updated)
    ambient_context = ""
    for path, content in doc_files.items():
        ambient_context += f"\n--- FILE: {path} ---\n{content}\n\n"

    for target_path, target_content in doc_files.items():
        print(f"  Updating {target_path}...")

        # We can exclude the target file from its own ambient context to save a few tokens
        # but for simplicity and structure, the targets are already in ambient_context.

        prompt = UPDATE_USER_PROMPT_TEMPLATE.format(
            target_path=target_path,
            target_content=target_content,
            diff_text=diff_text[:MAX_DIFF_CHARS],
            ambient_context=ambient_context[:MAX_DOC_CONTEXT_CHARS],
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

        new_content = response.choices[0].message.content.strip()

        # Basic check to ensure we didn't just get nothing
        if new_content and new_content != target_content:
            updates[target_path] = new_content
            print(f"    -> Generated updates for {target_path}")
        else:
            print(f"    -> No changes generated for {target_path}")

    return updates


def apply_updates_to_repo(doc_repo, updates, new_branch_name):
    for file_path, new_content in updates.items():
        print(f"Updating {file_path}...")
        try:
            # Check if file exists to get sha
            contents = doc_repo.get_contents(file_path, ref=new_branch_name)
            doc_repo.update_file(
                contents.path,
                f"Update {file_path}",
                new_content,
                contents.sha,
                branch=new_branch_name,
            )
        except GithubException:
            # Create if not exists
            print(f"Creating new file {file_path}...")
            doc_repo.create_file(
                file_path, f"Create {file_path}", new_content, branch=new_branch_name
            )


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
        base=base_branch,
    )

    print(f"Successfully created PR: {pr.html_url}")


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
    diff_text = get_local_git_diff(
        gh, args.source_repo, int(args.source_pr), args.repo_path
    )
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

    print(
        f"Documentation update required for {len(files_to_update)} files. Proceeding to generation..."
    )

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
