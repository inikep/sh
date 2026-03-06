#!/bin/python

# Script to manually dump all tables from a MySQL/MyRocks database.
# Dumps both schema and data into a single SQL file, preserving table structure, indexes, and partitioning.
# Handles literal newline conversion, proper semicolons, and optional removal of MySQL version-specific comments.

import re
import argparse
import os
import subprocess
import tempfile
import sys
from mysql_utils import find_mysqld, start_mysqld, wait_for_mysql, stop_mysqld

def uncomment_partition_clause(create_stmt):
    """
    Converts version-specific partition comments into active SQL:
    /*!50100 PARTITION BY ... */ -> PARTITION BY ...
    """
    # Match /*!50100 PARTITION ... */
    pattern = r'/\*\!\d+\s+(PARTITION\s+BY.*?\*/)'
    def repl(m):
        inner = m.group(1)
        # remove the trailing '*/'
        if inner.endswith("*/"):
            inner = inner[:-2]
        return inner.strip()

    return re.sub(pattern, repl, create_stmt, flags=re.DOTALL)

def mysqldump_all_data(basedir, data_dir, port, output_file, db_name="test"):
    mysqld_path = find_mysqld(basedir)

    output_file = os.path.abspath(output_file)
    base_name, _ = os.path.splitext(output_file)
    log_file = base_name + ".log"

    proc = start_mysqld(
        mysqld_path=mysqld_path,
        basedir=basedir,
        data_dir=data_dir,
        port=port,
        err_log=log_file,
        params=""
    )

    try:
        wait_for_mysql(basedir, port)

        mysqldump = os.path.join(basedir, "bin", "mysqldump")
        with open(output_file, "w") as f_out:
            subprocess.check_call([
                mysqldump,
                "-u", "root",
                f"--port={port}",
                "--protocol=tcp",
                "--routines",      # include stored procedures/functions
                "--triggers",      # include triggers
                "--all-tablespaces",
                "--databases", db_name  # include entire database
            ], stdout=f_out)

        print(f"[INFO] All data from database '{db_name}' dumped to {output_file}")

    finally:
        stop_mysqld(proc)

def quote_value(val, is_binary=False):
    """Quote a value for SQL insert."""
    if val is None or val.upper() == "NULL":
        return "NULL"
    if is_binary:
        # Escape single quotes
        val = val.replace("'", "''")
        return f"_binary '{val}'"
    val = val.replace("'", "''")
    return f"'{val}'"

