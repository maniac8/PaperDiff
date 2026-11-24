# 对稿 · PaperDiff — 全格式压力测试、性能基准与验收门禁指南（v0.1.0）

本测试规范面向 **v0.1.0 正式发布版**，覆盖 **59 项后端与真实 Headless Chrome CDP 端到端测试** + **14 项前端纯函数单元测试**（涵盖 20 类学术格式压力样本、原格式无损回写与离线 PDF、阅读排版与缩进校准、本地文件夹沙箱与严格两两比对、跨平台静默启动与 CLI 路径直达，以及 60 FPS 大论文压测），确保每次提交均保持零错排、零丢字、零卡顿、零回写损坏。

---

## 一、自动化测试套件总览（59 pytest + 14 前端单测）

| 测试文件 | 用例数 | 覆盖维度 | 状态 |
| :--- | :---: | :--- | :---: |
| [`paperdiff/tests/test_core_pipeline.py`](../paperdiff/tests/test_core_pipeline.py) | 11 | 核心 `01–06` 样本回归、Unicode 零丢字、LaTeX 学位论文净化、Word 中文大纲与 OMML | **11 / 11 PASS** |
| [`paperdiff/tests/test_parsers_stress.py`](../paperdiff/tests/test_parsers_stress.py) | 6 | 20 类学术格式压力矩阵（M1–M6、L1–L8、W1–W6） | **6 / 6 PASS** |
| [`paperdiff/tests/test_patcher_roundtrip.py`](../paperdiff/tests/test_patcher_roundtrip.py) | 3 | E1 LaTeX 外科表单元格写回、E2 Overleaf `.zip` 重打包、E3 Word 原模板干净版与红线版写回 | **3 / 3 PASS** |
| [`paperdiff/tests/test_pdf_export.py`](../paperdiff/tests/test_pdf_export.py) | 1 | E4 100% 离线自包含打印 HTML（零外链、内联 KaTeX）与矢量 PDF 生成 | **1 / 1 PASS** |
| [`paperdiff/tests/test_performance_benchmark.py`](../paperdiff/tests/test_performance_benchmark.py) | 2 | 后端 10k/50k 级压测 + 真实 Headless Chrome CDP 滚动/窗口拖拽性能基准 | **2 / 2 PASS** |
| [`paperdiff/tests/test_w1_reading_typography.py`](../paperdiff/tests/test_w1_reading_typography.py) | 10 | 跨格式首行/悬挂缩进提取、学术排版预设、洁净复制、三态主题对比度与单稿 PDF 排版 | **10 / 10 PASS** |
| [`paperdiff/tests/test_w2_local_workspace.py`](../paperdiff/tests/test_w2_local_workspace.py) | 11 | 本地目录安全沙箱、零上传直读、严格两两对比、外部修改检测、草稿冲突与备份写盘 | **11 / 11 PASS** |
| [`paperdiff/tests/test_w1_startup_core.py`](../paperdiff/tests/test_w1_startup_core.py) | 9 | 跨平台单实例锁、懒加载冷启动、静默 Web 启停脚本、PWA 与防 CSRF 优雅停机 | **9 / 9 PASS** |
| [`paperdiff/tests/test_w2_resume_and_cli.py`](../paperdiff/tests/test_w2_resume_and_cli.py) | 6 | 窗口尺寸与多屏钳制记忆、上次工作区快捷恢复、CLI 路径直达与一键安装命令行工具 | **6 / 6 PASS** |
| `paperdiff/frontend/src/utils/*.test.mjs` | 14 | 前端纯函数单测（本地目录树、排版预设、运行态辅助与工作区恢复） | **14 / 14 PASS** |

---

## 二、核心回归样本集（`test_cases/01–06`）

