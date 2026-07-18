# 04 — Tech stack choice

Type: grilling
Status: resolved

Blocked by: None — can start immediately

## Question

Should Peon's first cut use Python or Go, given the minimal loop and future extension direction?

## Answer

Python first. Use a per-project, user-space Python stack with `uv` so Peon stays portable and easy to extend. Go remains a future option only if single-binary deployment becomes the hard operational constraint; do not choose it now just for packaging ease.
