#!/opt/venv/bin/python
import argparse
import subprocess
import sys
from ai_utils import resolve_conflicts, run_command

def main():
    parser = argparse.ArgumentParser(description="Check out to base commit and cherry-pick a commit (if params provided). Then resolve conflicts using AI.")
    parser.add_argument("model", default="gemini-3-pro-preview", help="AI model to use (default: gemini-3-pro-preview)")
    parser.add_argument("base_commit", nargs='?', help="The base commit to checkout")
    parser.add_argument("cherry_pick_commit", nargs='?', help="The commit to cherry-pick")
    parser.add_argument("log_dir", nargs='?', default="./conflicts", help="Directory to store logs (default: ./conflicts)")

    args = parser.parse_args()

    if args.base_commit and args.cherry_pick_commit:
        print(f"Checking out base commit: {args.base_commit}")
        try:
            run_command(f"git checkout -f {args.base_commit}")
        except subprocess.CalledProcessError:
            sys.exit(1)

        print(f"Cherry-picking commit: {args.cherry_pick_commit}")
        result = run_command(f"git cherry-pick {args.cherry_pick_commit}", check=False)

        if result.returncode == 0:
            print("Cherry-pick successful. No conflicts.")
            sys.exit(0)
        else:
            print("Cherry-pick encountered conflicts.")
            resolve_conflicts(args.model, args.log_dir)
    else:
        if args.base_commit and not args.cherry_pick_commit:
            args.log_dir = args.base_commit

        print("No cherry-pick arguments provided. Attempting to resolve conflicts in current path.")
        resolve_conflicts(args.model, args.log_dir)

if __name__ == "__main__":
    main()
