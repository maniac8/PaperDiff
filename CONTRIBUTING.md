# Contributing to 对稿 · PaperDiff

感谢你对 **对稿 · PaperDiff** 的关注与贡献！本项目致力于打造 100% 本地优先、开源许可洁净、零错排且可无损写回的学术文稿阅读与比对工作台。在提交 Issue 或 Pull Request 前，请先阅读以下协作与工程规范。

---

## 1. 分支模型与提 PR 流程（`main` + `dev`）

本项目采用受保护的 **`main` + `dev` 双分支协作模型**，确保默认分支 `main` 始终对应已验证的稳定发布版本。

| 分支 | 角色定位 | 保护与合并规则 |
| :--- | :--- | :--- |
| `main` | 稳定发布线（仅存放 `vX.Y.Z` 正式版） | 受保护：禁止直接 push / force-push / 删除；仅接受 **`dev → main` Release PR** 与紧急 `hotfix/*` |
| `dev` | 日常集成分支（所有社区 PR 与 Dependabot 的目标分支） | 受保护：禁止 force-push / 删除；所有常规功能与修复 PR 均以 `dev` 为目标分支 |
| `feat/*`, `fix/*`, `docs/*` | 短期主题分支，从 `dev` 切出 | PR 合入 `dev` 后自动删除（推荐 **Squash and merge**） |
| `hotfix/*` | 线上紧急补丁，从 `main` 切出 | PR 合入 `main` 发补丁版后，同步合回 `dev` |

### 外部贡献者提 PR 步骤

1. Fork 本仓库并同步 `dev` 分支，切出语义化主题分支：
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b fix/your-topic   # 或 feat/your-feature, docs/your-doc
   ```
2. 完成修改后，在本地运行完整检查（见第 4 节）。
3. 提交 Pull Request 时，将目标分支（base branch）设为 **`dev`**，并按模板填写改动说明与自检清单。CI（`.github/workflows/ci.yml`）会自动运行前端单元测试、TypeScript 构建与后端 `pytest` 回归套件。

### 维护者发版流程（Release Flow）

1. 在 `dev` 上同步更新 6 处版本号（`paperdiff/backend/runtime_state.py`、`paperdiff/frontend/package.json`、`paperdiff/packaging/build_macos_dmg.py`、`paperdiff/packaging/PaperDiff.spec`、`paperdiff/packaging/build_windows_release.py`、`paperdiff/packaging/PaperDiff.iss`）与 [CHANGELOG.md](./CHANGELOG.md) 中的 `## [X.Y.Z] - YYYY-MM-DD` 段落，跑完本地全量测试后提交。
2. 发起 Release PR：`dev` → `main`，等待全部 CI 检查通过。
3. 使用 **Create a merge commit** 合并 `dev` → `main`（**避免在 `dev` → `main` 使用 Squash**，以保持双分支历史对齐）。
4. 拉取合并后的 `main`，打并推送语义化 tag：
   ```bash
   git checkout main && git pull origin main
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   推送 `vX.Y.Z` 会自动触发 `.github/workflows/release.yml`：校验 tag 位于 `main`、校验六处双端版本号一致、并行在 `macos-latest` 与 `windows-latest` 上运行全量测试并构建验证 macOS `.dmg` 与 Windows `Setup.exe` / `Portable.zip`、汇总生成统一 `SHA256SUMS.txt`、自动提取 `CHANGELOG.md` 说明并原子发布 GitHub Release（也可通过 **Actions → Release → Run workflow** 先产出预发布测试包供真机验证）。
5. 将 `main` 同步回 `dev` 以防下一周期冲突：
   ```bash
   git checkout dev && git merge main && git push origin dev
   ```

---

## 2. 本地开发环境搭建

### 环境要求
- **Python**: `3.11+`（macOS 独立打包推荐使用 `Python 3.12`）
- **Node.js**: `20+`（含 `npm`）
- **操作系统**: macOS Apple Silicon / Intel、Windows 10/11 (x64) 原生桌面端，以及 Linux 跨平台 Web 模式

### 安装与运行
```bash
# 1. 安装后端运行时与测试依赖
pip install -r paperdiff/requirements-dev.txt

