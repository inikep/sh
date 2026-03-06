#!/opt/venv/bin/python
import argparse
import subprocess
import os
import sys
import time
from datetime import datetime

# Import resolve_conflicts from the provided module
from llm_utils import resolve_conflicts, run_command


def get_commit_list(commit_range):
    # Use git log --oneline to get hashes and titles in one go
    # Format: hash title
    cmd = f"git log --reverse --oneline {commit_range}"
    result = run_command(cmd)
    lines = result.stdout.strip().splitlines()
    commits = []
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "title": parts[1]})
        else:
            commits.append({"hash": parts[0], "title": ""})
    return commits

def wait_for_user_to_continue():
    while True:
        user_input = input("Press 'c' or Enter to continue, 'q' to quit, or enter a number for new chunk size: ").strip().lower()
        if user_input == 'q':
            print("Aborting script at user request.")
            sys.exit(0)
        elif user_input == 'c' or user_input == '':
            return None
        elif user_input.isdigit():
            return int(user_input)
        else:
            print("Invalid input. Please try again.")

def process_commits(commits, model, log_dir):
    marker_title = "Make MyRocks buildable"
    marker_index = -1

    # At start check if marker is in batch (globally)
    for idx, commit in enumerate(commits):
        if marker_title in commit["title"]:
            marker_index = idx
            break

    override_chunk_size = None
    i = 0
    while i < len(commits):
        # If there is a marker then use current_chunk_size = 128 before marker
        # and current_chunk_size = 16 after marker (or if no marker found)
        if override_chunk_size is not None:
            current_chunk_size = override_chunk_size
        elif marker_index != -1 and i <= marker_index:
            current_chunk_size = 128
            # Check if the marker is within this potential chunk
            if i + current_chunk_size > marker_index:
                current_chunk_size = marker_index - i + 1
                print(f"Found marker commit. Adjusting batch size to finish this commit, then switching to 16.")
        else:
            # If there in no marker current_chunk_size = 16
            current_chunk_size = 8
        
        chunk_end = min(i + current_chunk_size, len(commits))
        current_batch = commits[i:chunk_end]
            
        cherry_pick_batch(current_batch, model, len(commits) - i - len(current_batch), log_dir)

        # Wait for user acceptance
        print(f"Batch completed. {len(commits) - chunk_end} commits remaining.")
        res = wait_for_user_to_continue()
        if res is not None:
            override_chunk_size = res
            print(f"Chunk size set to {override_chunk_size} for next batches.")

        i = chunk_end

def is_cherry_pick_in_progress():
    git_dir = run_command("git rev-parse --git-dir").stdout.strip()
    return os.path.exists(os.path.join(git_dir, "CHERRY_PICK_HEAD")) or \
           os.path.exists(os.path.join(git_dir, "sequencer"))

def ensure_clean_git_status():
    status = run_command("git status --porcelain").stdout.strip()
    if status:
        print(f"WARNING: Uncommitted changes found: {status}")
        sys.exit(1)

def ensure_git_has_only_staged_changes():
    # Check for unstaged or untracked changes
    # git status --porcelain outputs "XY PATH"
    # Y != ' ' means unstaged changes (modified in work tree)
    # XY == '??' means untracked
    status_output = run_command("git status --porcelain").stdout.strip()
    if not status_output:
        return

    lines = status_output.splitlines()
    has_issues = False
    for line in lines:
        if len(line) < 2: 
            continue
        
        # Check for untracked
        if line.startswith("??"):
            print(f"Error: Untracked file found: {line[3:]}")
            has_issues = True
            continue
            
        # Check for unstaged changes (second char is not space)
        # Note: If it's a conflict 'UU', it shows as 'UU'
        # We probably only want to allow staged changes.
        # Staged changes usually look like 'M ' or 'A ' or 'D '
        x = line[0]
        y = line[1]
        
        if y != ' ':
            print(f"Error: Unstaged changes found: {line[3:]} (Status: {x}{y})")
            has_issues = True
            
    if has_issues:
        print("Aborting: Found unstaged or untracked files. Please stage or clean them.")
        sys.exit(1)

def cherry_pick_batch(current_batch, model, commits_remaining, log_dir):
        # Prepare the range for cherry-pick
        if len(current_batch) == 1:
            commit_arg = current_batch[0]["hash"]
        else:
            commit_arg = " ".join([c["hash"] for c in current_batch])

        print(f"Cherry-picking batch of {len(current_batch)} commits...")
        
        cmd = f"git cherry-pick {commit_arg}"
        env = os.environ.copy()

        while True:
            try:
                subprocess.run(cmd, shell=True, check=True, env=env)
                break
            except subprocess.CalledProcessError:
                print("Conflict detected.")
                subprocess.run("git status", shell=True)
                
                action = None
                while True:
                    print("s) skip commit (git cherry-pick --skip)")
                    print("c) solve Conflict manually and continue")
                    print("q) quit (git cherry-pick --quit)")
                    print("l) solve Conflict with LLM")
                    ans = input("Choose option: ").strip().lower()
                    
                    if ans == 'q':
                        subprocess.run("git cherry-pick --quit", shell=True)
                        sys.exit(0)
                    elif ans == 's':
                        action = 'skip'
                        break
                    elif ans == 'c':
                        action = 'continue'
                        break
                    elif ans == 'l':
                        handle_conflict(model, log_dir)
                        print("LLM resolution completed.")
                        action = 'continue'
                        break
                
                if action == 'skip':
                     cmd = "git cherry-pick --skip"
                     env["GIT_EDITOR"] = "true"
                     continue

                ensure_git_has_only_staged_changes()
                if not is_cherry_pick_in_progress():
                    print("Cherry-pick state cleared (likely finished or aborted by user). Stopping this batch.")
                    return
                wait_for_user_to_continue()
                cmd = "git cherry-pick --continue"
                env["GIT_EDITOR"] = "true"

        print("Batch finished. Checking status...")
        ensure_clean_git_status()


def handle_conflict(model, log_dir):
    print(f"Resolving conflict with model {model}...")
    
    # Save original stdout/stderr because resolve_conflicts modifies them without restoring
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    
    try:
        resolve_conflicts(model, log_dir=log_dir, stage_files=True)
    finally:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def main():
    parser = argparse.ArgumentParser(description="Automated cherry-pick with AI conflict resolution")
    parser.add_argument("base_branch", help="Base branch to checkout")
    parser.add_argument("commit_range", help="The commit range to cherry-pick")
    parser.add_argument("output_branch", help="Name of the output branch")
    parser.add_argument("log_dir", nargs='?', default="./conflicts", help="Directory to store logs (default: ./conflicts)")
    parser.add_argument("model", nargs='?', default="gemini-3-pro-preview", help="AI model to use (default: gemini-3-pro-preview)")
    
    args = parser.parse_args()
    
    print("Discarding unstaged changes...")
    run_command("git reset --hard", check=False)
    run_command("git clean -ffd", check=False)
    
    # Create and checkout output branch based on base_branch
    print(f"Creating and checking out {args.output_branch} based on {args.base_branch}...")
    # fetch first? maybe not needed if local
    run_command(f"git checkout -B {args.output_branch} {args.base_branch}")
    run_command("git clean -ffd", check=False)
    ensure_clean_git_status()

    # Get commits
    commits = get_commit_list(args.commit_range)
    print(f"Found {len(commits)} commits to cherry-pick.")
    
    process_commits(commits, args.model, args.log_dir)
    
    print("Cherry-pick sequence completed successfully.")

if __name__ == "__main__":
    main()
