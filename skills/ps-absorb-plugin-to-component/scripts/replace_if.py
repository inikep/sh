#!/usr/bin/env python3
"""Transform helper: stdin must be exactly blob EXPECTED (REV:PATH or blob id); outputs blob NEW.
Use when a file has a single pre-conversion version, so the conversion result itself is the
per-commit target. Any other input aborts (it means the file changed and needs a real transform)."""
import subprocess, sys
def rev(x): return subprocess.run(['git','rev-parse',x],capture_output=True,check=True,text=True).stdout.strip()
exp, new = rev(sys.argv[1]), rev(sys.argv[2])
data = sys.stdin.buffer.read()
got = subprocess.run(['git','hash-object','--stdin'],input=data,capture_output=True,check=True).stdout.decode().strip()
if got != exp: sys.exit(f'input blob {got[:12]} != expected {exp[:12]}')
sys.stdout.buffer.write(subprocess.run(['git','cat-file','blob',new],capture_output=True,check=True).stdout)
