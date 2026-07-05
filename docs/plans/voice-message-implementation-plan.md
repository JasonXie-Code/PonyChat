# PonyChat 普通对话语音消息完整实施计划

> 编写日期：2026-05-31  
> 最近更新：2026-06-02  
> 适用范围：Android App 普通对话模式、PonyChat 主后端、PonyChat Voice Lab（`voice.ponychat.org`）  
> 核心目标：第一版在普通对话中加入类似 QQ 的角色语音消息体验；用户语音消息暂不纳入当前实施范围，后续再作为独立阶段接入。当 Voice Lab 不可用时，自动回退到文本消息，不影响主聊天。

---

## 0. 当前进展快照（2026-06-02）

本章节记录当前代码仓库已经推进到的状态，作为后续继续开发和验收的基准。

### 0.1 已完成或已基本落地

后端已经完成角色语音消息的核心数据层和 Voice Lab 编排骨架：

1. 已新增 `message_voice_states` 独立表和迁移逻辑。
   - 位置：`Backend/db/database.py`
   - 表内只保存 `voice_status`、`voice_id`、`voice_job_id`、`voice_cache_key`、`tts_text`、`transcript`、`text_fragments_json`、`voice_error`、`updated_at`。
   - 没有保存音频文件、音频 URL 或 App 本地路径。

2. 已新增语音状态 DAO。
   - 位置：`Backend/db/message_voice_states.py`
   - 提供状态标准化、保存、批量读取和把语音状态附加到消息 JSON 的能力。

3. 历史、分页、增量和搜索接口已经开始合并语音状态。
   - 位置：
     - `Backend/db/conversations_dao.py`
     - `Backend/routes/characters.py`
     - `Backend/routes/messages.py`
   - 历史消息返回时会附带 `voice_state`。
   - 搜索范围已经包含 `tts_text`、`transcript`、`text_fragments_json`。

4. 已新增 Voice Lab 客户端。
   - 位置：`Backend/voice_lab_client.py`
   - 已封装 `POST /jobs/tts`、轮询 `GET /jobs/{job_id}`、下载 `GET /jobs/{job_id}/audio?variant=mobile`。
   - 已加入启用开关、连接超时、任务超时、轮询间隔和失败熔断配置。

5. 已新增聊天语音编排模块。
   - 位置：`Backend/chat_modules/voice_messages.py`
   - 已实现：
     - 括号文本拆分，完整 `（...）` / `(...)` 进入 `text_fragments`，不送入 TTS。
     - 角色语音配置读取。
     - `pending`、`ready`、`failed` 状态保存。
     - Voice Lab 成功后把音频作为短期 `audio_transfer` 返回或在线推送。
     - `message_updated` WebSocket 事件推送。
   - 当前 `audio_transfer` 只用于在线下发或调试接口响应，不写入 outbox，不做持久化。

6. 普通非流式聊天链路已经接入后台语音生成调度。
   - 位置：`Backend/chat_modules/normal_nonstream.py`
   - assistant 文本落库成功后，可按当前语音策略调度 TTS。
   - 当前还不是完整“导演步骤”方案，而是先使用角色配置 + 保守启发式策略。

7. 已新增手动/调试语音生成接口。
   - 位置：`Backend/routes/messages.py`
   - 接口：`POST /api/messages/voice/synthesize`
   - 用途：对指定 assistant 消息触发一次后端 TTS，返回 `voice_state` 和一次性 `audio_transfer`，方便 Android 调试接入。

Android 端已经完成语音消息基础模型、本地缓存和主要 UI 样式：

1. 已扩展消息模型。
   - 位置：`Android-App/app/src/main/java/top/ponychat/webview/data/model/Models.kt`
   - 已新增/扩展：
     - `MessageVoiceState`
     - `VoiceAudioTransfer`
     - `VoiceMessagePatch`
     - `MessageVoiceUpdate`
     - `VoiceSynthesizeResponse`
     - `waveform`

2. 已新增本地语音缓存。
   - 位置：`Android-App/app/src/main/java/top/ponychat/webview/data/local/ChatVoiceCache.kt`
   - 已支持：
     - 接收后端 base64 音频并写入 App 私有缓存。
     - 使用 `voice_cache_key` 建索引。
     - 使用 `MediaMetadataRetriever` 读取时长。
     - 使用 `MediaExtractor` + `MediaCodec` 解码音频并计算波形能量数组。
   - 这一步已经为“大音量柱高、小音量柱矮”的真实波形显示准备好了数据来源。

3. 已扩展网络和 WebSocket。
   - 位置：
     - `Android-App/app/src/main/java/top/ponychat/webview/data/api/ApiService.kt`
     - `Android-App/app/src/main/java/top/ponychat/webview/data/repo/ChatRepository.kt`
     - `Android-App/app/src/main/java/top/ponychat/webview/data/api/SyncWebSocketManager.kt`
   - 已加入 `POST /api/messages/voice/synthesize` 调用。
   - 已能解析服务端 `message_updated` 为 `MessageVoiceUpdate`。

4. `ChatViewModel` 已开始接入语音状态。
   - 位置：`Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatViewModel.kt`
   - 已支持：
     - 把历史消息里的 `voice_state` 合并成 UI 消息状态。
     - 用 `ChatVoiceCache` 对语音状态做本地缓存水合。
     - 应用 `MessageVoiceUpdate` 到当前消息。
     - 调试触发最近一条 assistant 消息的后端语音生成。
     - 注入 assistant/user 端本地语音样例、缓存缺失样例、生成失败样例。

5. 语音气泡 UI 样式已经完成第一轮。
   - 位置：`Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatMessageBubble.kt`
   - 已实现：
     - assistant 左侧语音气泡。
     - user 右侧语音气泡样式样例。
     - 不同时长对应不同气泡宽度，最长 60 秒且保持一行。
     - 时长秒标识在数字右上方。
     - 长按菜单中只有展开“转文字”后才显示“复制”。
     - 波形区域点击用于播放/暂停。
     - 波形区域拖动用于改变进度。
     - 播放进度用“已播实色、未播浅色”表达。

### 0.2 当前未完成或需要继续修正

1. 真实波形数据尚未完全接到气泡渲染。
   - `ChatVoiceCache` 已经能从真实音频计算 `waveform`。
   - `ChatMessageBubble.kt` 里的 `VoiceWaveBars` 当前仍主要使用固定高度 pattern。
   - 下一步需要把 `voiceState.waveform` 传入 `VoiceWaveBars`，并按每个 bucket 的真实音量决定柱高，满足“大音量柱高、小音量柱矮”。

2. 播放仍需要和真实音频文件完全绑定。
   - UI 已有播放/暂停、进度和拖动状态。
   - 下一步需要用 `MediaPlayer` 或 ExoPlayer 播放 `localFile`，并在拖动后 `seekTo` 新位置继续播放。

3. `message_updated` 的 UI 收集链路还需要最后接线。
   - `SyncWebSocketManager` 已经解析出 `messageUpdateFlow`。
   - 下一步需要在聊天页面收集该 flow，并调用 `viewModel.applyVoiceMessageUpdate(update)`。

