#!/bin/bash

if [ $# -lt 1 ]; then
  echo "usage: $0 [branch_name]"
  exit
fi

set -u

readonly BRANCH=$1

function create_git_gca_worktree ()
{
    local lower_base_branch=$1
    local lower_branch=$2
    local higher_branch=$3

    local gca_rev
    gca_rev="$(git rev-list "$lower_base_branch" ^"$higher_branch" --first-parent --topo-order \
        | tail -1)^"

    echo "Creating $lower_branch from $lower_base_branch for merge to $higher_branch at $gca_rev"

    git checkout -b "$lower_branch" "$gca_rev"
}

git checkout -b "$BRANCH-trunk" percona/trunk
create_git_gca_worktree "percona/8.0" "$BRANCH-8.0" "$BRANCH-trunk"
