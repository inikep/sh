#!/bin/bash

if [ $# -lt 2 ]; then
  echo "usage: $0 [branch_name] <lowest_version=5.6>"
  exit
fi

set -u

readonly BRANCH=$1
readonly LOWEST_VERSION_ARG=$2

readonly DEFAULT_LOWEST_VERSION="5.6"

if [ "$LOWEST_VERSION_ARG" = "" ]; then
    echo "Creating branches starting at $DEFAULT_LOWEST_VERSION"
    LOWEST_VERSION="$DEFAULT_LOWEST_VERSION"
else
    LOWEST_VERSION="$LOWEST_VERSION_ARG"
fi

if [ "$LOWEST_VERSION" != "5.6" ] && [ "$LOWEST_VERSION" != "5.7" ]; then
    echo "Only 5.6 and 5.7 are valid lowest versions"
    exit 1
fi

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

git checkout -b "$BRANCH-8.0" percona/8.0
create_git_gca_worktree "percona/5.7" "$BRANCH-5.7" "$BRANCH-8.0"
if [ "$LOWEST_VERSION" = "5.6" ]; then
   create_git_gca_worktree "percona/5.6" "$BRANCH-5.6" "$BRANCH-5.7"
fi