| 编号 | 测试样本目录 | 核心验收重点 |
| :---: | :--- | :--- |
| **01** | `01_en_latex_nature_revision/` | 英文顶刊 LaTeX 3 版本演进：6 类 AI 埋点陷阱全抓（数值/引文/交叉引用/公式/术语/断言强度）、段落移动互跳、Cherry-Pick 回退与无损回写 |
| **02** | `02_en_latex_overleaf_zip/` | Overleaf 多文件 `.zip`：递归 `\input` 展开、PNG 插图 SHA-256 更新状态、`.bib` 悬停卡片与未定义引文告警、`\multicolumn` + 加粗最优值变动 (`+B/-B`) + 数值 `Δ/%` |
| **03** | `03_zh_latex_thesis/` | 中文 `ctexart` LaTeX：`jieba` 双语分词、中文 AI 套话词消除统计、中英混排标点与百分比变动 |
| **04** | `04_en_word_manuscript/` | 英文 Word 稿件：内嵌插图与图注绑定、合并单元格表格与数值 `Δ/%`、多引文 `[12, 14]` 拆分、原生 `<w:ins>/<w:del>` Track Changes 导出 |
| **05** | `05_zh_word_report/` | 中文 Word 基金申报书：中文章节标题、图注、数值变动与表格引用丢失 |
| **06** | `06_edge_cases_stress_tex/` | LaTeX 边界压力测试：80 列折行与 `%` 注释 100% 免疫、嵌套格式宏与链接、`align*` 符号级公式 Diff |

---

## 三、v0.1.0 20 类全格式「零错排」压力测试矩阵

