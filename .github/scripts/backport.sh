#!/usr/bin/env bash
# Prints the backports that .github/workflows/backport.yml opens for one event,
# as a JSON array with one {pr, target, milestone, milestone_title} object per
# release branch. milestone is the milestone number, 0 for none.
#
#   PR=<number> backport.sh       for a merged PR
#   ISSUE=<number> backport.sh    for a closed issue that got a milestone; covers
#                                 each PR merged to main that closed it
#
# GH_REPO (owner/name) names the repository and GH_TOKEN authenticates.
#
# A merged PR backports to:
# - release/X.Y.x for each open patch milestone X.Y.Z (Z above 0) on the PR or on
#   an issue it closes, when the PR merged to main;
# - each branch named by a `backport release/X.Y.x` label on the PR.
# It skips a branch that does not exist, and a branch that already has an open or
# merged backport PR from backport-<PR>-to-<branch>, the branch_name the workflow
# gives the action. The milestone is the lowest patch milestone of that
# branch that named it, else the lowest open patch milestone of that branch, else
# none. A milestone title must be exactly X.Y.Z; "v0.18.1" is not a patch milestone.
#
# The GraphQL queries are single-quoted because $owner and the rest are GraphQL
# variables, which gh fills from its -f and -F flags.
# shellcheck disable=SC2016
set -euo pipefail
# Without this, set -e does not apply inside $(...), so a failed gh call there
# would return its error text as data.
shopt -s inherit_errexit

# Every lookup is a plain assignment, never a condition, so a failed gh call
# stops the script instead of reading as "no backport".

closing_prs() {
  local data
  data=$(gh api graphql -F owner='{owner}' -F name='{repo}' -F issue="$1" -f query='
    query($owner: String!, $name: String!, $issue: Int!) {
      repository(owner: $owner, name: $name) {
        issue(number: $issue) {
          closedByPullRequestsReferences(first: 100, includeClosedPrs: true) {
            nodes { number merged baseRefName repository { nameWithOwner } }
          }
        }
      }
    }' --jq '[.data.repository.issue.closedByPullRequestsReferences.nodes[]
             | select(.merged and .baseRefName == "main"
                      and .repository.nameWithOwner == env.GH_REPO)
             | .number] | join(" ")')
  if [[ -z "$data" ]]; then
    echo "::warning::Issue #$1 has no merged PR to main that closes it; no backport opened." >&2
  fi
  echo "$data"
}

# Prints one line per candidate target: "<branch> <exists> <milestone number>
# <milestone title>", with "0" for the number when the target gets no milestone.
candidates() {
  gh api graphql -F owner='{owner}' -F name='{repo}' -F pr="$1" -f query='
    query($owner: String!, $name: String!, $pr: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $pr) {
          baseRefName
          labels(first: 100) { nodes { name } }
          milestone { number title state }
          closingIssuesReferences(first: 100) { nodes { milestone { number title state } } }
        }
        milestones(states: OPEN, first: 100) { nodes { number title } }
        refs(refPrefix: "refs/heads/release/", first: 100) { nodes { name } }
      }
    }' --jq '
    def patch: test("^[0-9]+\\.[0-9]+\\.[1-9][0-9]*$");
    def branch: .title | capture("^(?<x>[0-9]+)\\.(?<y>[0-9]+)\\.") | "release/\(.x).\(.y).x";
    def version: .title | split(".") | map(tonumber);
    .data.repository as $repo
    | $repo.pullRequest as $pr
    | ($repo.milestones.nodes | map(select(.title | patch)) | sort_by(version)) as $open
    | (if $pr.baseRefName == "main"
         then [$pr.milestone] + [$pr.closingIssuesReferences.nodes[].milestone]
         else [] end
       | map(select(. != null and .state == "OPEN" and (.title | patch)))
       | unique_by(.number) | sort_by(version)) as $named
    | ($repo.refs.nodes | map("release/" + .name)) as $refs
    | [($named[] | branch),
       ($pr.labels.nodes[].name | capture("^backport (?<t>release/[^ ]+)$").t)]
    | unique[]
    | . as $t
    | (([$named[], $open[]] | map(select(branch == $t)) | first)
       // {number: 0, title: ""}) as $m
    | "\($t) \($refs | index($t) != null) \($m.number) \($m.title)"'
}

backports_for() {
  local pr="$1" lines target exists number title count
  lines=$(candidates "$pr")
  while read -r target exists number title; do
    [[ -n "$target" ]] || continue
    if [[ "$exists" != "true" ]]; then
      echo "::warning::#$pr names $target, which does not exist; not backported there." >&2
      continue
    fi
    # A backport PR closed without merging does not count, so a retry can open one.
    count=$(gh pr list --repo "$GH_REPO" --head "backport-$pr-to-$target" \
      --state all --json state --jq 'map(select(.state != "CLOSED")) | length')
    if [[ "$count" != "0" ]]; then
      echo "#$pr already has a backport PR to $target." >&2
      continue
    fi
    jq -nc --argjson pr "$pr" --arg target "$target" --argjson number "$number" \
      --arg title "$title" '{pr: $pr, target: $target, milestone: $number, milestone_title: $title}'
  done <<<"$lines"
}

if [[ -n "${ISSUE:-}" ]]; then
  prs=$(closing_prs "$ISSUE")
else
  prs="${PR:?set PR or ISSUE}"
fi
out=""
for pr in $prs; do
  out+=$(backports_for "$pr")$'\n'
done
jq -sc '.' <<<"$out"
