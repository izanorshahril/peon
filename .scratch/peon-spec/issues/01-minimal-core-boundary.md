# 01 — Minimal agent core boundary

Type: grilling
Status: resolved

Blocked by: None — can start immediately

## Question

What is the smallest modular boundary for Peon if Excel report generation already belongs to another application?

## Answer

Keep one small agent loop responsible for task input, compact context, normalized provider turns, tool-call dispatch, and the final response. This follows Tau and Minion's minimal center while borrowing Pi's extension-friendly shape. Excel I/O, image evidence, report schemas, and other domain behavior are extensions, not core adapters.