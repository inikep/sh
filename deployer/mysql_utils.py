#!/bin/python

import os
import subprocess
import time
import shutil
import shlex
import json

def find_mysqld(basedir):
    """Find mysqld or mysqld-debug in basedir/bin."""
    for binary in ["mysqld", "mysqld-debug"]:
        path = os.path.join(basedir, "bin", binary)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            print(f"[INFO] Using {path} binary")
            return path
    raise FileNotFoundError(f"Neither mysqld-debug nor mysqld found in {basedir}/bin")

def init_datadir(mysqld_path, basedir, data_dir, log_file):
    if os.path.exists(data_dir):
        print("[INFO] Removing old datadir...")
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    print("[INFO] Initializing datadir...")
    with open(log_file, "w") as f:  # write to the .mysqld log file
        subprocess.check_call([
            mysqld_path,
            f"--datadir={data_dir}",
            f"--basedir={basedir}",
            "--initialize-insecure"
        ], stdout=f, stderr=subprocess.STDOUT)
    print(f"[INFO] Datadir initialized (logs -> {log_file})")

def copy_datadir(src_dir, dest_dir):
    """
    Copy a MySQL datadir from src_dir to dest_dir.
    If dest_dir exists, it will be removed before copying.
    """
    if not os.path.exists(src_dir):
        raise FileNotFoundError(f"Source datadir not found: {src_dir}")

    if os.path.exists(dest_dir):
        print("[INFO] Removing old destination datadir...")
        shutil.rmtree(dest_dir)

    print(f"[INFO] Copying datadir from {src_dir} -> {dest_dir} ...")
    shutil.copytree(src_dir, dest_dir, symlinks=True)
    print("[INFO] Datadir copy complete.")

def start_mysqld(mysqld_path, basedir, data_dir, port, socket, err_log, params, gdb=False, rocks=False, cnf_file=None):
    """Start mysqld, optionally with a config file and/or RocksDB, redirect logs to file."""

    params_list = shlex.split(params) if params else []

    with open(err_log, "w"):
        pass  # truncate file automatically

    # --defaults-file must be the very first option after the binary
    defaults = [f"--defaults-file={cnf_file}"] if cnf_file else []

    mysqld_cmd = (
        [mysqld_path]
        + defaults
        + params_list
        + [
            f"--datadir={data_dir}",
            f"--basedir={basedir}",
            f"--port={port}",
            "--skip-networking=0",
            f"--socket={socket}",
            "--log-error-verbosity=3",
            f"--log-error={err_log}"
        ]
    )

    if rocks:
        mysqld_cmd += ( [
            "--plugin-load-add=RocksDB=ha_rocksdb.so",
            "--rocksdb"
            ] )

    # Convert to a shell-safe command string for gdb
    cmd_str = " ".join(shlex.quote(arg) for arg in mysqld_cmd)
    print(cmd_str)

    # Launch GNOME Terminal with gdb attached
    if gdb:
        proc = subprocess.Popen([
            "gnome-terminal",
            "--",
            "bash", "-c",
            f"gdb -ex 'break main' -ex 'set pagination off' -ex run --args {cmd_str}; exec bash"
        ])
    else:
        proc = subprocess.Popen(mysqld_cmd)

    print(f"[INFO] mysqld started with params={params}")
    print(f"[INFO] mysqld started with RocksDB enabled (pid={proc.pid}), logs -> {err_log}")
    return proc