### A. Markdown 压力样本（M1–M6）
1. **M1 · 科研长文与复杂公式手册**：10k+ 词长文、12+ 组 `$$...$$` 行间公式（含 `\begin{cases}` 与列表内嵌公式）、1,000+ 行内 KaTeX、粗体公式、12+ 张复杂表格，0 原始 `$$` 泄漏且保留精确行号锚点。
2. **M2 · 多级深度嵌套列表与混合块**：3 级缩进无序/有序混排、紧跟正文无空行列表、列表内嵌围栏代码块与引用块。
3. **M3 · Unicode 与特殊符号保真**：下划线标识符（`sparse_attn`、`kv_cache_v2`）、拉丁变音字符（`Debye–Hückel`、`Rémond`、`Ångström`）、希腊单位（`10 μm`、`4°C`）、原始标点零多余空格。
4. **M4 · GFM 扩展与学术增强**：任务列表 `- [x]`、删除线 `~~text~~`、脚注 `[^1]` 富文本定义与双向跳转、GitHub Callout（`> [!NOTE] / [!WARNING]`）、YAML Frontmatter 顶部折叠卡。
5. **M5 · 代码高亮与离线 Mermaid 图表**：Python / R / LaTeX / Bash 代码块离线 `highlight.js` 语法高亮 + ` ```mermaid ` 矢量流程图。
6. **M6 · 复杂 Markdown 表格**：左/中/右列对齐、单元格 `<br>` 换行、整格加粗 `**0.18**` 与单元格内公式/代码/链接。

### B. LaTeX 压力样本（L1–L8）
7. **L1 · 中文/双语高校学位论文封面与页眉宏**：`\begin{spacing}`、`\ThisCenterWallPaper`、`\begin{CJK*}`、`\chinesechaptersize`、`\noalign{}`、`\qquad`、`\fancypagestyle`、`\TOCadd`、`\addcontentsline`、`{\bf \Large ... \par}` — 0 源码泄漏、封面表归入前置折叠卡。
8. **L2 · 多章节 `\part / \chapter / \section` 层级树**：自适应大纲缩进与滚动高亮。
9. **L3 · 导言区自定义宏**：`\newcommand` / `\DeclareMathOperator` 自动提取注入 KaTeX `macros` + 0 参正文宏展开。
10. **L4 · 化学式与物理单位宏包**：`mhchem`（`\ce{CaCO3 + H2O}`）与 `siunitx`（`\SI{42.5}{\um}` 直立 `µm`、`\qty{25}{\celsius}`、`\num{5.62e-6}`）。
11. **L5 · 定理证明与伪代码算法环境**：`theorem / lemma / proposition / proof` 编号框 + `algorithm / algorithmic` 缩进伪代码（规范小写 `end if` / `end for`）。
12. **L6 · 多子图与交叉引用跳转**：`\begin{subfigure}` / `\subcaptionbox` 多图并排（正确绑定外层图 `\label`）+ 无重复 `\ref / \eqref / \autoref` 跳转。
13. **L7 · 复杂学术三线表**：`threeparttable`（含 `tablenotes`）、`\makecell`、双向嵌套 `\multicolumn/\multirow`、精确单元格偏移 `cell_spans`。
14. **L8 · 参考文献全路径渲染**：`thebibliography` / `.bbl` / `.bib` 悬挂缩进文献列表 + GB/T 7714 / Nature / IEEE / APA 四标准切换。

### C. Word (`.docx`) 压力样本（W1–W6）
15. **W1 · 中文硕博学位论文全套结构**：封面页 + 封面键值表 + 原创性声明 + 自动目录（`w:sdt` / `TOC`）→ 自动收敛于前置折叠卡，正文左侧完整输出中文目录树。
16. **W2 · `numbering.xml` 自动多级编号还原**：`第1章 / 1.1 / 1.1.1` 与中文括号编号完整还原。
17. **W3 · 真实科学 OMML 数学公式**：行内 `<m:oMath>`、行间 `<m:oMathPara>`（分式/根号/上下标/积分求和/矩阵）+ MathType OLE 图像回退。
18. **W4 · 脚注、尾注与文本框**：`footnotes.xml` / `endnotes.xml` 角标悬停跳转 + `w:txbxContent`（`mc:Choice` 去重读取，零双倍文字）。
19. **W5 · 导师批注与原生 Track Changes 一键拆版**：`comments.xml` 批注气泡；含 `<w:ins>/<w:del>` 的单份修订 `.docx` 一键拆为 `修订前 v1 vs 修订后 v2`。
20. **W6 · Word 原版排版副视图（`docx-preview`）**：原始 `.docx` 二进制归档与「学术精读 ⇄ Word 原版」一键切换。

---

## 四、编辑回写与离线 PDF 硬门禁（E1–E4）

| 验收项 | 验证目标 | 自动化测试结果 |
| :--- | :--- | :---: |
| **E1 · LaTeX 外科级单元格与公式回写** | 仅替换目标单元格内层文本与 `\textbf`，导言区、`\toprule/\cmidrule`、`%` 注释 0 漂移 | **PASS** |
| **E2 · Overleaf `.zip` 多文件重打包** | 通过 `source_map` 仅覆写改动的子 `.tex`，未改文件与图片字节级一致 | **PASS** |
| **E3 · Word 原模板 XML 原位回写** | 原封不动保留原 `.docx` 封面/页眉页脚/边框，支持干净版与 `<w:ins>/<w:del>` 红线修订版 | **PASS** |
| **E4 · 100% 离线出版级 HTML & PDF 导出** | 零外网 CDN 链接、内联 KaTeX 与中文综述、生成合法多页 `%PDF-` 矢量文件 | **PASS** |

---

## 五、实测性能基准（v0.1.0 实跑记录）

在 Apple Silicon macOS 上执行 `test_performance_benchmark.py`（包含真实 Headless Chrome CDP 驱动已编译生产版前端 SPA）：

| 性能指标 | 负载条件 | 实测结果 | 门禁要求 |
| :--- | :--- | :---: | :---: |
| 10.6k 词文档冷解析 / LRU 热缓存 | 42.4 KB / 258 块 / 1,000+ 公式 | **120.0 ms / 7.79 ms** | `< 400 ms / < 50 ms` |
| 离线自包含打印 HTML 生成 | 794.4 KB 含内联 KaTeX | **1.8 ms** | `< 200 ms` |
| 34.4k 词压力论文冷解析 / 表格写回 | 317.6 KB / 443 块 | **382.3 ms / 0.6 ms** | `< 1,500 ms / < 50 ms` |
| Chrome 单稿滚动帧耗时（P50 / P95） | **441 块 / 2,750 KaTeX 公式 / 56,986 px 高** | **16.65 ms / 17.35 ms (60.0 FPS)** | `P50 < 25 ms` |
| Chrome 16 步宽幅拖拽缩放（P50 / P95） | `1520px → 840px → 1480px` 过断点 | **80.26 ms / 101.49 ms** | `P50 < 150 ms` |
| Chrome 双栏对比滚动（P50 / P95） | 441 块左右双栏 Diff | **19.75 ms / 36.40 ms (50.6 FPS)** | `P50 < 30 ms` |

---

## 六、自动化执行命令

```bash
# 运行全部 59 项后端与真实 Chrome CDP 端到端测试
cd paperdiff && python3 -m pytest -W ignore -v

# 单独运行性能压测并打印 JSON 基准报告
cd paperdiff && python3 -m pytest tests/test_performance_benchmark.py -v -s

# 前端 14 项纯函数单元测试与生产构建
cd paperdiff/frontend
node --experimental-strip-types --test src/utils/*.test.mjs
npm run build
```
