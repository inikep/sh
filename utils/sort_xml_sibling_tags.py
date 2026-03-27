#!/usr/bin/env python3
"""
Parse an XML file and write XML. Optional: sort direct child elements by tag
name (--sort-siblings), mask volatile audit fields (--mask-timestamp-connection),
and pretty-print (default unless --no-indent).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _mask_record_id_text(text: str | None) -> str:
    """e.g. 12_2026-03-27T17:19:38 -> 12_[masked]"""
    if not text or not text.strip():
        return text or ""
    s = text.strip()
    if "_" in s:
        prefix, _ = s.split("_", 1)
        return f"{prefix}_[masked]"
    return "[masked]"


def mask_timestamp_connection(elem: ET.Element) -> None:
    """Replace TIMESTAMP, CONNECTION_ID, RECORD_ID text with stable placeholders (any depth)."""
    for child in list(elem):
        mask_timestamp_connection(child)
    name = _local_tag(elem.tag)
    if name == "TIMESTAMP":
        elem.text = "[masked]"
        for c in list(elem):
            elem.remove(c)
    elif name == "CONNECTION_ID":
        elem.text = "[masked]"
        for c in list(elem):
            elem.remove(c)
    elif name == "RECORD_ID":
        elem.text = _mask_record_id_text(elem.text)
        for c in list(elem):
            elem.remove(c)


def sort_children_by_tag(elem: ET.Element) -> None:
    """Recursively sort direct child elements by tag name (namespace-aware)."""
    for child in list(elem):
        sort_children_by_tag(child)

    children = list(elem)
    if len(children) <= 1:
        return

    for c in children:
        elem.remove(c)

    children.sort(key=lambda e: e.tag)
    for c in children:
        elem.append(c)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-process XML (optional sibling sort, optional audit field masking)."
    )
    parser.add_argument("input", help="Input XML file path")
    parser.add_argument(
        "-o",
        "--output",
        help="Output XML file path (default: stdout)",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Encoding for output file (default: utf-8)",
    )
    parser.add_argument(
        "--no-indent",
        action="store_true",
        help="Do not pretty-print output (smaller file)",
    )
    parser.add_argument(
        "--sort-siblings",
        action="store_true",
        help="Sort direct child elements alphabetically by tag at every level (off by default)",
    )
    parser.add_argument(
        "--mask-timestamp-connection",
        action="store_true",
        help="Mask TIMESTAMP, CONNECTION_ID, RECORD_ID (e.g. 12_ts -> 12_[masked]) for stable diffs",
    )
    args = parser.parse_args()

    try:
        tree = ET.parse(args.input)
    except ET.ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1

    if args.sort_siblings:
        sort_children_by_tag(tree.getroot())

    if args.mask_timestamp_connection:
        mask_timestamp_connection(tree.getroot())

    if not args.no_indent:
        try:
            ET.indent(tree.getroot(), space=" ", level=0)
        except AttributeError:
            pass

    if args.output:
        tree.write(
            args.output,
            encoding=args.encoding,
            xml_declaration=True,
            method="xml",
        )
    else:
        tree.write(sys.stdout.buffer, encoding="utf-8", xml_declaration=True, method="xml")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
