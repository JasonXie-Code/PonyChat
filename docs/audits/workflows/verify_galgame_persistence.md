
# Galgame History Persistence Verification

> 文档状态：2026-08-09 已复核。本文是计划或审计记录，结论对应其记录时点；当前实现与风险以 `docs/PROJECT_STATUS.md` 和代码为准。

## Changes Applied
1.  **Backend Saving Enabled for Galgame Mode**: 
    -   Modified `js/chat/chat-api.js` to allow `saveConversationsToBackend()` to be called even when `isGalgameMode` is true.
    -   Originally, line 466 prevented saving: `if (!requestSnapshot.isGalgameMode && ...)`
    -   Updated to: `if (window.saveConversationsToBackend) { ... }`

## Rationale
-   `addGalgameMessage` in `conversations.js` adds the message to the memory/buffer but explicitly comments out the save call: `// saveConversationsToBackend(); // 暂时不每次都存，由外部控制`.
-   This meant that without an external trigger, Galgame progress was **never** saved to disk during gameplay.
-   By enabling the save call in `chat-api.js` (which is the main message handling loop), we ensure that every time an AI response is received and processed, the full conversation history (including Galgame data) is persisted to `characters.json`/`galgame_conversations.json`.

## Version Updates
-   `index.html`:
    -   Updated `js/galgame/galgame-core.js` to `v121` (reflecting previous session's UI updates).
    -   Updated `js/ui/char-selection.js` to `v134` (reflecting syntax error fix).
-   `js/chat-wrapper.js`:
    -   Updated `chat-api.js` import to `v124` to ensure the new save logic is loaded.

## Verification Steps for User
1.  Enter Galgame mode for a character.
2.  Interact with the game (send message, get response, update score).
3.  Refresh the page.
4.  Re-enter Galgame mode for the same character.
5.  **Expected Result**: The conversation history and score should be restored exactly as it was before the refresh.