4. 后端语音调试入口还需要接到 App 调试面板。
   - `ChatViewModel.debugGenerateBackendVoiceForLastAssistant()` 已存在。
   - 下一步需要在调试模式设置页增加按钮，例如“后端语音”，点击后对最近一条 assistant 消息调用后端 TTS。

5. 缓存写入需要移到 IO 线程。
   - 当前 `applyVoiceMessageUpdate()` 和调试生成成功后的 `ChatVoiceCache.save()` 逻辑需要确认不在主线程做文件写入和音频解码。

6. 完整导演步骤尚未落地。
   - 当前接入的是角色配置 + 保守自动语音策略。
   - 原计划中的“导演先决定 `response_modality = text | voice`，主模型再按形态生成回复”仍是下一阶段正式化工作。

7. 用户语音消息仍不是正式功能。
   - 当前只做了用户端语音气泡样式调试样例，方便验证右侧气泡外观。
   - 还没有接入用户录音、ASR、发送、服务端用户语音状态或用户音频缓存。

8. 尚未完成本轮完整编译、安装和模拟器验收。
   - 下一步需要使用 `P:\Tools` 下的 JDK/Android SDK 编译 Debug APK。
   - 需要安装到模拟器，分别在深色和浅色模式下测试 assistant/user 端语音气泡、后端生成、缓存缺失、生成失败、播放、拖动、转文字和复制菜单。
   - 模拟器中的关键操作需要逐步截图留档。

### 0.3 下一步最小闭环

下一轮继续开发时，建议按这个顺序完成：

1. 把 `voiceState.waveform` 接入 `VoiceWaveBars`，真实音频按实际音量显示柱高。
2. 把语音播放改成真实 `localFile` 播放，拖动后从新位置继续播放。
3. 在聊天页面收集 `messageUpdateFlow`，让后端异步 TTS 完成后能把消息升级为语音气泡。
4. 在调试面板加入“后端语音”按钮，调用最近 assistant 消息的后端合成接口。
5. 把音频缓存保存和波形解码移到 IO 线程。
6. 使用 `P:\Tools` 编译安装到模拟器，完成深色和浅色外观截图测试。
7. 再补完整导演步骤和自动语音决策，替换当前保守启发式策略。

---

## 1. 总体原则

语音消息应作为普通聊天的增强层，而不是主链路依赖。

必须满足：

1. 文本聊天永远可用。LLM 文本回复是主结果，语音生成失败不能导致聊天失败。
2. 角色语音由主后端编排。Android App 不直接依赖 Voice Lab 生成角色语音。
3. Voice Lab 只负责 TTS 生成。主后端负责鉴权、文本语义状态、回退与历史一致性，不持久化任何语音音频。
4. 当前第一版不做用户语音消息。用户侧仍按普通文本消息入模；后续若接入用户语音，也只能保存 ASR 文本，不保存用户录音文件或音频 URL。
5. 角色语音转文字不走 ASR。角色语音直接使用生成 TTS 时的原始文本，并在 UI 上逐字出现，模拟转录过程。
6. 角色是否在本轮发送语音消息由“导演步骤”决定，而不是由客户端临时决定。
7. 如果导演步骤选择本轮语音回复，后续主模型回复应按语音回复来写；其中可朗读正文进入 TTS，带括号的动作/神态/旁白内容仍用文本展示，不送入 TTS。
8. 角色侧入模永远使用主回复模型的完整回复文本；用户侧当前只按文本入模，后续用户语音阶段再按 ASR 结果入模。
9. 主动消息、后台消息也要支持角色语音，但仍遵守导演决策、TTS 回退和本地音频缓存机制。
10. 所有音频只存在 Android App 本地缓存中。App 完全重装后，原来显示为音频消息的位置自动退化为文本消息。
11. 失败时静默降级。语音不可用时保留普通文本消息，最多轻提示一次，不插入额外失败消息。

---

## 2. 当前基础

### 2.1 Android 普通聊天 UI

当前普通对话主要由以下文件组成：

- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatMessageBubble.kt`
  - 负责用户/角色消息气泡渲染。
  - 用户消息右侧，靛蓝渐变气泡。
  - 角色消息左侧，`surfaceVariant` 气泡。
  - 已有长按菜单：复制、引用、选择、删除、撤回等。
  - 已支持 `attachments`，目前用于表情/素材。

- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreenInput.kt`
  - 负责底部输入栏。
  - 已有图片、拍照、表情、快捷消息、更多功能。
  - 已有 `VoiceState` 和 `BackendStreamingVoiceBridge`，目前更偏向“语音识别输入文本”，不是完整语音消息。

- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreenScaffoldMain.kt`
  - 负责消息列表、输入栏挂载、滚动、图片预热、消息操作回调。

### 2.2 后端消息与附件

主后端已有附件模型：

- `Backend/utils.py`
  - `ChatMessage.attachments`
  - `MessageAttachment`

- `Backend/db/message_attachments.py`
  - 负责附件标准化、保存、读取。
  - 当前 `normalize_attachment()` 只允许 `sticker`、`emoji_asset`。
  - 语音计划调整后，不再保存服务端音频附件；如需保存语音状态，应保存轻量文本 metadata，而不是音频 URL。

- `Backend/routes/chat.py`
  - `/api/chat` 主聊天入口。
  - `/api/chat/sticker` 已有“仅发送附件消息”的参考实现。

### 2.3 Voice Lab 能力

Voice Lab 位于：

- `PonyChat-Website/TTS/app_fast.py`
- `PonyChat-Website/TTS/static/`
- `PonyChat-Website/TTS/PonyChat-Voice-Lab.md`

已有能力：

- `POST /jobs/tts`
  - 异步 TTS 入队。
  - 返回 `job_id`。

- `GET /jobs/{job_id}`
  - 轮询任务状态。
  - 状态包括 `queued`、`running`、`completed`、`failed`。

- `GET /jobs/{job_id}/audio`
  - 下载生成音频。
  - 支持 `variant=original` 和 `variant=mobile`。

- `POST /jobs/tts/segmented`
  - 分段情绪 TTS，后续可用于更自然的角色语音。

- `GET /voices/meta`、`GET /speakers`
  - 声音库和预置说话人。

重要限制：

- Voice Lab 是独立 GPU 服务，不保证一直可用。
- 异步任务结果有 TTL，不应直接作为聊天历史里的音频 URL。
- 单卡队列可能排队，不应阻塞主聊天。
- Voice Lab 生成的音频只应下发给 App 本地缓存；主后端不保存音频文件。

### 2.4 当前仓库评估结论

根据当前代码仓库，角色语音消息方案可行，但第一版需要按现有架构收窄和补强：

- 普通对话已经有 `normal_planner` / 导演链路，适合扩展 `response_modality = text | voice`。
- Voice Lab 已有异步 TTS、轮询、`variant=mobile` 音频下载能力，可直接作为角色 TTS 服务。
- 主业务 WebSocket 和 `message_outbox` 已存在，但当前没有 `message_updated` 事件；需要新增 Android 解析和后端推送协议。
- `message_outbox` 的 payload 会持久化到数据库，不能放入 Voice Lab job audio URL 或 `audio_transfer`。音频下发应只对在线 App 走 WebSocket 直推；离线时只保留文本语音状态并降级文本展示。
- `messages` 表和 `save_conversation()` 当前是显式列写入，旧客户端或普通保存流程容易丢失新增顶层字段。第一版推荐使用独立 `message_voice_states` 表保存角色语音文本状态，不把语音状态直接塞进 `messages` 表顶层列。
- Android 普通输入栏现有 `BackendStreamingVoiceBridge` 仍偏“语音识别输入文本”，且普通聊天入口当前指向已移除的 `/ws/speech`。由于当前第一版暂不做用户语音消息，该问题不阻塞角色语音；后续用户语音阶段应改为 `/ws/speech/aliyun` 或 `/ws/speech/dashscope`。

---

## 3. 目标体验

### 3.1 用户语音消息

当前第一版暂不做用户语音消息，也不在输入栏新增“按住说话”发送入口。

用户侧第一版行为：

1. 用户继续发送普通文本消息。
2. 后端不新增用户语音上传、用户语音附件或用户语音 metadata。
3. 历史、搜索、多设备同步仍只处理用户文本消息。
4. 后续若恢复用户语音阶段，再复用 `/ws/speech/aliyun` 或 `/ws/speech/dashscope` 做实时 ASR，并只保存 ASR 文本。

### 3.2 角色语音消息

角色回复时：

1. 普通对话的导演步骤先判断本轮回复形态：`text` 或 `voice`。
2. 如果导演选择 `text`，主模型按普通文本回复，Android 显示普通文本气泡。
3. 如果导演选择 `voice`，主模型按语音回复来写本轮内容。
4. 语音回复中，可朗读正文进入 TTS；带括号的动作、神态、环境或补充说明仍用文本展示。
5. TTS 成功后，音频只写入 Android App 本地缓存；服务端只保存原始文本、`tts_text`、括号文本和语音状态。
6. Android 若本地缓存存在对应音频，显示左侧 QQ 风角色语音气泡，并在气泡下方/相邻位置展示括号文本。
7. 如果 App 完全重装或本地音频缓存丢失，该位置自动退化为原始 TTS 文本/完整回复文本展示。
8. 点击播放/暂停。
9. 长按气泡弹出菜单，包含“转文字”。
10. 点击“转文字”后，用 TTS 原始可朗读文本逐字出现，模拟转录过程。

### 3.3 Voice Lab 失效回退

当 Voice Lab 不可用：

1. 普通聊天照常生成文本。
2. 不等待语音生成。
3. Android 显示普通文本消息。
4. 不出现语音气泡。
5. 可选轻提示：“语音生成暂不可用，已显示文字。”

---

## 4. 数据模型设计

### 4.1 角色语音文本状态

服务端不保存角色语音音频，也不保存可播放音频 URL。服务端只保存足以让 App 还原展示与搜索的文本状态。

角色语音状态示例：

```json
{
  "voice_status": "ready",
  "voice_id": "twilight-soft",
  "tts_text": "今天也想听听你发生了什么。",
  "transcript": "今天也想听听你发生了什么。",
  "text_fragments": ["（她轻轻把尾音放慢，像是在等你接话。）"],
  "voice_job_id": "voice_lab_job_id",
  "voice_cache_key": "conv_xxx:msg_xxx:voice_lab_job_id",
  "voice_error": ""
}
```

字段约定：

- `tts_text`：真正送入 Voice Lab 的可朗读正文，不包含括号内容。
- `transcript`：角色语音“转文字”时展示的文本，通常等于 `tts_text`。
- `text_fragments`：本轮语音回复中仍需要文本展示的括号内容，例如动作、神态、环境或补充说明。
- `content`：assistant 消息仍可保留完整原文，便于历史、复制、模型上下文和失败回退。
- `voice_cache_key`：App 本地缓存音频的稳定键。服务端可保存键，但不保存音频。

App 本地缓存可保存：

```json
{
  "voice_cache_key": "conv_xxx:msg_xxx:voice_lab_job_id",
  "local_file": "app-private-cache/voice/xxx.mp3",
  "duration_ms": 4200,
  "mime": "audio/mpeg",
  "variant": "mobile"
}
```

该本地缓存不参与服务端同步。App 完全重装、清理缓存或换设备后，历史记录只显示 `transcript`、`text_fragments` 或完整 `content`。

用户语音消息当前第一版暂不实现，因此第一版不新增用户语音 metadata、不新增用户录音本地态持久化，也不新增用户语音发送接口。后续若恢复用户语音阶段，仍应遵守“不保存用户原始音频”的原则；发送到主后端的只会是普通 `role = "user"` 文本消息，`content` 为 ASR final 结果。可选保留轻量 metadata，例如：

```json
{
  "input_modality": "voice",
  "asr_provider": "dashscope",
  "asr_duration_ms": 12340
}
```

该 metadata 仅用于后续用户语音阶段的调试、统计和 UI 标识，不包含用户原始音频 URL。

### 4.2 消息层语音状态

建议 assistant 消息额外携带轻量状态。若现有消息模型暂不方便扩展顶层 metadata，也可以先放入服务端内部字段，但不要保存音频 URL。

```json
{
  "voice_status": "disabled | pending | ready | failed",
  "voice_error": "voice_service_unavailable | timeout | job_failed | download_failed"
}
```

含义：

- `disabled`：角色未开启语音。
- `pending`：文本已返回，语音生成中。
- `ready`：语音生成成功，App 可按 `voice_cache_key` 查找本地音频；若本地不存在则退化文本。
- `failed`：语音生成失败，已回退文本。

第一版需要向 Android 暴露 `ready/failed` 和 `voice_cache_key`。展示逻辑为“本地有音频显示语音，本地无音频显示文本”。

### 4.3 仓库适配建议：独立语音状态表

当前 `messages` 表没有通用 metadata 字段，`save_conversation()` 也是显式列写入。为了避免旧客户端或普通保存流程覆盖语音状态，第一版推荐新增独立表，而不是直接给 `messages` 顶层加一组 voice 列。

建议表：

```sql
CREATE TABLE IF NOT EXISTS message_voice_states (
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    voice_status TEXT NOT NULL DEFAULT 'disabled',
    voice_id TEXT,
    voice_job_id TEXT,
    voice_cache_key TEXT,
    tts_text TEXT,
    transcript TEXT,
    text_fragments_json TEXT NOT NULL DEFAULT '[]',
    voice_error TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, message_id)
);
```

要求：

- 历史接口加载消息时按 `conversation_id + message_id` 左连接语音状态，并返回给 Android。
- 搜索接口需要把 `tts_text`、`transcript`、`text_fragments_json` 纳入文本搜索范围。
- 普通消息保存、撤回、删除不应意外清空语音状态；删除消息时可按消息软删除策略保留或清理对应状态。
- 该表只保存文本状态和缓存键，不保存音频 URL、音频路径或音频字节。

---

## 5. 主后端改造

### 5.1 服务端语音状态存储

不再使用 `message_attachments` 保存角色语音音频附件。第一版使用独立 `message_voice_states` 表保存 assistant 消息的轻量语音文本状态。

需要保存：

- `conversation_id`
- `message_id`
- `voice_status`
- `voice_id`
- `voice_job_id`
- `voice_cache_key`
- `tts_text`
- `transcript`
- `text_fragments`
- `voice_error`

禁止保存：

- 角色 TTS 音频文件。
- 角色 TTS 音频 URL。
- 用户录音文件。
- 用户录音 URL。

验收：

- assistant/角色消息能保存和读取语音文本状态。
- 普通消息保存流程不会覆盖或清空已有 `message_voice_states`。
- 重新加载历史后，语音消息位置能退化显示 `transcript`、`text_fragments` 或完整 `content`。
- 搜索/历史接口能搜索 `tts_text`、`transcript`、`text_fragments` 和原始 `content`。

### 5.2 音频下发与本地缓存

角色 TTS 音频只作为一次性或短期结果下发给 Android App。主后端不得把音频写入长期存储。

可选实现方式：

1. 主后端调用 Voice Lab，下载音频后通过 `message_updated` 事件以短期下载地址或二进制通道交给当前在线 App。
2. App 收到音频后写入私有本地缓存，并用 `voice_cache_key` 建立索引。
3. 主后端丢弃音频字节，只保留 `voice_cache_key` 和文本状态。

要求：

- 服务端不提供永久 `/chat_audio` URL。
- 服务端不把 Voice Lab job audio URL 写入历史。
- 服务端不把 `audio_transfer.url` 写入 `message_outbox.payload_json`，因为 outbox 是持久化补推通道。
- `message_updated` 中带 `audio_transfer` 的事件只面向当前在线 App 直推；App 不在线时不补发音频，只能在历史中看到语音文本状态并降级文本。
- 失败状态或不含音频 URL 的轻量状态可以通过历史接口恢复；不要依赖离线补推恢复音频。
- App 换设备、清缓存、完全重装后，无法恢复音频是预期行为。
- 历史 UI 必须自动退化为文本展示。

### 5.3 Voice Lab 客户端

新增后端模块，建议路径：

- `Backend/voice_lab_client.py`

职责：

1. 封装 `POST /jobs/tts`。
2. 封装 `GET /jobs/{job_id}` 轮询。
3. 封装 `GET /jobs/{job_id}/audio?variant=mobile` 下载短期音频结果。
4. 统一超时、重试、错误码。
5. 实现健康缓存和熔断。

配置项建议：

```text
PONYCHAT_VOICE_LAB_BASE_URL=https://voice.ponychat.org
PONYCHAT_VOICE_LAB_ENABLED=1
PONYCHAT_VOICE_LAB_CONNECT_TIMEOUT=5
PONYCHAT_VOICE_LAB_JOB_TIMEOUT=40
PONYCHAT_VOICE_LAB_CIRCUIT_OPEN_SECONDS=180
PONYCHAT_VOICE_LAB_DEFAULT_VARIANT=mobile
```

### 5.4 熔断和回退

必须覆盖以下失败：

- DNS/连接失败。
- `/jobs/tts` 创建失败。
- job 一直 `queued` 或 `running` 超时。
- job 返回 `failed`。
- 下载音频失败。
- 音频下发给 App 失败。
- `voice_id` 不存在。
- 配置禁用。

策略：

1. 最近成功后，认为 Voice Lab 短期可用。
2. 最近失败后，熔断 2-5 分钟。
3. 熔断期间不再尝试 TTS，直接回退文本。
4. 所有异常只记录日志，不影响 `/api/chat` 主结果。

### 5.5 导演步骤与本轮回复形态

普通对话在主模型生成最终回复前，应增加或复用“导演步骤”来决定本轮是否发送语音消息。

导演步骤职责：

1. 根据角色语音开关、用户当前输入、上下文节奏、消息长度、Voice Lab 熔断状态，决定本轮回复形态。
2. 输出结构化字段，例如：

```json
{
  "response_modality": "text",
  "voice_reason": "当前回复较长，文本更适合阅读",
  "allow_voice_retry": false
}
```

或：

```json
{
  "response_modality": "voice",
  "voice_reason": "用户发来短句问候，适合用语音营造陪伴感",
  "allow_voice_retry": true
}
```

约束：

- 如果角色未开启语音，导演只能输出 `text`。
- 如果 Voice Lab 处于熔断状态，导演只能输出 `text`，或后端强制覆盖为 `text`。
- 导演步骤只决定回复形态，不负责写最终回复正文。
- 主模型必须收到本轮 `response_modality`，并按该形态生成。

### 5.6 主模型回复规范

当导演输出 `response_modality = "text"`：

- 主模型按现有普通文本回复生成。
- 不生成语音状态，也不触发 TTS。

当导演输出 `response_modality = "voice"`：

- 主模型应按“即将被角色说出来”的语音回复来写。
- 可朗读正文应自然、口语化、适合 TTS。
- 带括号内容仍允许出现，但它们被视为文本展示片段，不送入 TTS。
- 后端需要从最终回复中拆分：
  - `tts_text`：非括号、可朗读正文。
  - `text_fragments`：括号内容。
  - `content`：完整原文，用于历史和回退。

示例：

```text
当然可以呀，我就在这里陪你。今天想先聊点轻松的，还是让我听你慢慢说？
（她的声音放得很轻，像是怕打断你的思路。）
```

拆分结果：

```json
{
  "tts_text": "当然可以呀，我就在这里陪你。今天想先聊点轻松的，还是让我听你慢慢说？",
  "text_fragments": ["（她的声音放得很轻，像是怕打断你的思路。）"]
}
```

注意：

- 括号文本不能进入 Voice Lab，否则会把动作描写读出来，破坏语音消息体验。
- 如果拆分后 `tts_text` 为空，本轮强制回退为纯文本。
- 如果 TTS 生成失败，本轮完整 `content` 作为普通文本消息展示。

### 5.7 括号拆分规则

语音回复只跳过完整闭合括号对中的内容，其余内容按可朗读正文处理。

第一版需要识别的完整闭合括号对：

- 中文全角：`（...）`
- 英文半角：`(...)`

规则：

1. 只有存在明确起始括号和对应结束括号的片段，才进入 `text_fragments`。
2. 未闭合括号、孤立右括号、跨段异常括号，不从 `tts_text` 中剔除。
3. 嵌套括号第一版不做复杂解析，按最外层完整闭合括号对提取；无法稳定解析时保留在 `tts_text` 中。
4. 如果导演选择 `voice`，且文本中没有完整闭合括号对，则整段回复都可以进入 TTS。
5. 拆分失败不能导致本轮丢内容；最坏情况是完整回复走 TTS，或在 `tts_text` 为空时回退文本。

示例：

```text
我当然愿意听你说。（她轻轻点头）
```

拆分为：

```json
{
  "tts_text": "我当然愿意听你说。",
  "text_fragments": ["（她轻轻点头）"]
}
```

示例：

```text
我当然愿意听你说。（她轻轻点头
```

由于括号未闭合，拆分为：

```json
{
  "tts_text": "我当然愿意听你说。（她轻轻点头",
  "text_fragments": []
}
```

### 5.8 上下文入模策略

角色侧：

- 无论本轮是否成功生成语音，后续对话入模都使用主回复模型生成的完整 `content`。
- `content` 包含可朗读正文和括号文本片段，不能只用 `tts_text`。
- 本地音频只是展示层和播放层，不改变模型记忆中的角色回复内容。

用户侧：

- 用户发送文本消息时，按原文本 `content` 入模。
- 当前第一版不做用户语音消息，因此用户侧只有文本消息入模。
- 后续用户语音阶段若恢复，才按 ASR final 文本作为 `content` 入模；用户原始录音仍不上传、不保存、不参与模型上下文。

### 5.9 聊天生成链路

一步到位采用正式版“文本先返回，语音后补”的结构，不做同步短等待作为主方案。

流程：

1. 导演步骤判断本轮 `response_modality`。
2. `/api/chat` 调用主模型生成 assistant 内容。
3. 如果本轮是 `text`，保存并返回普通文本消息。
4. 如果本轮是 `voice`，后端拆分 `tts_text` 和 `text_fragments`。
5. 保存 assistant 完整文本消息，用于历史、复制和失败回退。
6. 立即返回文本给 Android，或返回“语音生成中”的轻量状态。
7. 后端后台任务用 `tts_text` 生成角色语音。
8. 成功后生成 `voice_cache_key`，通过 `message_updated` 把语音文本状态和音频短期结果下发给 App。
9. 主后端通过正式消息更新事件通知 Android，例如 `message_updated`。
10. Android 以 `conversation_id + message_id` 为锚点更新对应消息，将音频写入本地缓存；若写入成功，将文本展示升级为语音气泡 + 括号文本片段。

现有普通回复会按换行拆成多条 assistant 消息。第一版应二选一：

1. 语音回复强制生成单段 assistant 文本，只给该 `message_id` 生成一条语音。
2. 或者每个 assistant 段落各自保存一条 `message_voice_states`，分别生成和播放。

推荐第一版采用方案 1，降低 `message_updated` 与本地缓存索引复杂度。

消息更新事件建议：

```json
{
  "type": "message_updated",
  "conversation_id": "conv_xxx",
  "message_id": "msg_xxx",
  "patch": {
    "voice_status": "ready",
    "voice_cache_key": "conv_xxx:msg_xxx:voice_lab_job_id",
    "voice_id": "twilight-soft",
    "tts_text": "我当然愿意听你说。",
    "transcript": "我当然愿意听你说。",
    "text_fragments": ["（她轻轻点头）"],
    "audio_transfer": {
      "kind": "short_lived_url",
      "url": "https://voice.ponychat.org/jobs/voice_lab_job_id/audio?variant=mobile",
      "expires_hint_seconds": 86400
    }
  }
}
```

也可以将 `audio_transfer.kind` 设计为 `bytes` 或应用内二进制通道；无论哪种方式，音频只允许 App 落本地缓存，不进入主后端长期存储。

注意：

- 带 `audio_transfer` 的 `message_updated` 不进入 `message_outbox`，只对在线 App 直推。
- 如果 App 离线或推送失败，服务端只保留 `message_voice_states` 文本状态；音频不会补发，历史自动降级文本。
- Android 需要新增 `message_updated` 解析分支，并将其映射到当前会话消息更新或本地缓存写入。

失败时也可发送更新事件，但不强制：

```json
{
  "type": "message_updated",
  "conversation_id": "conv_xxx",
  "message_id": "msg_xxx",
  "patch": {
    "voice_status": "failed",
    "voice_error": "voice_service_unavailable"
  }
}
```

Android 收到失败状态后保持普通文本展示。

### 5.10 主动消息和后台消息

主动消息、后台消息需要支持角色语音，使用与前台普通聊天相同的决策和生成链路。

要求：

1. 后台生成主动消息时，同样先运行导演步骤，输出 `response_modality`；当前 `scheduled_followup` 是独立保存和推送链路，需要单独接入语音状态和 TTS 后补。
2. 如果本轮为 `voice`，仍先保存完整文本内容，再后台生成 TTS。
3. TTS 成功后保存语音文本状态，并仅向在线 App 下发短期音频结果。
4. App 在线时通过 `message_updated` 更新当前聊天或列表缓存，并写入本地音频缓存。
5. App 不在线时，通知栏仍以文本 preview 为主，不自动播放语音。
6. Voice Lab 失效时，主动消息退回纯文本，不丢消息。

### 5.11 角色语音配置

建议在角色配置中增加：

```json
{
  "voice_enabled": true,
  "voice_id": "twilight-soft",
  "voice_instruct": "温柔地，语速稍慢",
  "voice_decision_policy": "director",
  "voice_mobile_microphone": true
}
```

`voice_decision_policy` 可选：

- `off`：不生成语音，导演只能输出 `text`。
- `director`：由导演步骤逐轮决定 `text` 或 `voice`。
- `always_voice_when_available`：只要 Voice Lab 可用就倾向语音，但仍允许后端因熔断、内容不适合朗读、`tts_text` 为空等情况回退文本。

第一版推荐：

- 使用 `voice_decision_policy = "director"`。
- Android 若本地有音频缓存，显示语音气泡和括号文本片段。
- 若没有本地音频缓存，显示 `transcript`、`text_fragments` 或完整普通文本气泡。

---

## 6. Android App 改造

### 6.1 数据模型

Android 需要在消息模型旁边解析服务端返回的语音文本状态，并维护独立本地音频缓存索引。

需要增加辅助解析函数：

- `hasVoiceState()`
- `voiceDurationMs()`
- `voiceTranscript()`
- `voiceCacheKey()`
- `voiceMime()`

### 6.2 VoiceMessageBubble 组件

在 `ChatMessageBubble.kt` 中新增 composable：

```kotlin
@Composable
private fun VoiceMessageBubble(
    voiceState: AssistantVoiceState,
    isPlaying: Boolean,
    transcriptState: VoiceTranscriptState,
    onPlayToggle: () -> Unit,
    onShowMenu: (...) -> Unit
)
```

视觉要求：

- 高度：42-46dp。
- 宽度按时长变化，范围约 96-260dp。
- 角色气泡：沿用 `surfaceVariant`。
- 显示喇叭图标、声波、时长。
- 播放中声波循环动画。
- 未播放可显示小红点。

角色左侧布局：

```text
[ 喇叭   声波   12" ]
```

说明：

- 服务端不持久化角色音频；`VoiceMessageBubble` 只在 App 本地存在 `voice_cache_key` 对应音频时显示。
- 当前第一版没有用户语音消息；用户消息继续显示普通文本气泡。
- 如果本地音频不存在，消息应显示 `transcript`、`text_fragments` 或完整 `content` 文本。

### 6.3 语音气泡菜单

长按语音气泡菜单：

通用：

- 播放 / 暂停
- 转文字 / 收起文字
- 复制文字
- 引用
- 删除

角色消息额外：

- 重新生成语音（第二阶段）

菜单行为：

- 如果未展开，显示“转文字”。
- 如果正在转录，显示“取消转文字”或禁用。
- 如果已展开，显示“收起文字”。
- 如果 transcript 为空，“复制文字”置灰。

### 6.4 转文字展开区

展开区附着在语音气泡下方，不作为新消息。

角色语音：

- 读取消息语音状态中的 `tts_text` 或 `transcript`。
- 先显示“正在转文字...” 300-500ms。
- 然后逐字出现。
- 标点处轻微停顿。
- 完成后只显示文本。

当前第一版没有用户语音气泡，也没有用户侧“转文字”入口。

### 6.5 播放器

新增统一语音播放控制，建议由 ViewModel 管理：

- 当前播放 message id。
- 当前播放 attachment id。
- 播放进度。
- 加载状态。

播放方式：

- Android 原生 `MediaPlayer` 或 `ExoPlayer`。
- 第一版可用 `MediaPlayer`，后续如需缓存和波形进度再切 ExoPlayer。

要求：

- 同一时间只播放一条语音。
- 离开页面停止播放。
- 点击另一条语音时停止上一条。
- 播放失败轻提示。
- App 启动或进入会话时，用 `voice_cache_key` 检查本地音频是否存在；不存在则直接显示文本，不报错。

### 6.6 本地音频缓存

角色语音音频只存在 App 私有缓存中。

缓存索引字段：

- `voice_cache_key`
- `conversation_id`
- `message_id`
- `local_file`
- `duration_ms`
- `created_at`
- `voice_id`

要求：

1. 收到 `message_updated` 的 `audio_transfer` 后，App 下载或接收音频并写入私有缓存。
2. 写入成功后，当前消息显示为语音气泡。
3. 写入失败、文件丢失、App 重装、用户清缓存时，消息显示为文本。
4. 对话历史记录页面不读取本地音频，不显示语音气泡，只显示 `transcript`、`text_fragments` 和原始 `content`。
5. 搜索只搜索文本，不搜索音频。

### 6.7 后续：输入栏录音模式（本阶段不做）

当前第一版暂不做用户语音消息，因此不改造输入栏为“按住说话”模式，不新增用户录音发送入口。

在 `ChatScreenInput.kt` 增加语音消息入口。

建议交互：

1. 输入框左侧增加麦克风按钮。
2. 点击麦克风切换文本/语音模式。
3. 语音模式下输入框位置变成“按住说话”按钮。
4. 长按开始录音。
5. 松开发送。
6. 上滑取消。

录音中 UI：

- 显示计时。
- 显示音量条或简易波形。
- 正常态文案：“松开发送，上滑取消”。
- 取消态文案：“松手取消”。

### 6.8 后续：用户语音发送（本阶段不做）

当前第一版暂不实现以下流程，仅作为后续用户语音阶段参考。

用户语音发送不上传原始音频。Android 流程：

1. 请求 `RECORD_AUDIO` 权限。
2. 开始本地录音/采集 PCM。
3. 限制时长，例如 1-60 秒。
4. 录音过程中将音频流发送到 `/ws/speech/dashscope` 或 `/ws/speech/aliyun` 做实时 ASR。
5. 松开发送时，若 ASR final 可用，则把 ASR 文本作为普通用户消息发送到 `/api/chat`。
6. 主后端只保存 ASR 文本，不保存用户录音文件。
7. 当前会话中可显示“语音转文字发送”的轻量状态；历史记录中显示普通用户文本气泡。

第一版建议时长限制：

- 少于 0.8 秒：提示“说话时间太短”。
- 超过 60 秒：自动发送或自动停止。
- ASR final 为空时，不发送消息，提示“没有识别到清晰语音”。

---

## 7. 后续用户语音 ASR 方案（本阶段不做）

当前第一版暂不做用户语音消息。本章只保留为后续阶段参考，不参与当前 MVP 排期、验收和测试范围。

### 7.1 现有能力

主后端已有：

- `/ws/speech/dashscope`
- `/ws/speech/aliyun`
- `BackendStreamingVoiceBridge`

这些能力目前用于实时语音识别输入文本，可以复用。

仓库注意事项：

- Android 普通聊天输入栏当前的语音入口构造的是 `/ws/speech`。
- 后端 `/ws/speech` 已移除本地 ASR，会返回 `local_asr_removed` 并关闭。
- 后续用户语音阶段应改为 `/ws/speech/aliyun` 或 `/ws/speech/dashscope`，可参考陪玩模式已有实现。

### 7.2 正式方案：录音时同步转写，发送 ASR 文本

用户录音时：

1. Android 只在本地短暂持有录音流，不上传持久音频文件。
2. 把 PCM 分块发送到 `/ws/speech/dashscope`。
3. ViewModel 缓存 partial/final。
4. 发送语音消息时，把 final transcript 作为用户消息 `content`。
5. 主后端按普通文本用户消息处理该 ASR 文本。
6. 对话历史只显示 ASR 文本，不显示用户语音气泡。

优点：

- 体验快。
- 复用现有实时 ASR。
- 不在服务器保存用户原始音频，隐私风险更低。

边界：

- 如果录音时网络差导致 ASR final 为空，则不发送消息。
- 如果 ASR partial 有内容但 final 超时，可让用户确认是否发送当前 partial。

### 7.3 本地临时展示

为了保留“用户发了语音”的即时感，Android 可以在发送前和刚发送后短暂显示本地态：

- 录音中：显示本地录音条、计时、partial ASR。
- 松开发送后：短暂显示“语音已转文字发送”或直接替换为用户文本气泡。
- 历史加载、重进会话、多设备同步时：只显示 ASR 文本。

该本地态不要求服务端参与，也不要求跨设备还原。

---

## 8. Voice Lab 接入细节

### 8.1 TTS 请求

主后端调用：

```http
POST https://voice.ponychat.org/jobs/tts
Content-Type: application/json
```

请求：

```json
{
  "voice_id": "twilight-soft",
  "text": "今天也想听听你发生了什么。",
  "language": "Auto",
  "instruct": "温柔地，语速稍慢",
  "max_new_tokens": 2048,
  "temperature": 0.9,
  "top_k": 50,
  "top_p": 1.0,
  "repetition_penalty": 1.05,
  "mobile_microphone": true
}
```

完成后下载：

```http
GET https://voice.ponychat.org/jobs/{job_id}/audio?variant=mobile
```

推荐使用 `variant=mobile`：

- 体积更小。
- 听感更像手机语音消息。
- 更贴合 QQ 风格。

### 8.2 超时建议

- 建立连接：5 秒。
- 创建 job：5 秒。
- 轮询间隔：1.2 秒。
- 后台任务总上限：40-60 秒。
- 熔断时间：180 秒。

### 8.3 分段情绪

第一版不做分段情绪。

第二阶段可用 `/jobs/tts/segmented`：

- 后端分析角色回复中的情绪段落。
- 或让 LLM 同时输出分段 TTS hints。
- 每段传不同 `instruct`。
- Voice Lab 拼接成一条音频。

---

## 9. 新增后端接口建议

### 9.1 后续：发送用户语音 ASR 文本（本阶段不做）

当前第一版不新增用户语音发送能力。本接口建议仅作为后续用户语音阶段参考。

用户语音不新增音频上传接口。Android 完成 ASR 后，复用 `/api/chat` 发送普通用户文本消息。

请求中的最后一条用户消息：

```json
{
  "role": "user",
  "content": "我刚才想说今天可能会晚点回来。",
  "metadata": {
    "input_modality": "voice",
    "asr_provider": "dashscope",
    "asr_duration_ms": 12340
  }
}
```

如果当前 `ChatMessage` 暂不支持 `metadata` 字段，后续用户语音阶段可先只发送 `content`，再补充轻量 metadata。

要求：

- 不上传用户原始音频文件。
- 不保存用户音频附件。
- 服务器只保存和处理 ASR 文本。

### 9.2 更新语音转写结果

该接口只用于角色语音文本状态补充，或未来需要修正 assistant voice metadata 时使用。当前第一版不涉及用户语音。

请求：

```json
{
  "username": "Jason",
  "conversation_id": "conv_xxx",
  "message_id": "msg_xxx",
  "attachment_id": "att_xxx",
  "transcript": "我刚才想说今天可能晚点回来。",
  "transcript_status": "ready"
}
```

### 9.3 重新生成角色语音

第二阶段接口：

```http
POST /api/messages/voice/regenerate
```

用途：

- 角色语音生成失败后手动重试。
- 用户切换音色后重新生成。
- 长按角色语音菜单“重新生成语音”。

注意：

- 重新生成成功后仍然只把音频下发给 App 本地缓存。
- 服务端只更新 `voice_job_id`、`voice_cache_key`、`tts_text`、`transcript`、`text_fragments` 等文本状态。

---

## 10. UI 细节规范

### 10.1 气泡尺寸

动态宽度：

```text
width = 88dp + durationSeconds * 3dp
范围：96dp 到 260dp
```

高度：

```text
42dp 到 46dp
```

时长格式：

- 12 秒：`12"`
- 65 秒：`1'05"`

### 10.2 状态

语音气泡状态：

- `idle`
- `loading`
- `playing`
- `paused`
- `failed`

转文字状态：

- `collapsed`
- `starting`
- `streaming`
- `ready`
- `failed`

### 10.3 文本展开卡片

角色左侧：

- 跟随角色气泡左边缘。
- 使用轻量 `surfaceVariant`。
- 字体略小于正文。
- 如果是角色语音的“转文字”，展示 `transcript`，也就是 TTS 使用的可朗读正文。
- 如果是语音回复中的括号文本片段，作为独立轻文本片段展示，不混入“转文字”结果。

用户侧：

- 当前第一版不做用户语音消息。
- 后续用户语音阶段若恢复，用户语音 ASR 展示在输入栏录音状态中，发送后进入历史的是普通用户文本气泡，不带语音展开卡片。

不建议把转文字结果作为新消息插入列表。

---

## 11. 分阶段实施计划

### 阶段 0：确认协议和配置

产出：

- 确认语音文本状态 JSON 结构。
- 确认角色配置字段。
- 确认 Voice Lab base URL 与生产环境变量。
- 确认 App 本地音频缓存索引和清理策略。
- 确认 `message_updated` 正式消息更新事件协议。
- 确认当前第一版不做用户语音消息，后续再单独排期。
- 确认角色 TTS 音频不进入服务器持久化存储。

验收：

- 文档确认后再开始代码。

### 阶段 1：后端语音文本状态存储

任务：

1. 新增 `message_voice_states` 独立表和 DAO，不直接依赖 `messages` 顶层字段。
2. 支持保存 `voice_status`、`voice_cache_key`、`tts_text`、`transcript`、`text_fragments`。
3. 确保搜索和历史接口返回可搜索文本，不返回音频 URL。
4. 增加基础测试。

验收：

- 构造带语音文本状态的 assistant 消息能保存、读取、历史恢复。
- 服务器不会保存角色 TTS 音频文件或永久 URL。
- 普通消息保存、历史刷新、旧客户端请求不会清空语音文本状态。

### 阶段 2：Voice Lab 客户端与回退

任务：

1. 新增 `voice_lab_client.py`。
2. 实现 `/jobs/tts`、轮询、下载。
3. 实现超时、熔断、错误归一。
4. 实现音频短期下发给 App，不写入主后端长期存储。

验收：

- Voice Lab 正常时能生成 MP3 并下发给在线 App 本地缓存。
- Voice Lab 关闭或超时时不影响文本回复。
- 日志能看到明确失败原因。
- 服务端磁盘/数据库不出现角色音频文件或音频 URL。

### 阶段 3：角色语音消息

任务：

1. 在普通聊天主模型前加入或复用导演步骤，输出本轮 `response_modality`。
2. 主模型按 `text` 或 `voice` 形态生成最终回复。
3. 当本轮为 `voice` 时，后端拆分 `tts_text` 与括号文本片段。
4. 用 `tts_text` 触发 TTS。
5. 成功后保存语音文本状态，通过 `message_updated` 下发短期音频结果给 App。
6. 失败时回退完整纯文本。
7. 支持角色级 `voice_enabled`、`voice_id` 和 `voice_decision_policy`。

验收：

- 开启语音的角色可收到语音文本状态，并在在线 App 中获得本地音频缓存。
- 关闭语音的角色仍为纯文本。
- Voice Lab 失效时 App 只看到文本，不报错。
- 导演选择 `text` 时不会触发 TTS。
- 导演选择 `voice` 时，括号文本不会进入 TTS 音频。
- 消息以 `message_updated` 正式事件完成本地音频缓存下发。
- App 重装后该消息退化为文本展示。

### 阶段 4：Android 语音气泡与播放

任务：

1. 解析消息语音文本状态。
2. 实现 `VoiceMessageBubble`。
3. 实现点击播放/暂停。
4. 实现长按菜单。
5. 实现角色语音“转文字”逐字展开。
6. 实现本地音频缓存索引。

验收：

- 当前 App 本地缓存存在时，角色语音可播放。
- 长按可转文字。
- 角色转文字无需网络。
- 无本地音频缓存时显示普通文本/原始 TTS 文本。
- 收到 `message_updated` 后可把对应 assistant 消息升级为语音展示。
- App 完全重装后，原音频消息位置显示文本。

### 阶段 5：主动消息和后台消息语音

任务：

1. 主动消息生成前运行同一套导演步骤。
2. 后台消息保存完整文本内容。
3. 如果导演选择 `voice`，后台生成 TTS 并向在线 App 下发本地缓存音频。
4. 在线 App 通过 `message_updated` 接收更新。
5. 离线通知仍以文本 preview 为主。

验收：

- 主动消息可生成角色语音并在在线 App 本地缓存。
- Voice Lab 失效时主动消息回退文本。
- 离线时不会自动播放语音。

### 阶段 6：体验优化

任务：

1. 未播放红点。
2. 播放中声波动画。
3. 语音播放进度细线。
4. 角色语音重新生成。
5. 分段情绪 TTS。
6. `message_updated` 事件可靠性和重连补偿。

### 后续阶段：用户语音录制、ASR 与文本发送（当前不做）

任务：

1. 输入栏加入语音模式。
2. 实现按住录音、松开发送、上滑取消。
3. 录音期间接入 `/ws/speech/dashscope` 或 `/ws/speech/aliyun`。
4. 松开发送时把 ASR final 作为普通用户文本消息发送。
5. 服务端只保存 ASR 文本，不保存用户音频。

验收：

- 用户可发送语音消息。
- 对话历史只显示用户语音的 ASR 文本。
- 服务端无用户录音文件、无用户音频附件。
- 太短/太长录音处理合理。

### 后续阶段：用户语音本地体验优化（当前不做）

任务：

1. 录音中显示 partial ASR。
2. 发送后平滑替换为用户文本气泡。
3. ASR final 为空时阻止发送并提示。

验收：

- 用户语音发送过程清晰。
- 历史和多设备同步只出现 ASR 文本。

---

## 12. 测试计划

### 12.1 后端单元测试

- 语音文本状态 JSON 原样保存。
- 导演输出 `text` 时跳过 TTS。
- 导演输出 `voice` 时拆分 `tts_text` 与括号文本片段。
- 括号文本不会进入 Voice Lab 请求。
- Voice Lab 客户端超时。
- Voice Lab 客户端 job failed。
- 熔断后直接跳过 TTS。
- 音频下发失败后回退或保持文本展示。
- 只有完整闭合括号对会从 `tts_text` 中剔除。
- 当前阶段不新增用户语音接口、用户语音附件或用户录音服务端文件。
- 角色语音请求不会创建服务端持久音频文件。

### 12.2 后端集成测试

- Voice Lab mock 成功：assistant 消息带语音文本状态和 `voice_cache_key`。
- Voice Lab mock 失败：assistant 消息只有文本。
- voice mock 成功时，消息状态带 `tts_text`、`transcript`、`text_fragments`。
- voice mock 成功时，主后端发送 `message_updated` 事件。
- 历史接口返回可搜索文本状态，不返回音频 URL。
- 当前阶段不新增用户语音 ASR 集成测试；后续用户语音阶段再补。
- 主动消息/后台消息可生成语音文本状态；Voice Lab 失败时回退文本。

### 12.3 Android 测试

- 角色语音气泡渲染。
- 角色语音旁边或下方正确显示括号文本片段。
- 当前阶段不新增用户语音气泡或录音发送入口。
- 播放/暂停/切换播放。
- 长按菜单。
- 角色语音逐字转文字。
- `message_updated` 到达后能更新对应 assistant 消息。
- 离开页面停止播放。
- App 本地音频缓存丢失时，消息退化为文本展示。
- App 完全重装后，历史只显示原始 TTS 文本和括号文本。
- 对话历史记录页面不显示音频气泡，只显示文本内容并可搜索。
- 深色/浅色主题。
- 小屏幕和大字体。

### 12.4 失败演练

- 关闭 Voice Lab。
- Voice Lab 返回 500。
- job 永远 queued。
- 音频下载 404。
- 本地音频文件丢失。
- Android 播放 URL 失败。
- 后续用户语音阶段再补 ASR WebSocket 断开演练。
- `message_updated` 丢失后，重新进入会话能从历史恢复文本状态，但不能恢复音频是预期行为。

---

## 13. 风险与处理

### 13.1 Voice Lab 不稳定

风险：

- GPU 服务偶尔失效或排队过长。

处理：

- 文本先返回。
- TTS 后台生成。
- 超时和熔断。
- 失败只保留文本。
- 熔断状态应反馈给导演步骤，使导演优先或强制选择 `text`。

### 13.2 消息后补复杂

风险：

- assistant 消息先返回文本，后续本地音频缓存需要同步到 Android。

处理：

- 一步到位实现 `message_updated` 正式更新事件，不做短等待方案。
- 消息以 `message_id` 作为更新锚点。
- 客户端重连或重新进入会话时，从历史接口重新拉取文本状态；若本地缓存音频仍存在则显示语音，否则显示文本。

### 13.3 历史兼容

风险：

- 老消息没有语音文本状态，或本地音频缓存不存在。

处理：

- Android 所有 voice state 解析都可空。
- 无本地音频缓存时走原文本气泡。

### 13.4 音频体积

风险：

- WAV 太大。

处理：

- 使用 Voice Lab 当前 MP3 输出。
- 角色语音优先下载 `variant=mobile`。
- 当前第一版不做用户语音；后续若恢复用户语音阶段，仍不上传、不存储服务端音频。
- 角色语音也不存储服务端音频，只存 App 本地缓存。

### 13.5 转文字误解

风险：

- 角色语音“转文字”不是真 ASR。

处理：

- 产品上不暴露技术细节。
- 因为角色语音本就由文本合成，直接显示原文更准确。

---

## 14. 推荐 MVP 范围

第一版一步到位包含：

1. 后端支持语音文本状态，但不保存音频。
2. 导演步骤决定本轮 `text` 或 `voice`。
3. 主模型按导演形态生成回复。
4. 角色语音只把完整闭合括号外的可朗读正文送入 Voice Lab。
5. Voice Lab 失败自动回退文本。
6. `message_updated` 正式事件向 App 下发短期音频结果，由 App 写入本地缓存。
7. Android 在本地音频存在时显示角色语音气泡、括号文本片段、播放状态。
8. 角色语音长按“转文字”，逐字展开 TTS 原文。
9. 主动消息、后台消息支持同一套角色语音生成和回退。
10. App 重装或缓存丢失后，原音频位置自动退化为文本。
11. App 对话历史记录页面只显示文本，方便搜索。

第一版不包含：

- 用户语音录制、实时 ASR、发送 ASR 文本。
- 用户语音气泡和用户语音本地体验优化。

可后续优化：

- 分段情绪 TTS。
- 重新生成语音。
- 更精细的声波动画和播放进度。
- `message_updated` 重连补偿的边缘体验。

原因：

- 当前已明确先不做用户语音；首版集中处理角色语音、消息后补、主动/后台消息语音和降级链路。
- 用户语音后续作为独立阶段推进，避免和角色语音状态、ASR 入口修复、Android 输入栏改造互相牵连。

---

## 15. 推荐最终路线

最终架构：

```text
Android App
  | 发送文本 / 播放角色语音 / 展开角色转文字
  v
PonyChat 主后端
  | 导演步骤判断本轮 text / voice
  | 主模型按本轮形态生成回复
  | 拆分可朗读正文与括号文本片段
  | 保存完整消息和角色语音文本状态
  | message_updated 下发短期音频结果
  | TTS 编排、熔断、回退
  v
Voice Lab
  | /jobs/tts
  | /jobs/tts/segmented
  | /jobs/{id}/audio
  v
Android App 私有音频缓存
```

这条路线能保证：

- Voice Lab 可用时，PonyChat 有完整语音消息体验。
- Voice Lab 不可用时，PonyChat 自动退回普通文本聊天。
- 角色语音的服务端历史只保留文本语义；音频只存在 App 本地。
- 后续可以继续扩展音色、分段情绪、自动播放、语音重生成。
