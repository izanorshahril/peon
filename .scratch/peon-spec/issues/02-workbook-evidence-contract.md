# 02 — Domain extension boundary

Type: grilling
Status: resolved

Blocked by: None — can start immediately

## Question

Where should the existing report-building application's Excel component live in Peon?

## Answer

It should remain in the report-building application, which already owns the workbook contract and safe read/write behavior. Peon should expose a small extension boundary so that application components can be wrapped as tools, skills, or an extension later. Workbook headers, formulas, formatting, image references, and report-specific errors must not become Peon core concepts.
