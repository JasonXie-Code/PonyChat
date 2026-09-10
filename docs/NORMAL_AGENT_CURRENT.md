# Current normal-chat Agent flow

The normal-chat Agent now produces the delivered reply directly. The existing reply_expression skill contains eight neutral examples that distinguish useful details, questions and topic changes from repetition. No additional expression skill or independent post-generation expression-review calls are used.

Skill call names and prompt main titles match for all 19 skills. Static text and the skill-title index live in Backend/chat_modules/Prompts.py; reply_expression_skill.py assembles the expression manual. Dynamic context remains in the existing skill adapter. DeepSeek execution uses low reasoning effort.

This snapshot also includes the current Agent architecture and its supporting application code, including timeout intake recovery. The main generation deadline is 180 seconds; an expired turn closes input before cleanup so later messages can enter a fresh turn.

Verification: 95 targeted prompt, runtime, worker-pool and timeout-intake regressions passed in this exact main worktree. Full Android/site builds and the entire backend test suite were not rerun for this snapshot sync. Runtime databases, private experimental chat logs and model binaries are intentionally not uploaded. Configure API credentials through the referenced environment variables. Local model configuration has no embedded API credential.

This is a repository synchronization, not a service deployment. MIT LICENSE is preserved from the previous main branch.
