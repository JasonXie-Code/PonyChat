# 管理后台重构计划：角色管理合并 + 素材管理

> 文档状态：2026-08-09 已复核。本文是计划或审计记录，结论对应其记录时点；当前实现与风险以 `docs/PROJECT_STATUS.md` 和代码为准。

> 日期：2026-05-17  
> 涉及功能：①合并「角色大厅 + 网页角色」→「角色管理（4）」；②新增「素材管理（5）」
>
> **代码现状（2026-05-18）**：角色管理合并与素材管理已落地。`/admin/web-chars` 前端路由已重定向到 `/admin/characters`，兼容 API 仍保留；素材文件不再落盘到 `Backend/static/assets/`，而是以 BLOB 存储在 SQLite `media_assets.file_data`，通过 `GET /api/admin/assets/{asset_id}/file` 返回。

---

## 一、角色管理合并

### 核心思路

原「网页角色」页面的本质是维护一份 `web_chars.json` ID 列表，用于控制哪些角色在官网 `/app` 对访客展示。
将这个开关 inline 进每个角色的编辑弹层，与已有的「在大厅公开」并排放置，即可消除独立页面。

「在大厅公开」和「在网页公开」是两套独立逻辑，需分别处理：
- `isPublic` → 写入 `hall_characters` 表，控制 App 内角色大厅可见性
- `isWebVisible` → 写入 `characters.is_web_visible` 列，控制官网展示

---

### 改动文件（共 9 个）

#### 后端（4 个）

**1. `Backend/db/database.py`**
- `_migrate_columns` 的 `migrations` 列表追加：
  ```python
  ("characters", "is_web_visible", "INTEGER DEFAULT 0"),
  ```
- 在 `init()` 的迁移逻辑完成后，加一次性数据导入函数 `_migrate_web_chars_json(db)`：
  - 读取 `data/web_chars.json` 获取现有 ID 列表
  - 执行 `UPDATE characters SET is_web_visible=1 WHERE id IN (...)`
  - 成功后将 `web_chars.json` 重命名为 `web_chars.json.migrated`（防止重复执行）

**2. `Backend/web_visibility.py`**
- `get_public_web_characters()`：
  - 删除 `ids = load_web_character_ids()` 及 JSON 相关逻辑
  - 改为直接查 `WHERE ch.is_web_visible = 1 AND COALESCE(ch.is_hidden, 0) = 0`
  - 排序改为 `ORDER BY ch.sort_order DESC, ch.created_at DESC`
- `load_web_character_ids()` / `save_web_character_ids()`：保留函数但加 deprecated 注释

**3. `Backend/routes/admin/characters.py`**
- `list_all_characters`：
  - SELECT 加 `COALESCE(ch.is_web_visible, 0)` 列（追加在 `sort_order` 之后）
- `_parse_char_row(row)`：
  - 解包参数增加 `is_web_visible`（第 13 位）
  - 返回值加 `"isWebVisible": bool(is_web_visible)`
- `edit_character`：
  - 处理请求体中的 `isWebVisible` 字段
  - 直接写入 `direct_updates["is_web_visible"] = int(bool(body["isWebVisible"]))`
- `create_character`：
  - 同理处理 `isWebVisible`，插入时赋值给 `characters.is_web_visible`

**4. `Backend/routes/admin/web_chars_routes.py`**
- 不修改，不删除，路由继续挂载。前端不再主动调用，后端 API 仍存在供兼容。

---

#### 前端（5 个）

**5. `src/api/admin.js`**
- `fetchWebCharacterIds` 和 `saveWebCharacterIds` 函数保留，但不再被主流程使用。

**6. `src/views/admin/sections/CharactersSection.vue`**