def wait_for_mysql(basedir, port, user="root", password="", timeout=30):
    """Wait until MySQL server is ready using mysql client."""
    mysql_client = os.path.join(basedir, "bin", "mysql")
    last_error = None

    for i in range(timeout):
        try:
            subprocess.run(
                [mysql_client, f"--user={user}", f"--password={password}", f"--port={port}", "--protocol=tcp", "-e", "SELECT 1"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            print("[INFO] mysqld is ready for queries.")
            return
        except subprocess.CalledProcessError as e:
            last_error = e.stderr.strip()
            if (i + 1) % 5 == 0:  # print only every 5 seconds
                print("[WARN] MySQL not ready yet. Error:", last_error)
            time.sleep(1)

    raise RuntimeError(f"MySQL did not start in time. Last error: {last_error}")

def wait_for_mysql_or_crash(basedir, err_log, port, user="root", password="", timeout=30):
    """
    Wait until MySQL is ready to accept connections, or detect crash from error log.

    Args:
        basedir: MySQL base directory (mysql client in bin/)
        port: MySQL port
        err_log: Path to error log
        timeout: Seconds to wait before giving up
    Raises:
        RuntimeError if MySQL crashes or doesn't start in time
    """
    mysql_client = os.path.join(basedir, "bin", "mysql")
    last_error = None
    start_time = time.time()

    # Open error log to tail
    with open(err_log, "r") as f:
        # Seek to end so we only see new lines
        f.seek(0, os.SEEK_END)

        while True:
            # Check timeout
            if time.time() - start_time > timeout:
                raise RuntimeError(f"MySQL did not start in {timeout}s. Last error: {last_error}")

            # Read new lines from log
            lines = f.readlines()
            for line in lines:
                if "got signal" in line or "Assertion" in line or "Fatal" in line:
                    raise RuntimeError(f"MySQL crashed during startup:\n{line.strip()}")

            # Try connecting to MySQL
            try:
                subprocess.run(
                    [mysql_client, f"--user={user}", f"--password={password}", f"--port={port}", "--protocol=tcp", "-e", "SELECT 1"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )
                print("[INFO] mysqld is ready for queries.")
                return
            except subprocess.CalledProcessError as e:
                last_error = e.stderr.strip()
                # optional: print every few seconds
                if int(1 + time.time() - start_time) % 5 == 0:
                    print("[WAIT] MySQL not ready yet. Last error:", last_error)

            time.sleep(1)

def stop_mysqld(basedir, port, user="root", password=""):
    """
    Stop MySQL server gracefully using mysqladmin.

    Args:
        basedir: MySQL base directory (mysqladmin in bin/)
        port: MySQL port
    """
    mysqladmin = os.path.join(basedir, "bin", "mysqladmin")
    try:
        subprocess.run(
            [mysqladmin, f"--user={user}", f"--password={password}", f"--port={port}", "--protocol=tcp", "shutdown"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        print("[INFO] mysqld stopped gracefully.")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to stop mysqld: {e.stderr.strip()}")

import mysql.connector
from mysql.connector import Error

def open_mysql_connection(args, socket_path, database=None):
    """
    Open a MySQL connection using argparse 'args' and return it.
    """
    try:
        conn_params = {
            "user": args.user,
            "password": args.password,
            "database": database,
            "charset": args.charset or None,
            "ssl_disabled": True,
        }

        if args.socket:
            conn_params["unix_socket"] = socket_path
        else:
            conn_params.update({
                "host": args.host,
                "port": args.port,
            })

        conn = mysql.connector.connect(**conn_params)

        print("[INFO] MySQL connection established.")
        return conn

    except Exception as e:
        raise RuntimeError(f"Failed to connect to MySQL: {e}") from e

def execute_query(conn, query, params=None):
    """
    Execute a SQL query on the given connection.
    Returns fetched results for queries that return rows, otherwise returns affected row count.
    """
    if conn is None or not conn.is_connected():
        raise RuntimeError("MySQL connection is not open.")

    cursor = conn.cursor()
    try:
        cursor.execute(query, params or ())
        # Queries that return results
        if cursor.description:  # SELECT or similar
            result = cursor.fetchall()
        else:
            conn.commit()
            result = cursor.rowcount
    finally:
        cursor.close()
    return result

def execute_sql_file(conn, sql_path, charset):
    """
    Reads a .sql file, splits on semicolons, executes each SQL statement,
    and prints results or affected rows depending on query type.
    """
    with open(sql_path, "r", encoding=charset) as fh:
        sql_text = fh.read()

    # Remove lines starting with optional spaces followed by "-- " or "#"
    sql_lines = [
        line for line in sql_text.splitlines()
        if not line.lstrip().startswith(("--", "#"))
    ]
    cleaned_sql = "\n".join(sql_lines)

    # Split on semicolon, discard blank statements
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]

    for stmt in statements:
        print(f"[SQL] Executing: {stmt}")

        try:
            result = execute_query(conn, stmt)

            # SELECT-like queries return a list of rows
            if isinstance(result, list):
                if result:
                    print("[SQL] Result rows:")
                    for row in result:
                        print("   ", row)
                        #print("==========")
                        #data_list = json.loads(row[0])
                        ## Print each record on a single line
                        #for record in data_list:
                        #    if record is not None:  # Skip the trailing null
                        #        print(json.dumps(record, separators=(',', ':')))
                else:
                    print("[SQL] (No rows returned)")

            # Non-SELECT queries return an integer rowcount
            elif isinstance(result, int):
                print(f"[SQL] Query OK, affected rows: {result}")

            # Fallback (should not happen)
            else:
                print(f"[SQL] Raw result: {result}")

        except Exception as e:
            print(f"[SQL ERROR] {e}")

        print()  # blank line for readability

def close_mysql_connection(conn):
    """
    Close the given MySQL connection.
    """
    if conn is not None and conn.is_connected():
        conn.close()
        print("[INFO] MySQL connection closed.")

def run_shell_script(script_path, basedir, host, port, user, password, datadir, socket_path=None):
    """
    Execute a user-provided bash script with environment variables set.
    Returns (returncode, stdout, stderr).
    """
    if not os.path.exists(script_path):
        return -1, "", f"Script not found: {script_path}"

    env = os.environ.copy()
    env["BASEDIR"] = basedir
    env["HOST"] = host
    env["PORT"] = str(port)
    env["DATADIR"] = datadir
    env["USER"] = user
    env["PASSWORD"] = password
    if socket_path:
        env["SOCKET"] = socket_path

    try:
        proc = subprocess.run(
            ["/bin/bash", script_path],
            env=env,
            capture_output=True,
            text=True,
            check=False
        )
    except Exception as e:
        return -1, "", f"Shell script execution failed: {e}"

    return proc.returncode, proc.stdout, proc.stderr

def extract_errors_from_log(input_file: str, output_fh):
    """
    Reads a log file and writes lines containing 'error' or 'assert'
    (case-insensitive) to the provided open file handle.

    :param input_file: Path to the input log file.
    :param output_fh: Open file handle to write matching lines.
    """
    with open(input_file, "r") as fh:
        for line in fh:
            #if "[Warning]" not in line and "[System]" not in line:
            if "error" in line.lower() or "assert" in line.lower():  # Case-insensitive match
                output_fh.write(line)
