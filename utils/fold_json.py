#!/bin/python
 
import json
import sys

def fold_json(input_file, output_file):
    with open(input_file, "r") as f:
        data = json.load(f)

    with open(output_file, "w") as f:
        for record in data:
             # Dump each record as a single line with spaces after ":" and ","
            json_str = json.dumps(record, separators=(', ', ': '))
            f.write(json_str + '\n')

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fold_json.py <input.json> <output.json>")
        sys.exit(1)

    fold_json(sys.argv[1], sys.argv[2])
    print(f"Folded JSON written to {sys.argv[2]}")

