import subprocess
import sys
import os
import time

class Tee(object):
    def __init__(self, *files):
        self.files = files
    def write(self, obj):
        for f in self.files:
            try:
                f.write(obj)
                f.flush()
            except: pass
    def flush(self):
        for f in self.files:
            try:
                f.flush()
            except: pass

def run_command(command, check=True, **kwargs):
    shell = kwargs.pop('shell', True)
    capture_output = kwargs.pop('capture_output', True)
    text = kwargs.pop('text', True)
    
    if not capture_output and sys.stdout != sys.__stdout__:
        # Stream mode with custom stdout (Tee)
        # We need to manually capture and write to sys.stdout to ensure it goes to the file
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.STDOUT
        kwargs['text'] = True # Force text to read lines
        
        process = subprocess.Popen(command, shell=shell, **kwargs)
        
        output = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                sys.stdout.write(line)
                output.append(line)
                
        rc = process.poll()
        if check and rc != 0:
            raise subprocess.CalledProcessError(rc, command, output="".join(output))
        return subprocess.CompletedProcess(command, rc, stdout="".join(output), stderr=None)

    try:
        result = subprocess.run(command, shell=shell, check=check, capture_output=capture_output, text=text, **kwargs)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        if e.stdout:
            print(f"Stdout: {e.stdout}")
        if e.stderr:
            print(f"Stderr: {e.stderr}")
        raise e

def get_conflicted_files():
    # Get list of unmerged files
    result = run_command("git diff --name-only --diff-filter=U", check=False)
    if result.returncode != 0:
        return []
    files = result.stdout.strip().splitlines()
    if "MYSQL_VERSION" in files:
        files.append("storage/innobase/include/univ.i")
    return files

def read_file(filepath):
    try:
        with open(filepath, 'r') as f:
            return f.readlines()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []

def create_prompt_old(conflicted_files):
    prompt = (
        f"Resolve conflicts in the following files: {', '.join(conflicted_files)}.\n"
        "Do NOT stage the files and commit.\n"
    )

    if "MYSQL_VERSION" in conflicted_files:
        prompt += "Increase MYSQL_VERSION_EXTRA and increase PERCONA_INNODB_VERSION in storage/innobase/include/univ.i\n"
    
    return prompt

def create_prompt(conflicted_files):
    prompt = (
        f"Resolve all merge conflicts in the following files: {', '.join(conflicted_files)}.\n"
    )

    if "MYSQL_VERSION" in conflicted_files:
        prompt += "Increase MYSQL_VERSION_EXTRA and increase PERCONA_INNODB_VERSION in storage/innobase/include/univ.i\n"
    else:
        prompt += "CRITICAL CONSTRAINTS:\n"
        #prompt += "- ONLY resolve the existing merge conflict markers (e.g., <<<<<<<, =======, >>>>>>>).\n"
        #prompt += "- Do NOT make any changes unrelated to conflict resolution.\n"
        prompt += "- DO NOT change indentation, formatting, or white space outside of the conflict markers.\n"
        prompt += "- Do NOT stage the files and do NOT commit the changes.\n"
    return prompt

# Available models: 
# composer-1, auto
# sonnet-4.5, sonnet-4.5-thinking, opus-4.5, opus-4.5-thinking
# gemini-3-pro
# gpt-5.1, gpt-5.1-high, gpt-5.1-codex, gpt-5.1-codex-high, gpt-5.1-codex-max, gpt-5.1-codex-max-high
# opus-4.1, grok
def resolve_conflicts_with_cursor(model):
    prompt = create_prompt(get_conflicted_files())
    # Call cursor-agent
    # Using -p/--print to run non-interactively and -f/--force to allow writes
    return ["cursor-agent", prompt, "--model", model, "--print", "-f"]

# Available models: gemini-3-pro-preview, gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite
def resolve_conflicts_with_gemini(model):
    prompt = create_prompt(get_conflicted_files())
    # Call gemini
    return ["gemini", prompt, "--model", model, "--yolo"]

