# 15 - Normalize assistant transcript background and trailing bar

**What to fix:** Make assistant transcript rows use the same resolved background
as the transcript widget and remove the gray trailing strip at the right edge.
The user reference is the Pi-style terminal view: user messages have a gray
full-width block, while assistant messages sit on the normal terminal surface
without a second dark or gray surface.

**Status:** complete

## Symptoms

- Assistant output can render on a deep-black surface instead of the normal
  transcript background.
- A gray bar can remain after the assistant text to the right edge of the row.
- The issue is visible at narrow terminal widths and can survive a logical
  inspection that only checks message roles.
- The preceding user message is not required for the background mismatch.

## Reproduction

Run the narrow renderer probe or the focused regression test:

```text
uv run --no-sync pytest tests/test_textual_tui.py -q -k assistant_background
```

The equivalent minimized scenario is a `TextualPeonApp` test harness at
`size=(45, 20)` that appends `Hello! How can I help you today?` as an
assistant message and inspects every visible assistant strip, including the
wrapper rows and trailing cells. It also requires that no rendered segment
contain `\n` or `\r`, because either control can move a real terminal cursor
before the row's trailing cells are repainted.

The pre-fix probe was red with this observation:

```text
screen= Color(18, 18, 18)
widget= Color(18, 18, 18)
assistant_rows= ... Color('default', ColorType.DEFAULT) ...
AssertionError: assistant cells do not resolve to the transcript background
```

The minimized case was deterministic across three runs, both with and without
the preceding `hello` user message.

The recurrence was also deterministic at `(92, 20)`. The assistant content
strip contained a segment shaped like this even though its reported cell width
and background were correct:

```text
"Hello! How can I help you today?\n                         "
```

That hidden newline explains why renderer and SVG checks passed while the real
terminal retained a gray suffix.

## Ranked hypotheses

1. `bgcolor="default"` is a terminal-default reset, not inheritance from the
   Textual widget. Prediction: replacing it with the resolved transcript
   background makes every assistant segment match the widget.
2. Textual's trailing-cell extension or the later padding/crop path restyles
   the right side. Prediction: content cells match after hypothesis 1 while
   the final cells still differ; applying the resolved background to the final
   strip fixes the remaining bar.
3. The screen and transcript backgrounds differ. The probe currently falsifies
   this: both resolve to `Color(18, 18, 18)`.
4. Cached line roles or user styling leak into assistant rows. The minimized
   probe currently falsifies this: all affected rows are tagged `assistant`.
5. The terminal/compositor renders Rich's default color differently from the
   Textual CSS background. This is likely the visible manifestation of
   hypothesis 1 and will be checked with the explicit resolved color.

## Task tracking

- [x] Build a fast, deterministic renderer-level repro.
- [x] Reproduce at narrow width and confirm the failure without a user row.
- [x] Add a regression test for resolved assistant backgrounds and trailing
  cells.
- [x] Fix the assistant role background at the renderer seam.
- [x] Verify the original two-message scenario at narrow and normal widths.
- [x] Run focused tests, full tests, mypy, build, diagnostics, and diff checks.
- [x] Remove temporary debug probes and record the final root cause.
- [x] Reopen the diagnosis after the gray suffix recurred in a real terminal.
- [x] Capture incremental compositor spans and rendered control characters.
- [x] Extend the regression to reject line controls inside assistant strips.
- [x] Remove Rich's implicit line terminator from Markdown transcript lines.

## Confirmed root cause and fix

There were two independent defects. The first diagnosis correctly found that
the assistant renderer applied Rich `Style(bgcolor="default")`. Rich default
means the terminal default color, not the concrete Textual widget background.
Using `self.styles.background.rich_color` fixed the deep-black assistant
surface, but it did not fix the recurring gray suffix.

The remaining suffix came from `_render_markdown_lines`. It initially created
each Rich `Text` with `end=""`, but then sliced the object to trim outer
whitespace. Rich slicing resets `Text.end` to its default `"\n"`. Textual later
rendered the assistant content and its right-side padding as one full-width
strip containing that newline. A real terminal printed the response, advanced
to the next row, and painted the padding there, leaving the old full-width gray
user cells untouched after the response text. In-memory strip widths,
background comparisons, and full SVG exports did not model that cursor move.

The renderer now uses `self.styles.background.rich_color` for assistant rows and
empty transcript strips. This keeps the user gray block explicit while making
assistant content, wrapper rows, and trailing cells use the same resolved
background as the transcript widget. Markdown conversion also explicitly sets
`rendered_line.end = ""` after slicing, so each logical transcript line remains
terminal-safe while retaining its Rich spans.

Post-fix replay passed at `(45, 20)` and `(100, 30)` for both the short response
and a wrapped response. Each assistant visual row was full width and had a
uniform background.

## Final validation

- Focused regression: `1 passed`.
- Textual suite: `17 passed`.
- Full suite: `90 passed`.
- Mypy: no issues in 19 source files.
- Package build: source distribution and wheel succeeded.
- Editor diagnostics: no errors in the renderer or regression test.
- Exported 45-column screen: contained concrete `#121212` transcript pixels and
   `#3a3a44` user pixels, with no `default` styling token.
- Recurrence replay at `(45, 20)` and `(92, 20)`: all assistant rows were full
   width, had uniform transcript backgrounds, and contained no line controls.

## Handoff notes

Do not treat `Color('default')` as equivalent to the transcript widget's
concrete background. The regression test intentionally compares every visible
assistant segment, including blank wrapper rows and the cells after the text,
against `transcript.styles.background`.

Do not rely only on `Strip.cell_length` or exported SVG output for this class of
terminal bug. Assert that individual row segments contain no `\n` or `\r`, and
reset `Text.end` after any Rich `Text` slicing operation.

The user gray block must remain unchanged. The desired distinction is role
foreground and user background only; assistant rows should not introduce a
separate background surface.