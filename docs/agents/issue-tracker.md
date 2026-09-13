# Issue tracker: GitHub

Track this repository's maps and decision tickets in GitHub Issues at
`rickono/cookbook-mcp`, using the authenticated `gh` CLI. Refer to issues by linked
title in human-facing text. Use a body file or JSON input for multiline writes.

## Wayfinding operations

- Create the map with `wayfinder:map`. Keep its Destination, Notes, Decisions so
  far, Not yet specified, and Out of scope sections. Open tickets live in the
  sub-issue relationship, not an additional list in the map body.
- Create child issues with `wayfinder:research`, `wayfinder:prototype`,
  `wayfinder:grilling`, or `wayfinder:task`. Link each child with
  `POST /repos/rickono/cookbook-mcp/issues/{map_number}/sub_issues`, passing
  `sub_issue_id` as the child's numeric database ID.
- After all children exist, add each blocking edge with
  `POST /repos/rickono/cookbook-mcp/issues/{child_number}/dependencies/blocked_by`,
  passing `issue_id` as the blocker's numeric database ID. Issue numbers and
  node IDs are not database IDs.
- Query the map's sub-issues and their current issue records. The frontier is
  open children with no assignees and zero open blockers, in sub-issue order.
  `issue_dependencies_summary.blocked_by` reports the open-blocker count.
- Claim before work by assigning the issue to the owner driving this map:
  `gh issue edit NUMBER --add-assignee @me`.
- Resolve with an answer comment, then close the ticket. Re-read the map before
  appending a single linked-title gist to Decisions so far, preserving other
  sessions' edits. Leave the detailed answer in the ticket.
- Only fall back to body relationships if GitHub lacks the native relationship
  capability. Document the verified limitation before changing conventions.

Research assets belong on isolated `research/<name>` branches, linked from their
tickets. Keep source books, page images, extracted passages, raw experiment
outputs, credentials, and incident evidence outside Git and GitHub issues.
Only source-safe research summaries belong on these branches.

## Other issue operations

Use `gh issue view NUMBER --comments` to read a ticket and its resolutions.
List current labels and assignees when selecting work. A human-in-the-loop ticket
requires the owner's live input; a research finding does not settle their policy
preferences. Pull requests are not a triage request surface for this repository.
