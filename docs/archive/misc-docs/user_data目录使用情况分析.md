# user_data 目录使用情况分析

## 📊 当前状态

### ✅ 仍在使用的文件

#### 1. `users.json` - **仍在使用**
- **位置**: `user_data/users.json`
- **用途**: 存储用户认证信息（用户名、密码哈希、创建时间、最后活跃时间等）
- **使用代码**:
  - `backend/utils.py`: `load_users()`, `save_users()`
  - `backend/routes/auth.py`: 用户注册、登录、修改密码
  - `backend/routes/chat.py`: 更新用户最后活跃时间
  - `backend/routes/admin/*`: 管理后台相关功能

**状态**: ⚠️ **未迁移到数据库，仍在使用文件系统**

---

### ❓ 可能已迁移的文件（需要确认）

#### 2. `{username}/characters.json`
- **位置**: `user_data/{username}/characters.json`
- **状态**: 
  - 如果 `DISABLE_FILESYSTEM = True`，应该已迁移到数据库
  - 但文件可能仍存在（旧数据）

#### 3. `{username}/conversations/`
- **位置**: `user_data/{username}/conversations/`
- **状态**: 
  - 如果 `DISABLE_FILESYSTEM = True`，应该已迁移到数据库
  - 但文件可能仍存在（旧数据）

#### 4. `{username}/galgame/`
- **位置**: `user_data/{username}/galgame/`
- **状态**: 
  - 如果 `DISABLE_FILESYSTEM = True`，应该已迁移到数据库
  - 但文件可能仍存在（旧数据）

#### 5. `{username}/settings.json`
- **位置**: `user_data/{username}/settings.json`
- **状态**: 
  - 如果 `DISABLE_FILESYSTEM = True`，应该已迁移到数据库
  - 但文件可能仍存在（旧数据）

---

## 🔍 代码分析

### 仍在使用的代码路径

#### 用户认证系统（必须保留）
```python
# backend/utils.py
def load_users() -> dict:
    users_file = os.path.join(USER_DATA_ROOT, "users.json")
    # 读取 users.json

def save_users(users: dict):
    users_file = os.path.join(USER_DATA_ROOT, "users.json")
    # 写入 users.json
```

#### 用户注册/登录（必须保留）
```python
# backend/routes/auth.py
users = load_users()  # 读取 users.json
save_users(users)      # 写入 users.json
```

---

### 已禁用文件系统写入的代码路径

#### 角色数据保存
```python
# backend/routes/characters.py
if not DISABLE_FILESYSTEM:
    await asyncio.to_thread(do_save_sync)  # 只在 DISABLE_FILESYSTEM=False 时执行
```

#### 用户设置保存
```python
# backend/routes/auth.py
if not DISABLE_FILESYSTEM:
    # 文件系统保存逻辑（已禁用）
```

---

## 📁 目录结构

```
user_data/
├── users.json                    ✅ 仍在使用（用户认证）
│
├── {username}/
│   ├── characters.json          ❓ 可能已迁移到数据库
│   ├── conversations/           ❓ 可能已迁移到数据库
│   ├── galgame/                 ❓ 可能已迁移到数据库
│   └── settings.json            ❓ 可能已迁移到数据库
```

---

## ✅ 结论

### `user_data` 目录**仍在使用**，但用途有限：

1. **必须保留**:
   - ✅ `users.json` - 用户认证系统仍在使用文件系统
   - ✅ 目录本身 - 用于创建用户子目录（即使不写入数据）

2. **可以清理**（如果确认已迁移到数据库）:
   - ❓ `{username}/characters.json` - 如果已迁移到数据库，可以删除
   - ❓ `{username}/conversations/` - 如果已迁移到数据库，可以删除
   - ❓ `{username}/galgame/` - 如果已迁移到数据库，可以删除
   - ❓ `{username}/settings.json` - 如果已迁移到数据库，可以删除

---

## 🎯 建议

### 选项 1: 保留目录（推荐）
- 保留 `user_data/` 目录和 `users.json`
- 清理已迁移的用户数据文件（characters.json, conversations/, galgame/, settings.json）
- 原因：用户认证系统仍在使用文件系统

### 选项 2: 完全迁移到数据库
- 将 `users.json` 也迁移到数据库
- 创建 `users` 表存储用户认证信息
- 更新所有使用 `load_users()` 和 `save_users()` 的代码
- 然后可以完全删除 `user_data` 目录

---

## 📝 当前配置

```python
# backend/config.py
DISABLE_FILESYSTEM = True  # 已禁用文件系统写入（除了 users.json）
```

**注意**: `DISABLE_FILESYSTEM = True` 只影响角色、对话、设置等数据，**不影响用户认证系统**（users.json）。
