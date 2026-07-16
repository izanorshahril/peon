# 05 — Agent loop and extension pipeline

Type: grilling
Status: resolved

Blocked by: None — can start immediately

## Question

How far should the shared Peon loop extend before domain-specific extension behavior begins?

## Answer

Keep the shared loop only as far as task input, compact context updates, normalized provider turns, tool-call dispatch, and final response handling. Tool schemas, authentication details, workbook logic, image interpretation, and side effects stay inside extensions. Do not generalize extension lifecycle or context management until a second real extension needs it.
