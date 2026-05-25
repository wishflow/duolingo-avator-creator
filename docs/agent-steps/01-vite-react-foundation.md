# 01. Vite + React + TypeScript 前端基建迁移

## 1. 目标

本步骤只做前端工程化迁移，不做产品功能变更。

目标：

- 引入 Vite + React + TypeScript。
- 尽量保持当前桌面端、移动端 UI 和功能一致。
- 继续支持 GitHub Pages 和 Cloudflare Pages 的 `_site` 静态发布目录。
- 使用 npm 包 `@rive-app/canvas`，不再依赖 `unpkg` Rive runtime。
- 建立稳定的测试 hook，为后续多轮 agent、图文教程和 ZIP 导出打基础。

不做：

- 不修改 Worker AI 行为。
- 不迁移 Worker TypeScript。
- 不修复 `verify/generate` 竞态。
- 不做多轮 conversation thread。
- 不做图文教程。
- 不做 ZIP 导出。
- 不接入 Cloudflare Agents SDK。

## 2. 当前状态

当前前端主要集中在 `assets/avatar_explorer.html`：

- HTML、CSS、业务逻辑全部在同一个文件。
- Rive runtime 通过 `https://unpkg.com/@rive-app/canvas@2.37.8/rive.js` 加载。
- 静态发布命令复制 `assets/*` 到 `_site/`，再把 `assets/avatar_explorer.html` 复制为 `_site/index.html`。
- E2E 测试直接访问 `assets/avatar_explorer.html`，并依赖若干全局变量和函数。

迁移后，页面应成为 Vite 构建产物，但对用户和部署来说仍是静态站点。

## 3. 目标目录结构

建议结构：

```text
.
├── assets/
│   ├── avatar_builder_config.json
│   ├── avatar_builder_25_sept2025.riv
│   ├── *.svg
│   ├── avatar-icon-*.png
│   └── manifest.webmanifest
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── styles.css
│   ├── rive/
│   │   ├── riveRuntime.ts
│   │   ├── avatarState.ts
│   │   └── tileRenderer.ts
│   ├── ui/
│   │   ├── PreviewPanel.tsx
│   │   ├── OptionsPanel.tsx
│   │   ├── ToolRail.tsx
│   │   ├── MobileActionBar.tsx
│   │   └── GeneratePanel.tsx
│   ├── state/
│   │   ├── localAvatarStore.ts
│   │   └── historyStore.ts
│   └── testHooks.ts
├── index.html
├── vite.config.ts
├── worker/
│   └── index.js
└── docs/
```

说明：

- `src/` 放 React 前端代码。
- `worker/` 暂时保持现状，后续第 2 步再迁移 TypeScript。
- `assets/` 继续存 Rive、JSON、SVG、manifest、icon 等静态资源。
- `index.html` 作为 Vite 入口。
- Vite 构建输出目录固定为 `_site`。

## 4. 构建配置

`vite.config.ts` 要求：

| 配置 | 目标 |
| --- | --- |
| `base: './'` | 兼容 GitHub Pages 项目路径和 Cloudflare Pages 根路径 |
| `build.outDir: '_site'` | 保持现有部署目录 |
| `build.emptyOutDir: true` | 避免旧文件污染 |
| 静态资源复制 | 确保 Rive、JSON、SVG、manifest、icon 进入 `_site` |

`package.json` 调整方向：

| script | 行为 |
| --- | --- |
| `build:site` | 改为 `vite build` |
| `test:static` | 检查 Vite 产物和本地资源引用 |
| `test:e2e` | 继续跑现有 Python CDP 测试 |
| `test:worker` | 暂不改变 |
| `test:ci` | 仍然先静态、Worker，再强制 Chrome E2E |

依赖方向：

- 新增 `vite`、`typescript`、`react`、`react-dom`。
- 继续使用 `@rive-app/canvas` npm 包。
- 本步骤不新增 `jszip`，ZIP 导出放到第 8 步。

## 5. 功能等价要求

迁移后必须保持以下行为：

| 功能 | 要求 |
| --- | --- |
| 头像加载 | 默认 Rive 文件正常加载 |
| 预览 | 主 canvas 正常渲染，背景色同步 |
| 分类切换 | Body / Eyes / Hair / Face / Beard / Hat / Shirt / BG 可用 |
| tile 选择 | feature tile 可点击并更新头像 |
| 颜色选择 | swatch 可点击并更新头像 |
| Reset | 恢复默认头像 |
| Export PNG | 导出当前头像 |
| 本地保存 | 刷新后恢复当前头像 state |
| Undo/Redo | 按钮和快捷键保持可用 |
| Generate 页面 | 现有 AI 页面保持可打开，但不改行为 |
| 移动端布局 | 预览固定在上方，分类在预览下方，底部全局操作栏保留 |

