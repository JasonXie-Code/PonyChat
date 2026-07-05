# MBTI（小马 / 标准 双站点）

- **`Common/`**：共用前端源码（Vite 别名 `@common`）、`Common/package.json` 供 TypeScript 解析依赖。
- **`MLP/web/`**：小马情境变体；数据在 `MLP/web/src/data/`（别名 `@data`）。
- **`Standard/web/`**：标准情境变体；数据在 `Standard/web/src/data/`。

开发与构建请在 **PonyChat 仓库根** 下进入对应变体目录执行：

```text
cd PonyChat-Website/MBTI/MLP/web    # 或 PonyChat-Website/MBTI/Standard/web
npm install
npm run dev
npm run build
```

一键启动可使用各变体根目录的 `启动网站.bat`（依赖仓库根 `misc/tools` 等路径不变）。
