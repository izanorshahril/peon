# 14 - Pi-style provider selection and logout

**What to build:** Make provider/model setup selection-driven, retain all
detected models, and give the minimal terminal shell a Pi-like frame with an
explicit saved-provider removal command.

**Blocked by:** 12 - Provider discovery and interaction levels; 13 - Persistent
provider configuration

**Status:** complete

- [x] Present supported providers as numbered choices.
- [x] Discover OpenAI-compatible models before choosing the active model.
- [x] Select the only detected model automatically.
- [x] Ask for a numbered default when more than one model is detected.
- [x] Persist the complete detected model list for later switching.
- [x] Provide `/models` and `/model` for listing and switching saved models.
- [x] Provide `/logout` to remove the saved provider profile and exit.
- [x] Add a Pi-style header, separator-wrapped input area, and status footer.