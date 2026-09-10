# MLP MBTI 同人站

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

## 服务器密钥：唯一来源与用法

**`misc/deploy_mbti_server_usa.py`** 等向美国机同步静态资源时：**连接信息与密钥路径的唯一权威**为工作区外的 `P:\ServerKeys\servers.json`；规范见仓库根目录 [`ServerKeys.md`](../../../ServerKeys.md)；Python 优先复用 `P:\ServerKeys\ssh_lib.py`。

## 项目定位

面向同人圈、**手机访问为主**的娱乐向 MBTI 测试站点：在小马情境化题目中测出访问者的四字母类型，并给出「适合做朋友 / 适合伴侣」的类型推荐与典型小马；测试后可浏览已收录的**小马 MBTI 百科**。本站非临床心理测评，非孩之宝官方产品。

## 核心约定

| 项目 | 说明 |
|------|------|
| 语言 | 首版简体中文 |
| 角色译名 | 全站统一为**大陆 TV 版**常用译名（如 紫悦、碧琪、柔柔、云宝、珍奇、苹果嘉儿） |
| 典型小马 | 优先 **M6** 与主线高辨识度角色；**伴侣向**一行展示须与用户**自称性别相反**一侧的代表角色（见 `typicalPonies.ts` / `ponyForPartner`；无法识别性别时默认女性向名单） |
| 人口学 | 性别为**男 / 女**二选一（界面**左男右女**）；年龄须为 **1–100** 的整数，仅存本机会话 |
| 测试版本 | 题库 **72** 题；单次测验随机抽取 **36** 题（每轴 9 题）或 **12** 题（每轴 3 题），展示顺序打乱 |
| 题目 | 在四轴 MBTI 框架下做**小马场景化**原创表述 |
| 友伴推荐 | **基于维度的可解释规则**（朋友 = 仅翻转 E/I；伴侣 = 仅翻转 J/P）；长说明见 `compatExplain.ts`（16 型定制 + 伴侣向文末统一注记，避免与 `ponyForPartner` 举例冲突） |
| 视觉 | 前台与 **PonyChat 主站**一致的深色 slate + 紫青渐变顶栏与背景；移动优先、响应式布局；使用官方素材时须标注版权归孩之宝，站点无盈利 |
| 用户 | **无需注册**；匿名 ID 关联会话与存档 |
| 数据 | 开始测试前**明确告知**；**当前**测验结果与作答仅存浏览器 **localStorage**，**不上传**；规划中的后端将支持持久化与每题核对 |

## 技术形态

- **前端**：SPA（移动优先布局与交互）
- **后端**（规划中）：REST API；匿名会话；测验与作答持久化；管理端百科 CRUD（独立鉴权）
- **部署**：静态资源 **`web/dist`**；生产环境示例为 **Nginx** + `try_files` SPA 回退；域名与服务器由运维配置

### 当前实现

- **栈**：Vite + React + TypeScript + React Router；`index.html` 的 viewport 含 `interactive-widget=resizes-content`，与主站聊天页一致，便于 Android Chrome 在虚拟键盘弹出时调整布局视口。
- **数据**：测验结果、性别、年龄、题序与作答仅存浏览器 **localStorage**（键名见 `SessionContext`）。
- **运行**：见 [README.md](README.md)；根目录 **`启动网站.bat`** 调用 **`misc/start_dev.py`** 启动 `web` 开发服务。
- **生产部署**：与美国主站同机 Nginx 时，静态目录多为 **`/var/www/mbti-ponychat-static`**（与 `PonyChat-Website/Main/deploy/server-usa/nginx-ponychat-www.conf` 中 `mbti.ponychat.org` 的 `root` 一致）；旧配置或 **`misc/deploy.ps1`** 默认可能仍指向 **`/var/www/mbti`**。**`misc/deploy_mbti_server_usa.py`** 会同时更新上述两路径（先上传主目录，再在服务器 `cp -a` 镜像），避免 Nginx 仍绑旧 `root` 时公网看不到新构建。站点片段配置见 **`misc/nginx-mbti.ponychat.org.conf`**。公网访问域名示例 **`mbti.ponychat.org`**（以实际 DNS 为准）。

## 仓库内关键路径（随实现补充）

- 前端应用与路由：`web/src/`（入口 `web/src/main.tsx`、`web/src/App.tsx`）
- 16 型释义：`web/src/data/mbtiTypes.ts`（结果页「类型在说什么」与四字母释义）
- 友伴区块：`web/src/data/compatExplain.ts`（16 型 × 友/伴定制说明；伴侣段与 `ponyForPartner` 一致）
- 典型小马映射：`web/src/data/typicalPonies.ts`
- 题库与计分：**权威数据** [docs/questions.json](docs/questions.json)；计分与 12 题子集见 [docs/SCORING.md](docs/SCORING.md)
- 权利与免责备忘：[docs/RIGHTS_AND_DISCLAIMER.md](docs/RIGHTS_AND_DISCLAIMER.md)
- 友伴规则版本化配置（如 JSON，阶段 3）

## 文档

- [README.md](README.md)：本地运行、构建、部署命令
- [ROADMAP.md](ROADMAP.md)：阶段目标与任务顺序
- [docs/SCORING.md](docs/SCORING.md)：四轴计分、平局规则、12 题固定题号
- [docs/RIGHTS_AND_DISCLAIMER.md](docs/RIGHTS_AND_DISCLAIMER.md)：题库权利、娱乐向声明、素材标注备忘
