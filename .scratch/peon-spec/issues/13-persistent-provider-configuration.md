# 13 - Persistent provider configuration

**What to build:** Remember a successfully configured interactive provider and
reuse it on later Peon runs without prompting on every startup.

**Blocked by:** 11 - Interactive TUI and provider configuration; 12 - Provider
discovery and interaction levels

**Status:** complete

- [x] Save the selected provider, endpoint, model, and credential after setup.
- [x] Restore a valid saved configuration before prompting for provider setup.
- [x] Fall back to setup when the saved profile is missing, malformed, or no
  longer usable.
- [x] Keep `/provider` as the explicit reconfiguration command and update the
  saved profile after successful replacement.
- [x] Store the profile in a user-local JSON file with an optional
  `PEON_CONFIG_FILE` override.
- [x] Document that the profile may contain credentials and must be treated as
  sensitive.