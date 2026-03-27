#!/usr/bin/env python3

import argparse
import json

_MASK_KEYS = frozenset({"timestamp", "connection_id"})


def mask_timestamp_connection_fields(obj, mask="<masked>"):
    """Return a deep copy with timestamp and connection_id replaced at any depth."""
    if isinstance(obj, dict):
        return {
            k: (mask if k in _MASK_KEYS else mask_timestamp_connection_fields(v, mask))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_timestamp_connection_fields(i, mask) for i in obj]
    return obj


def collect_class_event_pairs(data):
    pairs = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                c, e = item.get("class"), item.get("event")
                if c is not None and e is not None:
                    pairs.add((str(c), str(e)))
    elif isinstance(data, dict):
        c, e = data.get("class"), data.get("event")
        if c is not None and e is not None:
            pairs.add((str(c), str(e)))
    return pairs


def print_class_event_pairs(pairs):
    print(f"[INFO] unique class/event pairs: {len(pairs)}")
    for c, e in sorted(pairs):
        print(f"--- {c}/{e} ---")


def unfold_json(
    input_file,
    output_file,
    class_event_pairs=False,
    mask_timestamp_connection=False,
):
    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)

    if mask_timestamp_connection:
        data = mask_timestamp_connection_fields(data)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Written pretty JSON to {output_file}")
    if class_event_pairs:
        print_class_event_pairs(collect_class_event_pairs(data))


def main():
    parser = argparse.ArgumentParser(
        description="Pretty-print JSON (unfold). Optional audit class/event pair listing."
    )
    parser.add_argument("input_file", help="Input JSON path")
    parser.add_argument("output_file", help="Output JSON path")
    parser.add_argument(
        "--class-event-pairs",
        action="store_true",
        help="After writing, print unique (class, event) pairs from audit-style objects.",
    )
    parser.add_argument(
        "--mask-timestamp-connection",
        action="store_true",
        help="Replace timestamp and connection_id with '<masked>' at any depth before writing.",
    )
    args = parser.parse_args()
    unfold_json(
        args.input_file,
        args.output_file,
        class_event_pairs=args.class_event_pairs,
        mask_timestamp_connection=args.mask_timestamp_connection,
    )


if __name__ == "__main__":
    main()
