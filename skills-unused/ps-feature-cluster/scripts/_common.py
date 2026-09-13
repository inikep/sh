"""Shared helpers for ps-feature-cluster scripts. Env-driven, no CLI args."""
import os, re, sys, subprocess

def env(name, default=None, required=False):
    v = os.environ.get(name, default)
    if required and not v:
        sys.stderr.write(f"missing env var ${name}\n")
        sys.exit(2)
    return v

BASE = env('BASE_BRANCH', required=True)
TIP  = env('TIP_BRANCH',  required=True)
WORK = env('WORK_DIR', f'/tmp/ps-feature-cluster-{TIP}')
SEEDS_FILE = env('SEEDS_FILE', f'{WORK}/seeds.tsv')
MIN_AFFINITY    = float(env('MIN_AFFINITY',    '4.0'))
STRONG_AFFINITY = float(env('STRONG_AFFINITY', '10.0'))
MARGIN          = float(env('MARGIN',          '1.3'))

os.makedirs(WORK, exist_ok=True)

def sh(*args, check=True):
    r = subprocess.run(['git'] + list(args), text=True, capture_output=True, errors='replace')
    if check and r.returncode != 0:
        sys.stderr.write(f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}\n")
        sys.exit(1)
    return r

SUBJECT_MARKER_RE = re.compile(r'^\s*(?:\[[^\]\n]{1,96}\]\s*)+')

def strip_subject_markers(subject):
    """Remove leading feature-marker prefixes such as '[foo] [bar] '."""
    return SUBJECT_MARKER_RE.sub('', subject or '').strip()

def commit_subject(c, raw=False):
    """Return the normalized subject by default, preserving old commits.json."""
    subj = c.get('raw_subj' if raw else 'subj', '')
    return subj if raw else strip_subject_markers(subj)