| 位置 | 改动内容 |
|------|---------|
| `editForm` reactive 对象 | 加 `isWebVisible: false` |
| `createForm` reactive 对象 | 加 `isWebVisible: false` |
| `openEdit(c)` | 加 `editForm.isWebVisible = !!c.isWebVisible` |
| `openCreate()` | 加 `createForm.isWebVisible = false` |
| `saveEdit()` | 传参加 `isWebVisible: editForm.isWebVisible` |
| `saveCreate()` | 传参加 `isWebVisible: createForm.isWebVisible` |
| 编辑弹层 modal-body | 「在大厅公开」checkbox 下方加一行「在网页公开」checkbox（`row-inline` 样式复用） |
| 创建弹层 modal-body | 同上 |
| 列表表头 `list-head` | `col-pub`（大厅）之后加 `col-web`（网页），点击排序 `toggleSort('web')` |
| 列表行 `list-row` | 加 `col-web` 单元格，badge 复用 `badge-on/badge-off` |
| `filtered` computed 排序 | 加 `sk === 'web'` 分支，`cmpNum(a.isWebVisible ? 1 : 0, ...)` |
| CSS grid-template-columns | `44px /* pub */` 后加 `44px /* web */` |

**7. `src/views/admin/AdminLayout.vue`**

```js
// navItems 改为（删除 web-chars 条目，characters label 改名，后续 kbd 顺移）
const navItems = [
  { to: '/admin/overview',       label: '数据概览', ion: 'bar-chart-outline',          kbd: '1' },
  { to: '/admin/users',          label: '用户管理', ion: 'people-outline',              kbd: '2' },
  { to: '/admin/conversations',  label: '对话记录', ion: 'chatbubble-ellipses-outline', kbd: '3' },
  { to: '/admin/characters',     label: '角色管理', ion: 'planet-outline',              kbd: '4' }, // ← 改名
  { to: '/admin/assets',         label: '素材管理', ion: 'albums-outline',              kbd: '5' }, // ← 新增
  { to: '/admin/invites',        label: '邀请码',   ion: 'pricetags-outline',           kbd: '6' },
  { to: '/admin/models',         label: '模型配置', ion: 'hardware-chip-outline',       kbd: '7' },
  { to: '/admin/recovery',       label: '数据恢复', ion: 'construct-outline',           kbd: '8' },
  { to: '/admin/system',         label: '系统设置', ion: 'settings-outline',            kbd: '9' },
]
const digitRoutes = navItems.map(i => i.to) // 直接派生
```

- template：删除侧边栏 `webCharCount` badge 的 `v-if` 条件判断（整个 `<span v-if="item.to === '/admin/web-chars'...">` 删掉）
- script：删除 `webCharCount` ref 和 `loadWebCharCount()` 函数及其 `onMounted` 调用

**8. `src/components/admin/CommandPalette.vue`**
- `NAV` 常量同步修改，删除 `web-chars` 条目，`characters` label 改为「角色管理」，插入「素材管理」

**9. `src/router/index.js`**
- 删除 `import WebCharsSection from '...'` 这一行
- `web-chars` 子路由改为：
  ```js
  { path: 'web-chars', redirect: '/admin/characters' }
  ```
- `characters` 路由 `meta.title` 改为 `'PonyChat — 角色管理'`
- 新增 `assets` 子路由（见第二部分）

---

## 二、素材管理（新功能）

### 核心定位

作为角色多模态回复的**基础素材库**，当前阶段专注于**图片（含动图）**管理，为后续「角色在聊天中插入表情包」提供可被大模型检索的结构化数据基础。

每张图片需要打上多维度标签（情绪 / 强度 / 使用场景 / 年龄分级），以及一句人话描述，大模型在生成回复时依据当前对话语境从库中检索匹配度最高的表情包并嵌入响应。

**分类预设（`category` 字段值）**

| 值 | 含义 |
|----|------|
| `emoji` | 表情包（最常用，优先支持） |
| `sticker` | 贴纸（PNG/WebP 透明背景） |
| `bg` | 背景图 |
| `misc` | 其他 |

**支持的图片格式**

只接受图片，含动图：`image/jpeg`、`image/png`、`image/gif`、`image/webp`、`image/apng`

动图识别规则：`is_animated = 1` 当 mime_type 为 `image/gif` 或 `image/apng`；WebP 则由后端读取文件头判断是否含 ANIM chunk。

**文件存储策略（以当前代码为准）**

文件二进制写入 SQLite：`media_assets.file_data`。列表和检索接口返回 `file_url: "/api/admin/assets/{asset_id}/file"`，前端 `<img>` 直接使用该 URL；后端在 `Backend/routes/admin/assets_routes.py` 中从数据库读取 BLOB 并返回图片响应。

