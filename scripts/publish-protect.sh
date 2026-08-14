#!/usr/bin/env bash
#
# Apply branch protection to main. Run this the moment the repo goes public.
#
# Why it is a script and not a setting already in place: rulesets and branch
# protection return 403 on a free private repo. They unlock at the instant the
# repo becomes public -- which is precisely the instant an unprotected main
# branch starts to matter. There is a window between "public" and "protected",
# and this script exists to make it as short as possible.
#
#   ./scripts/publish-protect.sh              # show what would change
#   ./scripts/publish-protect.sh --apply      # do it
#
# NOTE: this has never been executed -- it cannot be, until the repo is public.
# Read the output of the dry run before trusting it, and verify in the web UI
# afterwards. Do not treat a clean exit as proof.

set -euo pipefail

REPO="${REPO:-gaaaabeee/statementproof}"
APPLY=""
[ "${1:-}" = "--apply" ] && APPLY=1

# Every job that must pass before anything merges. The matrix produces one
# context per combination, and they must be listed individually: a context that
# is not named here is not required, and a parser bug that only shows on
# Windows or on 3.9 would merge unnoticed.
CONTEXTS=(
  "no-secrets"
  "test (ubuntu-latest, 3.9)"  "test (ubuntu-latest, 3.12)"
  "test (macos-latest, 3.9)"   "test (macos-latest, 3.12)"
  "test (windows-latest, 3.9)" "test (windows-latest, 3.12)"
)

checks_json=$(printf '%s\n' "${CONTEXTS[@]}" \
  | python3 -c 'import json,sys; print(json.dumps([{"context":l.strip()} for l in sys.stdin if l.strip()]))')

read -r -d '' RULESET <<JSON || true
{
  "name": "protect-main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": true,
        "require_last_push_approval": true,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash", "merge"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": ${checks_json}
      }
    }
  ]
}
JSON

echo "repo:      $REPO"
echo "ruleset:   protect-main (active, applies to the default branch)"
echo
echo "  - no direct pushes to main; a pull request is required"
echo "  - 1 approving review, and it must come from a CODEOWNER (you)"
echo "  - approvals are dismissed when new commits are pushed"
echo "  - the last push must itself be approved, so a contributor cannot"
echo "    approve, then push again before merging"
echo "  - all review threads resolved"
echo "  - branch must be up to date with main before merging"
echo "  - force-push and branch deletion blocked"
echo "  - required to pass: ${#CONTEXTS[@]} checks, including no-secrets"
echo

if [ -z "$APPLY" ]; then
  echo "dry run. re-run with --apply to make these changes."
  exit 0
fi

visibility=$(gh api "repos/$REPO" --jq .visibility)
if [ "$visibility" != "public" ]; then
  echo "repo is still '$visibility' -- rulesets need a public repo (or GitHub Pro)." >&2
  echo "make it public first, then run this immediately." >&2
  exit 1
fi

echo "$RULESET" | gh api "repos/$REPO/rulesets" --method POST --input - >/dev/null
echo "ruleset applied."

# A fork PR can run workflows. Requiring approval means a stranger's first PR
# cannot execute anything in this repo's Actions until you have read the diff.
gh api "repos/$REPO/actions/permissions/workflow" --method PUT \
  -F default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false >/dev/null
echo "workflow token set to read-only; Actions cannot approve PRs."

gh api "repos/$REPO" --method PATCH \
  -F allow_auto_merge=false \
  -F delete_branch_on_merge=true \
  -F allow_update_branch=true >/dev/null
echo "auto-merge disabled."

echo
echo "Now verify by hand, because this script has never been tested:"
echo "  https://github.com/$REPO/settings/rules"
echo "  https://github.com/$REPO/settings/actions"
echo
echo "Still to set in the web UI (no stable API):"
echo "  Actions > General > 'Require approval for all external contributors'"