## 6. 测试 hook 设计

现有 E2E 依赖全局变量，迁移后应收敛到一个稳定对象：

```ts
declare global {
  interface Window {
    __avatarTestHooks?: {
      isReady(): boolean;
      getState(): Record<string, number | boolean>;
      setStatePatch(patch: Record<string, number | boolean>): boolean;
      switchTab(index: number): void;
      exportPngForTest(): string;
      openGeneratePage(): void;
      undo(): void;
      redo(): void;
      getTileCount(): number;
      getLayoutSnapshot(): unknown;
    };
  }
}
```

要求：

- 只暴露测试需要的稳定能力。
- 不让测试依赖内部 React state 变量名。
- 旧测试可以先通过兼容层过渡，但最终应迁移到 `__avatarTestHooks`。

## 7. 迁移策略

建议分步迁移，避免一次性重写造成行为回归：

1. 建立 Vite + React + TS 空壳，先能构建 `_site`。
2. 把现有 HTML 结构拆成 React 组件，保持 class 名和布局基本一致。
3. 把现有 CSS 移入 `src/styles.css`，不做大幅视觉改版。
4. 把 Rive 初始化、state machine 输入、tile 渲染抽到 `src/rive/`。
5. 把 localStorage、本地历史、Undo/Redo 抽到 `src/state/`。
6. 加 `__avatarTestHooks`，更新 E2E 测试访问方式。
7. 确认 `npm run build:site` 生成 `_site/index.html` 和所有静态资源。

迁移期间允许保留局部命令式 DOM 操作，但最终应让 React 管页面结构，Rive canvas 渲染仍由 imperative API 管。

## 8. 部署兼容

必须保持：

- GitHub Pages URL 不变：`https://wishflow.github.io/duolingo-avator-creator/`
- Cloudflare Pages URL 不变：`https://duolingo-avator-creator.pages.dev/`
- Worker URL 不变：`https://duolingo-avator-creator.wei-shi-ws.workers.dev/`
- `_site` 仍是两个 Pages 平台的发布目录。
- GitHub Actions 仍必须先测试、再部署。

静态资源路径要求：

- 构建产物中 Rive、JSON、SVG、manifest、icon 均可通过相对路径访问。
- `base: './'` 必须覆盖 GitHub Pages 项目路径场景。
- 不引入运行时 CDN 依赖。

## 9. 测试计划

本步骤完成后至少运行：

```bash
npm run test:static
npm run test:worker
npm run build:site
npm run test:e2e
git diff --check
```

说明：

- 本地无 Chrome 时，`npm run test:e2e` 可按现有逻辑跳过。
- CI 中 `npm run test:ci` 必须安装 Chrome 并完整通过。
- `test:worker` 暂不改变，因为 Worker 不在本步骤范围内。

E2E 验收场景：

| 场景 | 预期 |
| --- | --- |
| 页面加载 | Rive 主头像和 tile 正常出现 |
| 选择 tile | 当前头像变化，选中态更新 |
| 选择颜色 | 当前头像和背景变化 |
| Reset | 恢复默认头像 |
| Export PNG | 能导出非空 PNG |
| 本地保存 | 修改后刷新仍恢复 |
| Undo/Redo | 能回退和恢复 |
| 移动端 | 预览固定，选项区滚动，底部操作栏不遮挡 |
| Generate 页面 | 能打开和返回，现有行为不变 |

## 10. 验收标准

本步骤算完成，必须满足：

- Vite + React + TypeScript 构建成功。
- `_site` 可直接作为 GitHub Pages / Cloudflare Pages 静态产物。
- 当前头像编辑器核心功能无回归。
- CI 完整通过并自动部署成功。
- Worker 行为与 API 不被本步骤修改。
- 文档、代码、测试一次性提交并推送。

## 11. 明确不处理的问题

这些问题已进入 roadmap，但不在第 1 步解决：

- `verify` 与 `generate` 竞态。
- 中文输出策略。
- 多轮 conversation thread。
- SSE agent 协议重构。
- semantic catalog 增强。
- 图文教程和跳转高亮。
- ZIP 导出。
- Worker TypeScript + Zod。
- Cloudflare Agents SDK、D1、R2、用户系统。