---

### 标签体系设计

每个素材有 **4 个结构化标签维度 + 自定义标签 + 描述**，由管理员在上传时填写，大模型检索时据此过滤：

#### 1. 情绪标签 `emotions`（JSON array，多选）

| 值 | 含义 | 值 | 含义 |
|----|------|----|------|
| `happy` | 开心 | `sad` | 难过 |
| `excited` | 兴奋 | `cry` | 哭泣 |
| `laugh` | 大笑/LOL | `angry` | 生气 |
| `shy` | 害羞 | `surprised` | 惊讶 |
| `cute` | 撒娇/卖萌 | `scared` | 害怕 |
| `smug` | 得意 | `disgusted` | 厌恶 |
| `aggrieved` | 委屈 | `speechless` | 无语 |
| `anticipate` | 期待 | `neutral` | 平静/无表情 |

#### 2. 强度 `intensity`（单选，默认 `moderate`）

表示情绪表达的激烈程度，帮助大模型在同一情绪下区分轻重场合。

| 值 | 含义 |
|----|------|
| `mild` | 轻度（微笑、淡定、轻微反应） |
| `moderate` | 中等（默认，日常表达） |
| `strong` | 强烈（爆笑、崩溃、极度兴奋、暴怒） |

#### 3. 使用场景标签 `scenes`（JSON array，多选）

| 值 | 含义 | 值 | 含义 |
|----|------|----|------|
| `greeting` | 打招呼 | `farewell` | 道别 |
| `congratulate` | 祝贺 | `celebrate` | 庆祝 |
| `comfort` | 安慰 | `encourage` | 鼓励 |
| `tease` | 调侃/吐槽 | `agree` | 认同/支持 |
| `refuse` | 拒绝/反对 | `question` | 提问/疑惑 |
| `love` | 表达爱意 | `casual` | 日常闲聊 |

#### 4. 年龄分级 `age_rating`（单选，默认 `all`）

| 值 | 含义 |
|----|------|
| `all` | 全年龄（默认，安全）|
| `teen` | 青少年（含轻度色情/暴力元素）|
| `adult` | 成人 R18（需角色配置允许） |

#### 5. 自定义标签 `custom_tags`（JSON array，自由文本）

供管理员补充预设选项未覆盖的信息，例如角色名、IP、特殊情境。

#### 6. 描述 `description`（短文本，建议 ≤30字，重要）

**这是大模型检索时信息量最大的字段**。一句人话说清楚这张图适合在什么时候用，远比结构化标签更直观。例如：「小马抱头蹲地，适合表达无奈踩坑」。上传时应尽量填写，不作强制但 UI 应予以突出提示。

---

### 大模型检索接口设计

后续角色聊天时，后端在构建 system prompt 或 tool call 前，调用以下内部接口获取候选表情包：

```
GET /api/admin/assets/suggest
    ?emotions=happy,excited
    &intensity=moderate
    &scenes=greeting
    &age_rating=all
    &limit=5
```

返回格式（供注入系统提示词或作为 LLM 工具调用结果）：

```json
[
  {
    "id": "abc123",
    "name": "开心挥手",
    "description": "小马开心地挥手，适合打招呼或表达高兴",
    "file_url": "/api/admin/assets/abc123/file",
    "is_animated": true,
    "emotions": ["happy", "excited"],
    "intensity": "moderate",
    "scenes": ["greeting"],
    "age_rating": "all"
  }
]
```

大模型在生成回复时，可以在消息末尾附加 `[emoji:abc123]` 之类的占位符，客户端/后端渲染层再替换为真实图片 URL。具体占位符协议由多模态回复功能实现时确定，此处只保证素材库接口提前就绪。

---

### 数据库表 `media_assets`

在 `Backend/db/database.py` 的 `SCHEMA_SQL` 中追加：