def resolve_conflicts(model, log_dir="./conflicts", stage_files=False):
    conflicted_files = get_conflicted_files()
    if not conflicted_files:
        print("Could not identify conflicted files.")
        # Check if cherry-pick is empty/needs skipping
        res = run_command("git status --porcelain", check=False)
        if not res.stdout.strip():
             print("Working tree clean. Attempting to commit an empty commit...")
             run_command("git commit --allow-empty --no-edit", check=False)
             return
        sys.exit(1)

    # Print git info
    head_hash = ""
    head_info = ""
    head_info_proc = run_command("git log --oneline -1 HEAD", check=False)
    if head_info_proc.returncode == 0:
        head_info = head_info_proc.stdout.strip()
        head_hash = head_info.split(" ")[0]

    cherry_hash = ""
    cherry_info = ""
    cherry_info_proc = run_command("git log --oneline -1 CHERRY_PICK_HEAD", check=False)
    if cherry_info_proc.returncode == 0:
        cherry_info = cherry_info_proc.stdout.strip()
        cherry_hash = cherry_info.split(" ")[0]

    # Setup logging to file
    import re
    def sanitize(s): return re.sub(r'[^a-zA-Z0-9_-]', '_', s)[:50]

    log_name_parts = ["resolve_conflict"]
    if head_hash: log_name_parts.append(head_hash)
    if cherry_hash: log_name_parts.append(cherry_hash)
    log_name_parts.append(sanitize(model))
    
    # Create log directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    base_log_filename = os.path.join(log_dir, "_".join(log_name_parts))
    log_filename = base_log_filename + ".log"
    counter = 1
    while os.path.exists(log_filename):
        log_filename = f"{base_log_filename}_{counter}.log"
        counter += 1
    
    print(f"Logging output to {log_filename}")
    log_file = open(log_filename, "a")
    sys.stdout = Tee(sys.stdout, log_file)
    sys.stderr = Tee(sys.stderr, log_file)

    # Print info to console and log
    print(f"Conflicted files: {', '.join(conflicted_files)}")
    if head_info: print(f"HEAD commit: {head_info}")
    if cherry_info: print(f"Cherry-pick commit: {cherry_info}")
    
    # Store original content (with conflict markers)
    original_contents = {}
    for file in conflicted_files:
        original_contents[file] = read_file(file)
        
    print(f"Running model {model} to resolve conflicts...")

    if model.startswith("cursor-gemini"):
        cmd = resolve_conflicts_with_cursor(model.replace("cursor-", "", 1))
    elif model.startswith("gemini"):
        cmd = resolve_conflicts_with_gemini(model)
    else:
        cmd = resolve_conflicts_with_cursor(model)

    prompt = create_prompt(conflicted_files)
    print(f"\033[94m==========BEGIN PROMPT==========\033[0m\n{prompt}\033[94m===========END PROMPT===========\033[0m")
    
    try:
        # We might want to see the agent's output.
        start_time = time.time()
        print("\033[94m==========BEGIN RESULT==========\033[0m")
        # subprocess.run(cmd, shell=True, check=True)
        run_command(cmd, shell=False, capture_output=False)
        print("\033[94m===========END RESULT===========\033[0m")
        end_time = time.time()
        print(f"Time taken: {end_time - start_time:.2f} seconds")
    except subprocess.CalledProcessError as e:
        print("Agent failed to run.")
        sys.exit(1)
               
    print("\033[94m==========BEGIN DIFF BETWEEN CONFLICT AND RESOLVED==========\033[0m")
    
    for file in conflicted_files:
        original_content = original_contents[file]
        
        # Use git diff for colored output
        proc = run_command(
            ["git", "diff", "--no-index", "--color", "-", file],
            shell=False,
            input="".join(original_content),
            check=False
        )
        
        if proc.stdout:
            print(proc.stdout)
        elif proc.returncode == 0:
            print(f"No changes detected in {file} (after agent run).")

    print("\033[94m==========END DIFF BETWEEN CONFLICT AND RESOLVED==========\033[0m")

    if stage_files:
        print("Staging resolved files...")
        for file in conflicted_files:
            run_command(["git", "add", file], shell=False, check=False)

    # Print info to console and log
    print(f"Conflicted files: {', '.join(conflicted_files)}")
    if head_info: print(f"HEAD commit: {head_info}")
    if cherry_info: print(f"Cherry-pick commit: {cherry_info}")
