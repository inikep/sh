#!/bin/python

import os
import argparse
from mysql_utils import *


def print_errors_from_file(input_file: str):
    with open(input_file, "r") as fh:
        for line in fh:
            if "error" in line.lower() or "assert" in line.lower():  # Case-insensitive match
                print(line, end="")  # Print the line directly

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start MySQL with RocksDB, run SQL file, stop MySQL.")
    parser.add_argument("--basedir", required=True, help="MySQL base directory")
    parser.add_argument("--datadir", required=True, help="Path to MySQL data directory")
    parser.add_argument("--port", type=int, default=3307, help="Port for MySQL (default: 3307)")
    parser.add_argument("--host", default="127.0.0.1", help="MySQL base directory")
    parser.add_argument("--init", action="store_true", help="Create a new datadir (default: False)")
    parser.add_argument("--params", default="", help="Extra mysqld command-line parameters")
    parser.add_argument("--gdb", action="store_true", help="Use gdb (default: False)")
    parser.add_argument("--socket", action="store_true", help="Use socket connection (default: False)")
    parser.add_argument("--rocks", action="store_true", help="Turn on MyRocks (default: False)")
    parser.add_argument("--sql", action="append", help="Path to SQL file to run (may be used multiple times)")
    parser.add_argument("--sh", action="append", help="Path to a shell script to execute after MySQL startup (may be used multiple times)")
    parser.add_argument("--user", default="root", help="MySQL base user")
    parser.add_argument("--password", default="", help="MySQL base password")
    parser.add_argument("--charset", default="utf8", help="Change client charset")
    parser.add_argument("--cnf", default=None, help="Path to MySQL config file (my.cnf)")
    parser.add_argument("--database", default=None, help="Default database to USE after connecting")
    args = parser.parse_args()

    base_name = os.path.splitext(os.path.abspath(args.datadir))[0]
    args.datadir = args.datadir.rstrip("/")
    temp_datadir = args.datadir + "_temp"
    err_log = f"{base_name}.log"
    output_file = f"{base_name}.out"
    socket_path = f"{base_name}.socket"

    mysqld_path = find_mysqld(args.basedir)
    if args.init:
        init_datadir(mysqld_path, args.basedir, args.datadir, err_log)

    if not os.path.exists(args.datadir):
        answer = input(f"[WARN] Datadir '{args.datadir}' not found. Initialize it? [y/N] ").strip().lower()
        if answer == "y":
            init_datadir(mysqld_path, args.basedir, args.datadir, err_log)
        else:
            print("[ERROR] Datadir does not exist. Exiting.")
            exit(1)

    conn = None
    with open(output_file, "w") as outfile:
        try:
            copy_datadir(args.datadir, temp_datadir)
            proc = start_mysqld(mysqld_path, args.basedir, temp_datadir, args.port, socket_path, err_log, args.params, args.gdb, args.rocks, cnf_file=args.cnf)

            wait_for_mysql_or_crash(args.basedir, err_log, args.port, user=args.user, password=args.password, timeout=60)
            conn = open_mysql_connection(args, socket_path, database=args.database)

            if args.sql:
                for sql_path in args.sql:
                    if os.path.exists(sql_path):
                        print(f"[INFO] Running SQL file: {sql_path}")
                        execute_sql_file(conn, sql_path, args.charset)
                        close_mysql_connection(conn)
                        conn = open_mysql_connection(args, socket_path, database=args.database)
                    else:
                        print(f"[WARN] SQL file not found: {sql_path}")

            if args.sh:
                for sh_path in args.sh:
                    print(f"[INFO] Running shell script: {sh_path}")
                    rc, out, err = run_shell_script(
                        sh_path,
                        basedir=args.basedir,
                        host=args.host,
                        port=args.port,
                        user=args.user,
                        password=args.password,
                        datadir=temp_datadir,
                        socket_path=socket_path
                    )

                    print(f"[SCRIPT] return code: {rc}")
                    if out:
                        print("[SCRIPT] stdout:\n", out)
                    if err:
                        print("[SCRIPT] stderr:\n", err)

        finally:
            if conn:
                close_mysql_connection(conn)
            stop_mysqld(args.basedir, args.port, user=args.user, password=args.password)
            time.sleep(1)
            extract_errors_from_log(err_log, outfile)
            outfile.flush()
            print_errors_from_file(err_log)
