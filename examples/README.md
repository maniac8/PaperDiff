# 官方演示案例（Official Examples）

本目录提供 4 套可直接用于体验与演示 **对稿 · PaperDiff** 的完整论文案例，覆盖日常学术写作最常见的 4 种稿件形态。所有案例均为虚构的 AI 顶会论文场景（长上下文 Transformer 推理与自适应 KV-Cache 稀疏路由），引文选用经典公开 AI 论文，无任何真实业务数据或个人信息。

## 案例一览

| 目录 | 稿件格式 | 包含文件 | 适合体验的功能 |
| :--- | :--- | :--- | :--- |
| `01_markdown_paper/` | Markdown（`.md`） | `v1_初稿.md`、`v2_修订稿.md`、`figures/architecture.svg` | 中文首行缩进、多级列表、嵌套引用块、Mermaid 流程图、KaTeX 公式、相对路径插图与表格数值/最优值加粗差值 |
| `02_word_manuscript/` | Word（`.docx`） | `v1_论文初稿.docx`、`v2_修改稿.docx`、`v2_审阅修订版.docx` | Word 原版视图切换、嵌入高清图表、OMML 原生公式、表格比对，以及带修订痕迹的 `.docx` 一键拆分两版对比 |
| `03_latex_single/` | 单文件 LaTeX（`.tex`） | `v1_manuscript.tex`、`v2_manuscript.tex`、`refs.bib`、`figures/scaling_curve.png` | 自定义宏（`\newcommand`）、`siunitx`、定理框、算法伪代码、`booktabs` 表格、`\ref`/`\cite` 联动与图表引用 |
| `04_latex_overleaf_zip/` | Overleaf 多文件包（`.zip`） | `paper_overleaf_v1.zip`、`paper_overleaf_v2.zip` | 自动识别 `main.tex`、展开 `\input{sections/...}` 子章节、加载同包 `refs.bib` 与 `figures/`，并跨版本整包比对 |

## 快速体验方式

### 方式 A：绑定本目录（推荐，免上传）

1. 启动 PaperDiff，在首页点击 **「新建项目」** → **「绑定本地目录」**，选择本 `examples` 文件夹。
2. 在左侧文件树中直接点击任意 `.md` / `.docx` / `.tex` / `.zip` 文件阅读排版效果。
3. 在文件树中勾选同一案例下的 `v1` 与 `v2` 两份文件，点击 **「对比已选」** 即可查看左右对照与数值变化提醒。
4. 打开 `02_word_manuscript/v2_审阅修订版.docx`，可直接体验「原生修订痕迹一键拆分对比」。

### 方式 B：终端一键直达

```bash
paperdiff ./examples
# 或使用跨平台启动器
python3 paperdiff/launch_desktop.py ./examples --daemon
```

## 预设变动看点

每套案例的 `v1 → v2` 都内置了一组一致的典型修稿改动：

- **关键数值变动**：主指标相对误差由 `14.2%` 修订为 `12.6%`，KV 显存节省由 `68.4%` 调整为 `73.1%`，统计 `p` 值由 `0.018` 调整为 `0.009`；
- **表格与最优值联动**：实验对比表中修改了多组定量数据与最优值加粗标注，方便核查表格差值与加粗转移；
- **文字与公式微调**：包含去冗余改写、正则项符号微调与实验基准数量更新（12 项 → 16 项）。
