#!/usr/bin/env python3
"""
Parse an XML file and write a new XML file where, at every element,
direct child elements are ordered alphabetically by tag name.

Text nodes, tails, comments, and attributes are preserved as produced
by ElementTree (attribute order is not defined by XML and may change).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET


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
        description="Write XML with sibling tags sorted alphabetically at each level."
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
    args = parser.parse_args()

    try:
        tree = ET.parse(args.input)
    except ET.ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1

    sort_children_by_tag(tree.getroot())

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
