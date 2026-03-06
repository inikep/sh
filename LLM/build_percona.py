#!/usr/bin/env python3
import os
import sys
import argparse
import multiprocessing
import llm_utils

def main():
    parser = argparse.ArgumentParser(description="Build Percona Server and log output.")
    parser.add_argument("log_dir", help="Directory to store logs")
    args = parser.parse_args()

    # Ensure current directory is the project root or where we want to build
    cwd = os.getcwd()
    source_dir = cwd

    # Check for specific directory structure to switch to out-of-source build
    # Logic: if we are in X, build in X-auto-build
    # Example: /data/mysql-server/percona-8.0 -> /data/mysql-server/percona-8.0-auto-build
    cwd_name = os.path.basename(cwd)
    # We apply this logic if we are seemingly in a source repo (simple heuristic: has .git or CMakeLists.txt)
    # But user specifically asked to strip last part and append suffix.
    # Let's just do it generally if the user wants out-of-source builds, or maybe always?
    # The previous prompt was specific to "percona-8.0", this one generalizes it.
    # Let's assume we want to do this auto-build folder logic for ANY directory we are in.
    
    parent_dir = os.path.dirname(cwd)
    build_dir_name = f"{cwd_name}-auto-build"
    build_dir = os.path.join(parent_dir, build_dir_name)
    
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    print(f"Using build directory: {build_dir}")

    # 1. Get HEAD hash for log filename (must run in source dir)
    head_hash = "unknown"
    res = llm_utils.run_command("git log --oneline -1 HEAD", check=False, capture_output=True)
    if res.returncode == 0:
        head_hash = res.stdout.strip().split(" ")[0]

    # 2. Setup logging
    # Resolve log_dir to absolute path before changing directory
    log_dir = os.path.abspath(args.log_dir)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_filename = os.path.join(log_dir, f"build_issue_{head_hash}.log")
    
    # Handle existing log files by appending a counter if needed, or just overwrite/append?
    # llm_utils logic appends counter.
    base_log_filename = os.path.join(log_dir, f"build_issue_{head_hash}")
    counter = 1
    temp_log_filename = f"{base_log_filename}.log"
    while os.path.exists(temp_log_filename):
        temp_log_filename = f"{base_log_filename}_{counter}.log"
        counter += 1
    log_filename = temp_log_filename

    print(f"Logging build output to {log_filename}")
    
    # Setup Tee for logging
    log_file = open(log_filename, "a")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = llm_utils.Tee(sys.stdout, log_file)
    sys.stderr = llm_utils.Tee(sys.stderr, log_file)

    try:
        # Change to build directory
        if build_dir != source_dir:
            os.chdir(build_dir)

        print(f"Starting build for commit {head_hash} in {build_dir}")
        
        # Check if we need to run cmake
        # Criteria:
        # 1. CMakeCache.txt does not exist (clean build)
        # 2. User requested it? (implicit for now if we want to ensure correctness)
        # 3. Git submodules need update?
        
        should_run_cmake = False
        try:
            # git submodule status prints lines starting with:
            #  - (minus) if the submodule is not initialized
            #  + (plus) if the currently checked out submodule commit does not match the SHA-1 found in the index of the containing repository
            #  U (U) if the submodule has merge conflicts
            res = llm_utils.run_command(["git", "-C", source_dir, "submodule", "status"], check=False, capture_output=True, shell=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.startswith("-") or line.startswith("+") or line.startswith("U"):
                        print(f"Submodule change detected: {line.strip()}")
                        should_run_cmake = True
                        # Update submodules
                        print("Updating git submodules...")
                        llm_utils.run_command(["git", "-C", source_dir, "submodule", "update", "--init", "--recursive"], check=True, capture_output=False, shell=False)
                        break
        except Exception as e:
            print(f"Warning: could not check submodules: {e}")

        if not os.path.exists("CMakeCache.txt"):
             should_run_cmake = True

        if should_run_cmake:
            # 1. Clear build dir before cmake (only if we are running cmake)
            # Be careful not to delete the log file if it's in the build dir (though it shouldn't be by default)
            # The log file is in `log_dir`. `build_dir` is usually `...-auto-build`.
            # We are currently IN build_dir.
            print("Cleaning build directory...")
            # We can use 'rm -rf *' but safer to just remove specific things or everything except "." and ".."
            # Since we want to clear it, let's remove contents.
            # BUT: we are running the script and logging to a file. If the log file is here, we delete it!
            # The log file is opened in `log_dir`. If `log_dir` == `build_dir` (unlikely by default), we have a problem.
            # Default log_dir is ./build_issue (relative to where script started).
            # We changed cwd to build_dir. 
            # If user started in percona-8.0, log_dir is percona-8.0/build_issue. build_dir is percona-8.0-auto-build. They are different.
            
            # Let's just remove everything in current dir (build_dir)
            for item in os.listdir("."):
                if item == "." or item == "..": continue
                # Skip if it happens to be the log file we are writing to?
                # It's hard to know exact path if we just have file handle, but we have `log_filename`.
                # `log_filename` is absolute or relative to original CWD.
                # If we are safe, we delete.
                try:
                    if os.path.isdir(item):
                        import shutil
                        shutil.rmtree(item)
                    else:
                        os.remove(item)
                except Exception as e:
                    print(f"Warning: could not remove {item}: {e}")

            # a) Call cmake
            # CMake flags
            # -DCMAKE_INSTALL_PREFIX=../percona-8.0-deb-gcc14-rocks-install

            cmake_flags = [
                "-DCMAKE_BUILD_TYPE=Debug",
                "-DMYSQL_MAINTAINER_MODE=ON",
                "-DBUILD_CONFIG=mysql_release",
                "-DWITH_PACKAGE_FLAGS=OFF",
                "-DWITH_NUMA=ON",
                "-DWITH_NDB=OFF",
                "-DWITH_NDBCLUSTER=OFF",
                "-DWITH_SYSTEM_LIBS=ON",
                "-DWITH_MECAB=system",
                "-DWITH_EDITLINE=system",
                "-DWITH_ROCKSDB=ON",
                "-DWITH_COREDUMPER=ON", 
                "-DWITH_PAM=ON",
                "-DWITH_KEYRING_VAULT=ON",
                "-DWITH_KEYRING_VAULT_TEST=ON",
                "-DWITH_PERCONA_AUTHENTICATION_LDAP=ON",
                "-DWITH_PERCONA_TELEMETRY=ON",
                "-DCMAKE_C_COMPILER=gcc-14",
                "-DCMAKE_CXX_COMPILER=g++-14",
                "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
                "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
                "-DDOWNLOAD_BOOST=1",
                "-DWITH_BOOST=../_deps"
            ]
            
            cmake_cmd = ["cmake"] + cmake_flags + [source_dir]
            print(f"Running CMake: {' '.join(cmake_cmd)}")
            llm_utils.run_command(cmake_cmd, check=True, capture_output=False, shell=False)
        else:
            print("CMakeCache.txt found. Skipping CMake configuration.")

        # b) Build Percona Server
        # Using make with parallel jobs
        cpu_count = int(multiprocessing.cpu_count() - 4)
        if cpu_count > 80:
             cpu_count = 80
        build_cmd = ["make", f"-j{cpu_count}"]
        print(f"Running Build: {' '.join(build_cmd)}")
        llm_utils.run_command(build_cmd, check=True, capture_output=False, shell=False)

        print("Build completed successfully.")

    except Exception as e:
        print(f"Build failed: {e}")
        sys.exit(1)
    finally:
        # Restore stdout/stderr (optional since script ends, but good practice)
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()

if __name__ == "__main__":
    main()