# 2. 安装前端依赖并构建静态资源
cd paperdiff/frontend
npm ci && npm run build
cd ../..

# 3. 启动本地桌面窗口（macOS WKWebView / Windows Edge WebView2 原生模式）
python3 paperdiff/desktop_app.py

# 或启动跨平台 Web 后台模式（默认 http://127.0.0.1:8765）
python3 paperdiff/launch_desktop.py --daemon
```

---

## 3. 代码注释与文档字符串规范

为了保证多人协作与开源社区可维护性，所有新增或修改的模块应遵循统一的代码文档规范：

### 3.1 Python（Google-Style Docstrings + 架构不变量说明）
- **模块顶部**：包含模块级三引号文档字符串，清晰说明模块在系统流水线中的职责、输入输出契约及关键不变量（例如“零丢字”“逆序切片避免偏移漂移”“路径沙箱防越界”）。
- **公共类与函数**：附完整类型注解（`from __future__ import annotations`）和 Google 风格 docstring，列出 `Args:`、`Returns:`、`Raises:`。
- **关键算法内联注释**：针对非直观的边界处理（如 OOXML `mc:Choice` 去重、LaTeX 括号平衡、Unicode 字符保护、CSS 裁剪边界）写明 **Why（为何这样做）**。

### 3.2 TypeScript / React（JSDoc + 性能与主题护栏说明）
- **文件头部**：使用 `/** @file ... */` 说明组件/模块的职责、性能护栏（如 `React.memo`、直接 DOM `rAF`、Portal 脱离 `contain: paint`）及三态主题约束。
- **导出的类型、接口、API 方法与工具函数**：编写简洁的 JSDoc 注释（`/** ... */`）。

---

## 4. 提交 PR 前的强制核查清单

在提交代码之前，请确保满足以下全部要求：

1. **开源许可证红线**：新增任何 Python / npm 依赖仅限 **MIT / BSD / Apache-2.0 / ISC / PSF**，严禁引入 GPL / AGPL 依赖或重型运行时（如 `numpy`、`pandas`、Playwright 浏览器内核）。
2. **零外部网络与隐私红线**：不得引入任何强制外网 CDN、埋点遥测或云端模型调用；确保离线断网状态下阅读、KaTeX、Mermaid 与 PDF 导出 100% 可用。
3. **全量测试通过**：
   ```bash
   # 后端与真实 Chrome CDP 端到端全量回归（76 项）
   cd paperdiff && python3 -m pytest -W ignore -v --ignore=tests/test_performance_benchmark.py

   # 前端纯函数单元测试（14 项）与严格 TypeScript 构建
   cd paperdiff/frontend
   node --experimental-strip-types --test src/utils/*.test.mjs
   npm run build
   ```
4. **三态主题一致性**：任何新增 UI 组件必须在 `浅色 / 护眼暖纸 / 深色炭灰` 三套主题下对比度达标，禁止硬编码未适配的纯白或低对比度色值。
5. **敏感数据零泄露**：严禁提交 `paperdiff/data/`、真实个人论文样本、内部需求编号或带本地绝对路径（如 `/Users/...`）的测试/文档链接。

---

## 5. Commit Message 约定

推荐使用 [Conventional Commits](https://www.conventionalcommits.org/) 风格：
- `feat(parser): support amsthm theorem environments in latex_parser`
- `fix(ui): render CiteChip hover popover via React Portal to avoid paint clipping`
- `perf(reader): eliminate scroll-triggered React re-renders with rAF scaleX`
- `docs(readme): add English README and main/dev PR contribution workflow`
- `test(stress): add Word mc:Choice textbox deduplication regression test`
