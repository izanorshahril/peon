Continue Peon 0.3.0 migration in:

C:\Work\Project_Work\peon-v0.3.0

Current branch:
feature/peon-0.3.0

Current HEAD:
377b867 docs: finalize ticket 04 handover status

Read first:
- AGENTS.md
- .scratch/project-history.md
- .scratch/peon-0.3.0/issues/05-dispatch-prompts-through-session-controller.md

Completed:
- Ticket 01: freeze 0.2.0 baseline and contracts
- Ticket 02: publish complete-turn runtime events
- Ticket 03: expose headless event iterators and validated history
- Ticket 04: unify tool lifecycle events

Next:
- Implement ticket 05, “Dispatch prompts through SessionController”.
- Preserve tickets 06–18 as open backlog.
- Do not modify the main worktree or detached backup worktree.
- Preserve unrelated changes.

Workflow:
1. Read the ticket and nearby owning abstractions.
2. State one local falsifiable hypothesis, one cheap discriminating check, and the smallest implementation slice.
3. Implement the smallest ticket-scoped change.
4. Immediately run focused tests for the changed behavior.
5. Run the full suite with:
   uv run pytest
6. Run:
   uv run mypy src/peon
   git diff --check
7. Review the diff for standards, specification compliance, event ordering, persistence, host compatibility, and regressions.
8. Update .scratch/project-history.md and the ticket checklist with verified results.
9. Commit the completed ticket with a focused commit message.
10. Leave the feature worktree clean and report the commit, tests, and next ticket.

Current verified baseline:
- Full pytest: 327 passed
- Mypy: clean for 29 source files
- Diff check: clean