```sql
-- 素材库（表情包、贴纸、背景等多模态基础资源）
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'emoji',   -- emoji / sticker / bg / misc
    file_size INTEGER,
    mime_type TEXT,                           -- image/jpeg, image/png, image/gif, image/webp, image/apng
    is_animated INTEGER DEFAULT 0,           -- 1 = 动图（GIF / APNG / animated WebP）
    emotions TEXT DEFAULT '[]',              -- JSON array: ["happy", "excited"]
    intensity TEXT DEFAULT 'moderate',       -- "mild" / "moderate" / "strong"
    scenes TEXT DEFAULT '[]',               -- JSON array: ["greeting", "tease"]
    age_rating TEXT DEFAULT 'all',          -- "all" / "teen" / "adult"
    flirt_level INTEGER DEFAULT 0,
    send_policy TEXT DEFAULT 'always',
    min_relationship_stage TEXT DEFAULT 'stranger',
    sender_archetypes TEXT DEFAULT '[]',
    blocked_archetypes TEXT DEFAULT '[]',
    custom_tags TEXT DEFAULT '[]',          -- 自定义自由文本标签 JSON array
    description TEXT DEFAULT '',            -- 人话描述（≤30字），LLM 检索最直接的依据
    file_data BLOB,
    uploader_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_media_assets_category ON media_assets(category);
CREATE INDEX IF NOT EXISTS idx_media_assets_age ON media_assets(age_rating);
CREATE INDEX IF NOT EXISTS idx_media_assets_intensity ON media_assets(intensity);
CREATE INDEX IF NOT EXISTS idx_media_assets_created ON media_assets(created_at DESC);
```

同时在 `_migrate_columns` 的 `allowed_tables` 集合中加入 `"media_assets"`。

---

### 改动文件（共 7 个，含 2 个新建）

#### 后端（4 个，含 1 个新建）

**新建 `Backend/routes/admin/assets_routes.py`**

```
路由前缀：/assets

GET    /assets              分页列表，?category=&emotions=&intensity=&scenes=&age_rating=&search=&page=&page_size=
POST   /assets/upload       上传图片（multipart/form-data）
                            字段：file, name, category, emotions(JSON), intensity,
                                  scenes(JSON), age_rating, custom_tags(JSON), description
PUT    /assets/{id}         修改 name / emotions / intensity / scenes / age_rating / custom_tags / description / category
DELETE /assets/{id}         删除文件 + 删数据库记录
GET    /assets/categories   返回各分类数量统计 [{category, label, count}]
GET    /assets/suggest      供内部/角色系统检索，?emotions=&intensity=&scenes=&age_rating=&limit=
```

**上传逻辑：**
1. 校验 mime_type 仅允许 `image/jpeg / image/png / image/gif / image/webp / image/apng`
2. 判断 `is_animated`：GIF/APNG 直接标记；WebP 读取文件前 16 字节判断是否含 `ANIM` chunk
3. 生成素材 UUID
4. 将图片二进制写入 `media_assets.file_data`
5. 插入 `media_assets` 表
6. 返回完整的 asset 对象

**修改 `Backend/db/database.py`**
- `SCHEMA_SQL` 追加 `media_assets` 建表 SQL（见上方）
- `_migrate_columns` 的 `allowed_tables` 加 `"media_assets"`

**修改 `Backend/routes/admin/__init__.py`**
```python
from . import ..., assets_routes  # 加入 import
router.include_router(assets_routes.router)  # 挂载路由
```

**文件服务**
- 当前素材文件服务由 `GET /api/admin/assets/{asset_id}/file` 提供，不需要额外 `/static` 挂载。

---

#### 前端（3 个，含 1 个新建）

**新建 `src/views/admin/sections/AssetsSection.vue`**

页面布局：左侧分类筛选栏 + 右侧内容区：

```
┌──────────────────────────────────────────────────────┐
│  工具栏：[搜索名称/标签] [上传图片] [刷新]  共 XX 个  │
├────────────┬─────────────────────────────────────────┤
│ 全部        │  筛选栏（横排）：                        │
│ 表情包 (12) │  情绪 [全部▼]  场景 [全部▼]  分级 [全部▼]│
│ 贴纸  (5)  ├─────────────────────────────────────────┤
│ 背景  (3)  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  │
│ 其他  (2)  │  │ 预览 │ │ 预览 │ │ 预览 │ │ 预览 │  │
│            │  │ 名称 │ │ 名称 │ │ 名称 │ │ 名称 │  │
│            │  │标签组│ │标签组│ │标签组│ │标签组│  │
│            │  └──────┘ └──────┘ └──────┘ └──────┘  │
│            │               ... 分页 ...              │
└────────────┴─────────────────────────────────────────┘
```

