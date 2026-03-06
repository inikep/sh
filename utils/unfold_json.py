#!/bin/python

import json
import sys

def unfold_json(input_file, output_file):
    with open(input_file, "r") as f:
        data = json.load(f)

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)  # indent adds newlines/EOLs

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python unfold.py <input.json> <output.json>")
        sys.exit(1)

    unfold_json(sys.argv[1], sys.argv[2])
    print(f"Written pretty JSON to {sys.argv[2]}")

