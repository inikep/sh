#!/bin/bash
# usage: killpat.sh REGEX [SIGNAL]
# Kill processes whose command line matches REGEX, never this script or the shell that ran it.
# (`pkill -f PATTERN` inside a tool shell also matches that shell's own command line, which
# contains PATTERN, and kills it.) Write the regex so it does not match itself, e.g. 'mtr_series[.]sh'.
sig=${2:-TERM}
for p in $(pgrep -f "$1"); do
  [ "$p" = "$$" ] || [ "$p" = "$PPID" ] || kill -"$sig" "$p" 2>/dev/null
done