**素材卡片（网格布局）：**
- 预览区：直接显示图片（动图自动播放）；卡片右上角有「动图」徽章
- 名称
- 标签组：情绪 badge（紫色）+ 场景 badge（蓝色）+ 年龄分级 badge（红/黄/绿）
- 鼠标悬停浮层：「编辑标签」「删除」按钮

**上传弹层（点击「上传图片」打开 modal）：**
- 拖拽区 + 点击选择（`accept="image/jpeg,image/png,image/gif,image/webp"` ）
- 支持多文件选择；文件列表可逐个填写标签，或批量套用同一组标签
- 每个文件的标签表单：
  - **描述**（单行文本，置顶，建议填写≤30字，UI 标注「大模型检索时最直接的依据」）
  - 名称（文本输入，默认文件名）
  - 分类（下拉：表情包 / 贴纸 / 背景 / 其他）
  - 情绪（多选 chip 组，预设 16 个选项）
  - 强度（单选 radio：轻度 / 中等✓ / 强烈）
  - 场景（多选 chip 组，预设 12 个选项）
  - 年龄分级（单选：全年龄 / 青少年 / 成人）
  - 自定义标签（tag input，回车追加）
- 确认后逐个调用上传 API，展示进度条

**编辑标签弹层（点击素材卡片「编辑标签」打开）：**
- 与上传表单相同的结构，回显当前值，保存时调用 `PUT /assets/{id}`
**修改 `src/api/admin.js`**

追加以下函数（写在文件末尾）：
```js
export async function fetchAssets(params = {})         // GET /assets
export async function uploadAsset(formData)            // POST /assets/upload (FormData)
export async function updateAsset(id, payload)         // PUT /assets/{id}
export async function deleteAsset(id)                  // DELETE /assets/{id}
export async function fetchAssetCategories()           // GET /assets/categories
export async function suggestAssets(params = {})       // GET /assets/suggest（内部/角色系统用）
```

**修改 `src/router/index.js`**
```js
import AssetsSection from '../views/admin/sections/AssetsSection.vue'
// 在 characters 路由后加：
{
  path: 'assets',
  name: 'admin-assets',
  component: AssetsSection,
  meta: { title: 'PonyChat — 素材管理', description: 'PonyChat 素材库管理。' },
},
```

---

## 三、执行顺序

```
Step 1  后端 DB
        database.py → 加 is_web_visible 迁移 + media_assets 表 + _migrate_web_chars_json()

Step 2  后端路由
        characters.py → 加 isWebVisible 字段读写
        web_visibility.py → 改为查 DB 列
        新建 assets_routes.py
        __init__.py → 挂载 assets_routes

Step 3  前端：角色管理
        CharactersSection.vue → 双 checkbox + col-web 列
        AdminLayout.vue → 删 web-chars，改标签，加 assets
        CommandPalette.vue → 同步 NAV
        router/index.js → redirect + 新路由

Step 4  前端：素材管理
        api/admin.js → 追加 asset 函数
        新建 AssetsSection.vue

Step 5  验证
        重启后端 → 检查迁移日志（is_web_visible 列 + web_chars 导入）
        前端 npm run build → 检查报错
        手动测试：编辑角色勾选「在网页公开」→ 刷新官网 /app 确认可见
        手动测试：上传一张表情包 → 确认列表返回 file_url，浏览器可打开 /api/admin/assets/{id}/file
```

---

## 四、遗留清理（后续可做，不影响功能）

- 删除 `src/views/admin/sections/WebCharsSection.vue`（现已无路由指向）
- 删除 `api/admin.js` 中的 `fetchWebCharacterIds` / `saveWebCharacterIds`
- 删除 `Backend/routes/admin/web_chars_routes.py`
- `web_visibility.py` 中彻底移除 JSON 相关函数
