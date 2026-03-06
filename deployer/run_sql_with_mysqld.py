#!/bin/python

import re
import os
import copy
import argparse
import mysql.connector
from mysql.connector import Error
from mysql_utils import find_mysqld, init_datadir, start_mysqld, wait_for_mysql, stop_mysqld

def split_insert(sql):
    """
    Splits a multi-row INSERT INTO ... VALUES (...), (...), ...;
    into multiple single-row INSERT statements.
    """
    sql = sql.strip().rstrip(";")

    # Match "INSERT INTO ... (columns) VALUES"
    match = re.match(r"^(INSERT\s+INTO\s+.+?\)\s+VALUES)\s*(.*)$",
                     sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return [sql + ";"]  # not an INSERT VALUES statement, return unchanged

    insert_head, values_part = match.groups()

    # Split top-level (...) groups after VALUES
    rows = []
    depth = 0
    buf = ""
    for ch in values_part:
        if ch == "(":
            depth += 1
        if ch == ")":
            depth -= 1
        buf += ch
        if depth == 0 and buf.strip():
            rows.append(buf.strip().lstrip(","))
            buf = ""

    return [f"{insert_head} {row.strip()};" for row in rows if row.strip()]


def run_sql_file(basedir, sql_files, myextra, table_name, host, port, user, run_last):
    base_name = os.path.splitext(sql_files[0])[0]
    if table_name:
        base_name = f"{base_name}-{table_name}"
    else:
        base_name = f"{base_name}-all"
    sql_log_file = f"{base_name}.sql"
    sql_err_file = f"{base_name}.mysql_error"

    print(f"[INFO] Running SQL file (persistent connection to 'test'): {sql_files} -> {sql_log_file}")

    # Read and join multiple SQL files, then split into statements
    sql_commands, statement = [], ""
    for sql_file in args.sql:
        print(f"[INFO] Reading {sql_file} ...")
        with open(sql_file, "r") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("--") or stripped.startswith("#") or not stripped:
                    continue
                statement += line
                if stripped.endswith(";"):
                    sql_commands.append(statement.strip())
                    statement = ""
    if statement:
        sql_commands.append(statement.strip())

    # Expand multi-row INSERTs
    expanded_commands = []
    for cmd in sql_commands:
        expanded_commands.extend(split_insert(cmd))
    sql_commands = expanded_commands

    # Filter by table if requested
    if table_name:
        regex = re.compile(rf"\b{re.escape(table_name)}\b", re.IGNORECASE)
        sql_commands = [cmd for cmd in sql_commands if regex.search(cmd)]
        print(f"[INFO] Filtering queries for table '{table_name}', found {len(sql_commands)} matching statements")

    #print("\n[DEBUG] Final SQL commands to execute:")
    #for i, cmd in enumerate(sql_commands, start=1):
    #    print(f"--- Command #{i} ---\n{cmd}\n")

    with open(sql_log_file, "w") as log, open(sql_err_file, "w") as err_log:
        try:
            # Open one fixed connection (disable SSL to avoid wrap_socket error)
            conn = mysql.connector.connect(user=user, host=host, port=port, ssl_disabled=True)
            cursor = conn.cursor()

            cursor.execute("CREATE DATABASE IF NOT EXISTS test;")
            cursor.execute("USE test;")

            log.write(f"# MYEXTRA={myextra}\n")

            for cmd in sql_commands:
                log.write(f"{cmd}\n")
                log.flush()
                try:
                    cursor.execute(cmd)
                    if cursor.with_rows:
                        rows = cursor.fetchall()
                        col_names = [d[0] for d in cursor.description]
                        # Log column names as comment
                        log.write("# " + "\t".join(col_names) + "\n")
                        # Log each row as comment
                        for row in rows:
                            log.write("# " + "\t".join(str(v) for v in row) + "\n")
                    conn.commit()

                    # Execute last failing (?) sql command after each statement (if table_name is set)
                    if table_name and run_last:
                        # cmd = f"CHECK TABLE {table_name};"
                        cmd = sql_commands[-1] if sql_commands else None
                        log.flush()
                        try:
                            cursor.execute(cmd)
                            if cursor.with_rows:
                                rows = cursor.fetchall()
                            conn.commit()
                        except Error as e:
                            log.write(f"{cmd}\n")
                            raise

                except Error as e:
                    log.write(f"# [ERROR] Failed query:\n# {cmd}\n# [ERROR MESSAGE] {e}\n")
                    log.flush()

                    err_log.write(f"[ERROR] Failed query:\n{cmd}\n[ERROR MESSAGE] {e}\n\n")
                    err_log.flush()

                    if "2013: Lost connection to MySQL server during query" in str(e):
                        print("[FATAL] Lost connection during query, aborting loop.")
                        break
        except Error as e:
            log.write(f"# [FATAL] Could not connect: {e}\n")
            err_log.write(f"[FATAL] Could not connect: {e}\n")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    print(f"[INFO] SQL execution finished. Results in {sql_log_file}, errors in {sql_err_file}")
    return sql_commands

def run_sql_minimal_error(sql_commands, min_file, host, port, user="root"):
    """
    Minimizes sql_commands to the smallest set that still produces an error,
    and saves the minimal set to `sql_log_file.min.sql`.
    """
    def has_error(cmd_list):
        """Returns True if executing cmd_list triggers any error in results or exceptions"""
        try:
            conn = mysql.connector.connect(host=host, port=port, user=user, ssl_disabled=True)
            cursor = conn.cursor()

            cursor.execute("DROP DATABASE IF EXISTS test;")
            cursor.execute("CREATE DATABASE test;")
            cursor.execute("USE test;")
            conn.commit()

            error_found = False
            for cmd in cmd_list:
                try:
                    cursor.execute(cmd)
                    if cursor.with_rows:
                        rows = cursor.fetchall()
                        for row in rows:
                            if "error" in " ".join(str(v) for v in row).lower():
                                error_found = True
                                break
                    if error_found:
                        break
                    conn.commit()
                except Error:
                    # error_found = True
                    break

            cursor.close()
            conn.close()
            return error_found
        except Error as e:
            print(f"[FATAL] Could not connect: {e}")
            return False

    # Make a copy of commands to modify
    minimal_commands = copy.deepcopy(sql_commands)

    # Estimate total iterations as the original number of queries
    total_iterations = len(minimal_commands)
    iteration_count = 0
    removed_count = 0

    # Iteratively remove queries from end to start
    i = len(minimal_commands) - 1
    while i >= 0:
        iteration_count += 1
        print(f"[INFO] Iteration {iteration_count}/{total_iterations}, testing removal of query {i+1}, Total queries removed: {removed_count}")
        print(f"[TESTING] {minimal_commands[i]}\n")
        test_commands = minimal_commands[:i] + minimal_commands[i+1:]
        if has_error(test_commands):
            print(f"[REMOVED] Query {i+1}:\n")
            # Removing this query still causes an error → drop it
            minimal_commands = test_commands
            removed_count += 1
        i -= 1

    # Save minimal set to file
    with open(min_file, "w") as f:
        for cmd in minimal_commands:
            f.write(cmd.strip() + "\n\n")

    print(f"[INFO] Minimal failing set saved to {min_file}")
    return minimal_commands


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start MySQL with RocksDB, run SQL file, stop MySQL.")
    parser.add_argument("--basedir", required=True, help="MySQL base directory")
    parser.add_argument("--table_name", default=None, help="MySQL base directory")
    parser.add_argument("--datadir", required=True, help="Path to MySQL data directory")
    parser.add_argument("--sql", required=True, action="append",
                        help="Path to SQL file to execute (can be given multiple times)")
    parser.add_argument("--port", type=int, default=3307, help="Port for MySQL (default: 3307)")
    parser.add_argument("--host", default="127.0.0.1", help="MySQL base directory")
    parser.add_argument("--myextra_file", default=None, help="File with additional mysqld options (default: False)")
    parser.add_argument("--reduce", action="store_true", help="Enable reduction (default: False)")
    parser.add_argument("--run_last", action="store_true", help="Run last SQL command trying to crash faster")

    args = parser.parse_args()
    table_name = args.table_name

    base_name = os.path.abspath(args.sql[0])
    base_name = os.path.splitext(base_name)[0]
    if table_name:
        base_name = f"{base_name}-{table_name}"
    else:
        base_name = f"{base_name}-all"
    mysqld_log = f"{base_name}.mysqld"

    # Load extra mysqld options if provided
    myextra = None
    if args.myextra_file and os.path.exists(args.myextra_file):
        with open(args.myextra_file, "r") as f:
            # Join lines into a single string of options
            myextra = " ".join(line.strip() for line in f if line.strip())
        print(f"[INFO] Loaded extra mysqld options: {myextra}")

    mysqld_path = find_mysqld(args.basedir)
    init_datadir(mysqld_path, args.basedir, args.datadir, mysqld_log)
    proc = start_mysqld(mysqld_path, args.basedir, args.datadir, args.port, mysqld_log, myextra)
    try:
        wait_for_mysql(args.basedir, args.port)
        sql_commands = run_sql_file(args.basedir, args.sql, myextra, args.table_name, args.host, args.port, "root", args.run_last)
        if args.reduce:
            run_sql_minimal_error(sql_commands, f"{base_name}-mini.sql", args.host, args.port)
    finally:
        stop_mysqld(proc)
        # Print errors from mysqld log
        with open(mysqld_log, "r") as f:
            for line in f:
                if "[ERROR]" in line:
                    print(line.strip())
