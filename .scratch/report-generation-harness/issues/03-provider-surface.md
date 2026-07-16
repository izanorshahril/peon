# 03 — Normalized provider surface

Type: grilling
Status: resolved

Blocked by: None — can start immediately

## Question

What normalized provider interface should hide the difference between OpenAI-compatible base URLs and GitHub Copilot login while keeping Peon's loop provider-agnostic?

## Answer

Use one normalized model-turn shape by default: the loop sends context and available tools, and receives either an assistant response or a tool call. Keep OpenAI-compatible transport and GitHub Copilot login inside provider adapters. Introduce a second public shape only when a provider cannot map cleanly.
