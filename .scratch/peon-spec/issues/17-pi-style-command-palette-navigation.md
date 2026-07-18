# 17 - Pi-style slash command palette navigation

**What to build:** Make Textual slash suggestions keyboard-selectable and make both shells present same concise command descriptions and candidate hints.

**Blocked by:** none; issue 16 is complete

**Status:** complete

**Tracker label:** `complete`

## Scope

- Open palette when composer contains slash search text.
- Render canonical command, short description, candidate hint, and Reserved state when applicable.
- Highlight one selected result.
- Use Up/Down to cycle visible matches, wrapping at boundaries.
- Preserve selected command across query updates when it remains visible.
- Use Tab to complete selected canonical command without executing it.
- Use Enter to invoke selected command.
- Use Escape to dismiss palette while preserving composer draft.
- Keep mouse optional; keyboard path is primary.
- Feed prompt-toolkit completion from same ordered matches and description metadata.

## Acceptance criteria

- User can type `/`, press Down repeatedly, and execute any visible available command.
- Selection highlight and Enter target always agree.
- Description/candidate search updates list without focus leaving composer.
- Tab inserts canonical name even when match came from candidate or description.
- Reserved row cannot look available; invoking it returns concise unavailable feedback.
- No command list or description drift exists between renderers.

## Test seam

Use Textual app harness for key events and visible rows. Use command catalog tests for match content/order; do not duplicate ranking tests in renderer suite.