def dump_all_tables(basedir, data_dir, port, output_file, db_name, myextra):
    mysqld_path = find_mysqld(basedir)

    output_file = os.path.abspath(output_file)
    base_name, _ = os.path.splitext(output_file)
    log_file = base_name + ".log"

    proc = start_mysqld(
        mysqld_path=mysqld_path,
        basedir=basedir,
        data_dir=data_dir,
        port=port,
        err_log=log_file,
        params=myextra
        #params="--loose-rocksdb_validate_tables=2"
    )

    try:
        wait_for_mysql(basedir, port, timeout=60)
        mysql_client = os.path.join(basedir, "bin", "mysql")

        # Get list of tables
        tables_cmd = [
            mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp",
            "-NBe", f"SELECT table_name FROM information_schema.tables WHERE table_schema='{db_name}';"
        ]
        tables = subprocess.check_output(tables_cmd, text=True).splitlines()

        with open(output_file, "w", encoding="utf-8") as f_out:
            for table in tables:
                # --- CREATE TABLE ---
                create_cmd = [
                    mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp",
                    "-NBe", f"SHOW CREATE TABLE `{db_name}`.`{table}`;"
                ]
                output = subprocess.check_output(create_cmd, text=True)
                _, create_stmt = output.split("\t", 1)
                create_stmt = create_stmt.replace("\\n", "\n").rstrip()
                if not create_stmt.endswith(";"):
                    create_stmt += ";"
                create_stmt = uncomment_partition_clause(create_stmt)
                f_out.write(f"{create_stmt}\n\n")

                # --- Get columns and detect blob/text columns ---
                cols_cmd = [
                    mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp",
                    "-NBe",
                    f"SELECT COLUMN_NAME, DATA_TYPE, GENERATION_EXPRESSION "
                    f"FROM information_schema.COLUMNS "
                    f"WHERE table_schema='{db_name}' AND table_name='{table}';"
                ]
                cols_output = subprocess.check_output(cols_cmd, text=True).splitlines()

                columns = []
                binary_columns = set()
                for line in cols_output:
                    parts = line.split("\t")
                    if len(parts) < 3:
                        parts += [""] * (3 - len(parts))
                    col_name, data_type, gen_expr = parts
                    # Skip generated columns
                    if gen_expr in ("", None, "NULL"):
                        columns.append(col_name)
                        if data_type in ("blob", "longblob", "mediumblob", "tinyblob",
                                            "binary", "varbinary", "text", "tinytext",
                                            "mediumtext", "longtext"):
                            binary_columns.add(col_name)

                if not columns:
                    continue  # nothing to insert

                # --- Stream SELECT results row by row ---
                select_cols = [f"`{col}`" for col in columns]
                select_cmd = [
                    mysql_client, "-u", "root", f"--port={port}", "--protocol=tcp",
                    "--binary-mode",  # ensures raw bytes
                    "-NBe",
                    f"SELECT {', '.join(select_cols)} FROM `{db_name}`.`{table}`;"
                ]

                with subprocess.Popen(select_cmd, stdout=subprocess.PIPE) as p:
                    for raw_line in p.stdout:
                        # Decode raw bytes safely
                        line = raw_line.decode("utf-8", errors="backslashreplace").rstrip("\n")
                        values = line.split("\t")
                        quoted_values = [
                            quote_value(val, is_binary=(col in binary_columns))
                            for val, col in zip(values, columns)
                        ]
                        f_out.write(f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in columns)}) "
                                    f"VALUES ({', '.join(quoted_values)});\n")
                f_out.write("\n")

        print(f"[INFO] All schemas and data dumped to {output_file}")

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed with exit code {e.returncode}")
        print(f"[ERROR] Command: {' '.join(e.cmd)}")
        if e.output:
            print(f"[ERROR] Output:\n{e.output}")

    finally:
        stop_mysqld(proc)


def main():
    parser = argparse.ArgumentParser(description="Dump all tables with schema and data")
    parser.add_argument("--basedir", required=True, help="MySQL base directory")
    parser.add_argument("--datadir", required=True, help="Path to MySQL data directory")
    parser.add_argument("--port", type=int, default=3307, help="Port for MySQL (default: 3307)")
    parser.add_argument("--output-file", required=True, help="Path to output .sql file")
    parser.add_argument("--database", default="test", help="Database name (default: test)")
    parser.add_argument("--mysqldump", action="store_true", default=False, help="Use mysqldump for dumping table data instead of manual SELECTs.")
    parser.add_argument("--myextra_file", default=None, help="File with additional mysqld options (default: False)")
    args = parser.parse_args()

    if not os.path.isdir(args.basedir):
        print(f"[ERROR] basedir does not exist: {args.basedir}")
        sys.exit(1)

    if not os.path.isdir(args.datadir):
        print(f"[ERROR] datadir does not exist: {args.datadir}")
        sys.exit(1)

    # Load extra mysqld options if provided
    myextra = None
    if args.myextra_file and os.path.exists(args.myextra_file):
        with open(args.myextra_file, "r") as f:
            # Join lines into a single string of options
            myextra = " ".join(line.strip() for line in f if line.strip())
        print(f"[INFO] Loaded extra mysqld options: {myextra}")

    if args.mysqldump:
        mysqldump_all_data(args.basedir, args.datadir, args.port, args.output_file, args.database)
    else:
        dump_all_tables(args.basedir, args.datadir, args.port, args.output_file, args.database, myextra)

if __name__ == "__main__":
    main()
