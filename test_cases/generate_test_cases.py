#!/usr/bin/env python3
"""Generate a comprehensive LaTeX (.tex, .zip) and Word (.docx) test suite for PaperDiff Studio."""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from pathlib import Path
from docx import Document
from docx.shared import Inches

OUT_DIR = Path(__file__).resolve().parent


def make_chart_png(bar_heights: list[float], accent_rgb: tuple[int, int, int] = (37, 99, 235)) -> bytes:
    """Generate a clean crisp academic bar-chart PNG in pure stdlib Python (zero deps)."""
    w, h = 520, 260
    bg = (255, 255, 255)
    grid = (226, 232, 240)
    axis = (51, 65, 85)
    muted = (148, 163, 184)
    buf = bytearray(bg * (w * h))

    def set_px(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if 0 <= x < w and 0 <= y < h:
            idx = (y * w + x) * 3
            buf[idx : idx + 3] = bytes(rgb)

    def fill_rect(x0: int, y0: int, x1: int, y1: int, rgb: tuple[int, int, int]) -> None:
        for yy in range(max(0, y0), min(h, y1)):
            row_start = (yy * w + max(0, x0)) * 3
            row_end = (yy * w + min(w, x1)) * 3
            span = (row_end - row_start) // 3
            if span > 0:
                buf[row_start:row_end] = bytes(rgb) * span

    # Plot frame margins
    left, right, top, bottom = 54, w - 28, 28, h - 38
    # Horizontal gridlines
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy = int(bottom - frac * (bottom - top))
        for gx in range(left, right, 4):
            fill_rect(gx, gy, gx + 2, gy + 1, grid)

    # Axes (left & bottom spines only — clean publication style)
    fill_rect(left, top, left + 2, bottom + 2, axis)
    fill_rect(left, bottom, right, bottom + 2, axis)

    # Bars
    n = max(1, len(bar_heights))
    slot = (right - left - 30) // n
    bar_w = max(24, int(slot * 0.52))
    for i, val in enumerate(bar_heights):
        bh = int(max(0.05, min(1.0, val)) * (bottom - top - 8))
        bx0 = left + 22 + i * slot
        color = accent_rgb if i == n - 1 else muted
        fill_rect(bx0, bottom - bh, bx0 + bar_w, bottom, color)
        # Crisp top cap highlight
        fill_rect(bx0, bottom - bh, bx0 + bar_w, bottom - bh + 3, axis)

    # Encode PNG
    raw_scanlines = bytearray()
    stride = w * 3
    for y in range(h):
        raw_scanlines.append(0)
        raw_scanlines.extend(buf[y * stride : (y + 1) * stride])

    def _chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw_scanlines), 6))
        + _chunk(b"IEND", b"")
    )


def write_zip_mixed(rel: str, files: dict[str, str | bytes]) -> None:
    p = OUT_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            if isinstance(content, bytes):
                zf.writestr(name, content)
            else:
                zf.writestr(name, content.strip() + "\n")


def write_text(rel: str, content: str) -> None:
    p = OUT_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding="utf-8")


def write_zip(rel: str, files: dict[str, str]) -> None:
    p = OUT_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.strip() + "\n")


def write_docx(rel: str, blocks: list[tuple[str, object]]) -> None:
    """blocks: list of (kind, payload) where kind in {'title','h1','h2','h3','caption','p','table','image'}."""
    p = OUT_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for kind, payload in blocks:
        if kind == "image" and isinstance(payload, bytes):
            doc.add_picture(io.BytesIO(payload), width=Inches(4.6))
            continue
        if kind == "table" and isinstance(payload, list):
            rows = payload
            tbl = doc.add_table(rows=len(rows), cols=len(rows[0]))
            tbl.style = "Table Grid"
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    cell_p = tbl.cell(r_idx, c_idx).paragraphs[0]
                    if isinstance(val, tuple):
                        txt, is_bold = val
                        run = cell_p.add_run(str(txt))
                        run.bold = bool(is_bold)
                    else:
                        cell_p.text = str(val)
            # Merge top-left 2 columns on header row if marked with '__MERGE_LEFT__'
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    if val == "__MERGE_LEFT__" and c_idx > 0:
                        tbl.cell(r_idx, c_idx).text = ""
                        tbl.cell(r_idx, c_idx - 1).merge(tbl.cell(r_idx, c_idx))
            continue
        text = str(payload)
        if kind == "title":
            doc.add_heading(text, level=0)
        elif kind == "h1":
            doc.add_heading(text, level=1)
        elif kind == "h2":
            doc.add_heading(text, level=2)
        elif kind == "h3":
            doc.add_heading(text, level=3)
        elif kind == "caption":
            para = doc.add_paragraph(text)
            try:
                para.style = "Caption"
            except Exception:
                pass
        else:
            doc.add_paragraph(text)
    doc.save(str(p))


# ==============================================================================
# 01. English Full LaTeX Paper (v1 AI Draft -> v2 AI Polish w/ Traps -> v3 Final)
# ==============================================================================
CASE1_V1 = r"""\documentclass[11pt]{article}
\usepackage{amsmath,graphicx}
\title{Entropy-Guided Adaptive Token-Budget Routing for Long-Context Transformers}

\begin{document}
\maketitle

\begin{abstract}
Understanding how attention mass concentrates across ultra-long sequences is of paramount importance for scaling modern Transformer inference. However, existing KV-Cache eviction paradigms exhibit fundamental limitations because fixed-window pruning fails to retain transient long-range retrieval anchors. In this study, we delve into an entropy-guided adaptive routing (AdaptRoute) framework that leverages layer-wise attention priors to guide dynamic block selection. Across a benchmark of 88 reasoning tasks ($n = 88$, 128K context), our framework reduces perplexity gap (PPL) from 0.412 to 0.286 nats ($p < 0.001$), offering a comprehensive and auditable blueprint for memory-constrained LLM serving.
\end{abstract}

\section{Introduction}
\label{sec:intro}

Transformer attention weights span orders of magnitude across early syntactic layers and deep retrieval heads~\cite{vaswani2017neurips,dao2022neurips}. Moreover, tight GPU memory budgets make exhaustive KV-Cache retention infeasible in real-world deployments. Traditional eviction protocols rely on uniform or sliding token windows, meaning a large fraction of memory budget is spent on low-entropy filler tokens while missing long-range reasoning anchors, as illustrated in Fig.~\ref{fig:profile_overview}.

Furthermore, purely heuristic pruning methods struggle under tight cache budgets ($N \le 8$ blocks per head) because they lack prior knowledge of head specialization and chain-of-thought dependency spans~\cite{wei2022neurips}. Notably, coupling a reduced-order entropy prior with sequential expected information gain (EIG) selection may suggest a practical path toward higher accuracy without increasing GPU memory.

\section{Methodology}
\label{sec:method}

\subsection{Hierarchical Attention Entropy Prior}
We model block importance $c(z) = \log_{10} C(z)$ over block index $z \in [0, 500]$ as a Gaussian process whose mean function $m_\phi(z)$ is anchored by a layer-wise attention balance:

\begin{equation}
\label{eq:transport}
\frac{\partial}{\partial z}\!\left(w_s(z)\, C(z) - K_z(z)\frac{\partial C(z)}{\partial z}\right) = S_{\text{head}}(z) - \lambda_{\text{decay}} C(z),
\end{equation}

where $w_s(z)$ denotes the positional decay velocity, $K_z(z)$ is cross-block diffusion, and the prior variance satisfies $\sigma_z^2 = 0.64$.

\subsection{Sequential Expected Information Gain}
At each decode step $t$, the AdaptRoute policy selects the next key--value block $z_t^\star$ by maximizing the mutual information between the block logit $y_t$ and the full attention output $\mathbf{c}$:

\begin{equation}
\label{eq:eig}
z_t^\star = \arg\max_{z \in \mathcal{Z}} \; \mathbb{E}_{p(y \mid z, \mathcal{D}_{t-1})}\!\left[ D_{\text{KL}}\!\left(p(\mathbf{c} \mid \mathcal{D}_{t-1}, z, y) \,\|\, p(\mathbf{c} \mid \mathcal{D}_{t-1})\right) \right].
\end{equation}

This paragraph describes our operational GPU memory cost model: each deep layer above 200 blocks incurs a bandwidth penalty proportional to cache depth, $\eta_{\text{cost}}(z) = 1 + 0.36 (z / 500)$, ensuring that distant blocks are queried only when expected distortion reduction outweighs latency cost.

\section{Experiments and Results}
\label{sec:results}

We evaluate AdaptRoute against uniform pruning, sliding-window eviction, and unconstrained top-k caching across 88 benchmark tasks summarized in Table~\ref{tab:ablation}. Under an 8-block budget, AdaptRoute achieves a PPL gap of 0.286 compared to 0.412 for uniform eviction (a 30.6\% reduction, $p < 0.001$) and improves long-range needle retrieval accuracy from 61.5\% to 84.2\%.

\begin{figure}[t]
\caption{Comparison of long-context reasoning accuracy under an 8-block KV-Cache budget across uniform, sliding-window, and entropy-guided AdaptRoute policies.}
\label{fig:profile_overview}
\end{figure}

\begin{table}[t]
\caption{Quantitative ablation of entropy prior, cost weighting, and block budget across $n = 88$ tasks.}
\label{tab:ablation}
\begin{tabular}{lccc}
\toprule
Strategy & Block Budget & PPL Gap & Retrieval Acc. (\%) \\
\midrule
Uniform & 8 & 0.412 & 61.5 \\
Sliding Window & 8 & 0.368 & 68.4 \\
AdaptRoute (Ours) & 8 & \textbf{0.286} & \textbf{84.2} \\
\bottomrule
\end{tabular}
\end{table}

\section{Discussion}
\label{sec:discussion}

Our results indicate that embedding layer-wise entropy structure into sequential block routing substantially narrows output distortion at 128K sequence lengths. Under the stated single-host serving assumptions, the method provides calibrated latency budgets suitable for practical LLM deployment.

\end{document}
"""

# V2 deliberately includes realistic AI-polish improvements PLUS subtle traps for testing guardrails!
CASE1_V2_TRAPS = r"""\documentclass[11pt]{article}
\usepackage{amsmath,graphicx}
\title{Entropy-Guided Adaptive Token-Budget Routing for Long-Context Transformers}

\begin{document}
\maketitle

\begin{abstract}
Measuring how attention mass varies across long sequences is essential for scaling modern Transformer inference. Standard KV eviction uses fixed windows that often drop narrow retrieval anchors. We present an entropy-guided adaptive routing algorithm that uses attention priors to select token blocks sequentially. Across 86 reasoning tasks ($n = 86$, 128K context), our method cuts perplexity gap from 0.421 to 0.286 nats ($p < 0.05$), giving systems engineers a clear plan under tight GPU memory limits.
\end{abstract}

\section{Introduction}
\label{sec:intro}

Transformer attention weights vary by several orders of magnitude from early layers to deep retrieval heads~\cite{dao2022neurips,fake2026neurips}. Limited GPU memory prevents dense KV retention during long-context inference. Fixed uniform or sliding windows waste memory on flat filler tokens and miss sharp retrieval peaks, as shown in Fig.~\ref{fig:profile_overview}.

Purely heuristic pruning also struggles when only a few blocks ($N \le 8$ per head) can be kept, because it ignores head specialization and chain-of-thought spans~\cite{wei2022neurips}. Coupling a simple entropy prior with sequential expected information gain (EIG) selection conclusively proves higher accuracy without extra GPU memory.

\section{Methodology}
\label{sec:method}

\subsection{Hierarchical Attention Entropy Prior}
We model block importance $c(z) = \log_{10} C(z)$ over block index $z \in [0, 500]$ as a Gaussian process anchored by a layer-wise attention balance:

\begin{equation}
\label{eq:transport}
\frac{\partial}{\partial z}\!\left(w_s(z)\, C(z) - K_z(z)\frac{\partial C(z)}{\partial z}\right) = S_{\text{head}}(z) - \lambda_{\text{decay}} C(z),
\end{equation}

where $w_s(z)$ is positional decay velocity, $K_z(z)$ is cross-block diffusion, and the prior scale satisfies $\sigma_z = 0.64$.

\subsection{Sequential Expected Information Gain}
At each decode step $t$, the policy picks the next block $z_t^\star$ by maximizing the mutual information between the block logit $y_t$ and the full attention output $\mathbf{c}$:

\begin{equation}
\label{eq:eig}
z_t^\star = \arg\max_{z \in \mathcal{Z}} \; \mathbb{E}_{p(y \mid z, \mathcal{D}_{t-1})}\!\left[ D_{\text{KL}}\!\left(p(\mathbf{c} \mid \mathcal{D}_{t-1}, z, y) \,\|\, p(\mathbf{c} \mid \mathcal{D}_{t-1})\right) \right].
\end{equation}

\section{Experiments and Results}
\label{sec:results}

We compare our approach against uniform pruning, sliding-window eviction, and unconstrained top-k caching across 88 benchmark tasks. Under an 8-block budget, our method achieves a perplexity gap of 0.286 compared to 0.412 for uniform eviction (a 30.6\% reduction, $p < 0.001$) and raises needle retrieval accuracy from 61.5\% to 84.2\%.

\begin{figure}[t]
\caption{Long-context reasoning accuracy under an 8-block budget comparing uniform, sliding-window, and entropy-guided adaptive strategies.}
\label{fig:profile_overview}
\end{figure}

\begin{table}[t]
\caption{Ablation of entropy prior, cost weighting, and block budget across $n = 88$ tasks.}
\label{tab:ablation}
\begin{tabular}{lccc}
\toprule
Strategy & Block Budget & PPL Gap & Retrieval Acc. (\%) \\
\midrule
Uniform & 8 & 0.412 & 61.5 \\
Sliding Window & 8 & 0.368 & 68.4 \\
Adaptive (Ours) & 8 & \textbf{0.291} & \textbf{84.2} \\
\bottomrule
\end{tabular}
\end{table}

\section{Discussion}
\label{sec:discussion}

This paragraph describes our operational GPU memory cost model: each deep layer above 200 blocks incurs a bandwidth penalty proportional to cache depth, $\eta_{\text{cost}}(z) = 1 + 0.36 (z / 500)$, ensuring that distant blocks are queried only when expected distortion reduction outweighs latency cost.

Our results show that adding attention entropy priors into sequential routing narrows output distortion at 128K sequence lengths. Under the stated single-host serving assumptions, the approach produces calibrated latency budgets for practical LLM deployment.

We further note a practical limitation: cross-node tensor-parallel KV sharding is not explicitly modeled by the single-host prior, and extending the framework to multi-node disaggregated serving remains an important avenue for future systems work.

\end{document}
"""

CASE1_V3_FIXED = r"""\documentclass[11pt]{article}
\usepackage{amsmath,graphicx}
\title{Entropy-Guided Adaptive Token-Budget Routing for Long-Context Transformers}

\begin{document}
\maketitle

\begin{abstract}
Measuring how attention mass varies across long sequences is essential for scaling modern Transformer inference. Standard KV-Cache eviction uses fixed windows that often drop narrow retrieval anchors. We present an entropy-guided adaptive routing (AdaptRoute) framework that uses attention priors to select token blocks sequentially. Across 88 reasoning tasks ($n = 88$, 128K context), AdaptRoute cuts PPL gap from 0.412 to 0.286 nats ($p < 0.001$), giving systems engineers a clear plan under tight GPU memory limits.
\end{abstract}

\section{Introduction}
\label{sec:intro}

Transformer attention weights vary by several orders of magnitude from early layers to deep retrieval heads~\cite{vaswani2017neurips,dao2022neurips}. Limited GPU memory prevents dense KV-Cache retention during long-context inference. Fixed uniform or sliding windows waste memory on flat filler tokens and miss sharp retrieval peaks, as shown in Fig.~\ref{fig:profile_overview}.

Purely heuristic pruning also struggles when only a few blocks ($N \le 8$ per head) can be kept, because it ignores head specialization and chain-of-thought spans~\cite{wei2022neurips}. Coupling a simple entropy prior with sequential expected information gain (EIG) selection offers a practical path toward higher accuracy without extra GPU memory.

\section{Methodology}
\label{sec:method}

\subsection{Hierarchical Attention Entropy Prior}
We model block importance $c(z) = \log_{10} C(z)$ over block index $z \in [0, 500]$ as a Gaussian process anchored by a layer-wise attention balance:

\begin{equation}
\label{eq:transport}
\frac{\partial}{\partial z}\!\left(w_s(z)\, C(z) - K_z(z)\frac{\partial C(z)}{\partial z}\right) = S_{\text{head}}(z) - \lambda_{\text{decay}} C(z),
\end{equation}

where $w_s(z)$ is positional decay velocity, $K_z(z)$ is cross-block diffusion, and the prior variance satisfies $\sigma_z^2 = 0.64$.

\subsection{Sequential Expected Information Gain}
At each decode step $t$, the AdaptRoute policy picks the next block $z_t^\star$ by maximizing the mutual information between the block logit $y_t$ and the full attention output $\mathbf{c}$:

\begin{equation}
\label{eq:eig}
z_t^\star = \arg\max_{z \in \mathcal{Z}} \; \mathbb{E}_{p(y \mid z, \mathcal{D}_{t-1})}\!\left[ D_{\text{KL}}\!\left(p(\mathbf{c} \mid \mathcal{D}_{t-1}, z, y) \,\|\, p(\mathbf{c} \mid \mathcal{D}_{t-1})\right) \right].
\end{equation}

\section{Experiments and Results}
\label{sec:results}

We compare AdaptRoute against uniform pruning, sliding-window eviction, and unconstrained top-k caching across 88 benchmark tasks summarized in Table~\ref{tab:ablation}. Under an 8-block budget, AdaptRoute achieves a PPL gap of 0.286 compared to 0.412 for uniform eviction (a 30.6\% reduction, $p < 0.001$) and raises needle retrieval accuracy from 61.5\% to 84.2\%.

\begin{figure}[t]
\caption{Long-context reasoning accuracy under an 8-block KV-Cache budget comparing uniform, sliding-window, and entropy-guided AdaptRoute policies.}
\label{fig:profile_overview}
\end{figure}

\begin{table}[t]
\caption{Ablation of entropy prior, cost weighting, and block budget across $n = 88$ tasks.}
\label{tab:ablation}
\begin{tabular}{lccc}
\toprule
Strategy & Block Budget & PPL Gap & Retrieval Acc. (\%) \\
\midrule
Uniform & 8 & 0.412 & 61.5 \\
Sliding Window & 8 & 0.368 & 68.4 \\
AdaptRoute (Ours) & 8 & \textbf{0.286} & \textbf{84.2} \\
\bottomrule
\end{tabular}
\end{table}

\section{Discussion}
\label{sec:discussion}

This paragraph describes our operational GPU memory cost model: each deep layer above 200 blocks incurs a bandwidth penalty proportional to cache depth, $\eta_{\text{cost}}(z) = 1 + 0.36 (z / 500)$, ensuring that distant blocks are queried only when expected distortion reduction outweighs latency cost.

Our results show that adding attention entropy priors into sequential routing narrows output distortion at 128K sequence lengths. Under the stated single-host serving assumptions, AdaptRoute produces calibrated latency budgets for practical LLM deployment.

We further note a practical limitation: cross-node tensor-parallel KV sharding is not explicitly modeled by the single-host prior, and extending the framework to multi-node disaggregated serving remains an important avenue for future systems work.

\end{document}
"""

# ==============================================================================
# 02. Overleaf Multi-File LaTeX Project ZIPs (v1.zip vs v2.zip)
# ==============================================================================
ZIP_V1 = {
    "main.tex": r"""\documentclass[10pt]{article}
\title{Block-Sparse KV-Cache Compression for Long-Context Transformer Serving}
\begin{document}
\maketitle
\input{sections/abstract}
\input{sections/intro}
\input{sections/results}
\bibliography{references}
\end{document}
""",
    "sections/abstract.tex": r"""\begin{abstract}
Block-sparse attention routing offers a promising paradigm for accelerating long-context Transformer inference. Notably, our serving benchmarks ($n = 36$) demonstrate that dynamic budget pruning lowers decode latency by 64.5\% ($p = 0.002$) while preserving multi-hop reasoning accuracy.
\end{abstract}
""",
    "sections/intro.tex": r"""\section{Introduction}
Memory bandwidth frequently bottlenecks autoregressive Transformer models during 128K decoding~\cite{dao2022neurips}. Conventional full-attention caching approaches are costly and limit concurrent batch size. Leveraging head-level sparsity masks to compact redundant KV blocks provides a holistic and seamless alternative, as illustrated in Fig.~\ref{fig:sparse_mech}.
""",
    "sections/results.tex": r"""\section{Key Findings}
Across three batch regimes ($B \in \{8, 16, 32\}$), block-sparse Transformer kernels retained 89.3\% of long-range retrieval recall compared with 31.2\% in sliding-window baselines (Table~\ref{tab:latency}). Profiling traces confirm that fused tiling reduces per-token decode time to 12.0 ms.

\begin{figure}[t]
\includegraphics[width=\linewidth]{figures/sparse_latency.png}
\caption{Retrieval recall efficiency across sliding-window baseline and block-sparse Transformer kernels.}
\label{fig:sparse_mech}
\end{figure}

\begin{table}[t]
\caption{Summary of recall and significance across batch regimes.}
\label{tab:latency}
\begin{tabular}{lccc}
\toprule
Method & \multicolumn{2}{c}{Serving Metrics} & Significance \\
\midrule
Sliding Window & 31.2\% & 1.8 ms & — \\
BlockSparse-2x & \textbf{89.3\%} & 12.0 ms & $p = 0.002$ \\
\bottomrule
\end{tabular}
\end{table}
""",
    "references.bib": """@inproceedings{dao2022neurips,
  title = {FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness},
  author = {Dao, Tri and Fu, Daniel Y. and Ermon, Stefano and Rudra, Atri and Re, Christopher},
  booktitle = {NeurIPS},
  year = {2022}
}""",
    "figures/sparse_latency.png": make_chart_png([0.31, 0.58, 0.89], (37, 99, 235)),
}

ZIP_V2 = {
    "main.tex": r"""\documentclass[10pt]{article}
\title{Block-Sparse KV-Cache Compression for Long-Context Transformer Serving}
\begin{document}
\maketitle
\input{sections/abstract}
\input{sections/intro}
\input{sections/results}
\bibliography{references}
\end{document}
""",
    "sections/abstract.tex": r"""\begin{abstract}
Block-sparse attention routing can accelerate long-context Transformer inference. In serving tests ($n = 36$), dynamic budget pruning cuts decode latency by 64.5\% ($p = 0.002$) without hurting multi-hop reasoning accuracy.
\end{abstract}
""",
    "sections/intro.tex": r"""\section{Introduction}
Memory bandwidth often bottlenecks autoregressive Transformer models during 128K decoding~\cite{dao2022neurips}. Conventional full-attention caching is expensive and restricts concurrent batch size. Applying head-level sparsity masks to compact redundant KV blocks offers a low-overhead alternative, as shown in Fig.~\ref{fig:sparse_mech}.
""",
    "sections/results.tex": r"""\section{Key Findings}
Across three batch regimes ($B \in \{8, 16, 32\}$), block-sparse Transformer kernels retained 89.3\% of long-range retrieval recall versus 31.2\% in sliding-window baselines (Table~\ref{tab:latency}). Profiling traces show that fused tiling reduces per-token decode time to 10.0 ms.

\begin{figure}[t]
\includegraphics[width=\linewidth]{figures/sparse_latency.png}
\caption{Retrieval recall efficiency across sliding-window baselines and fused block-sparse Transformer kernels.}
\label{fig:sparse_mech}
\end{figure}

\begin{table}[t]
\caption{Summary of recall and statistical significance across batch regimes.}
\label{tab:latency}
\begin{tabular}{lccc}
\toprule
Method & \multicolumn{2}{c}{Serving Metrics} & Significance \\
\midrule
Sliding Window & 31.2\% & 1.8 ms & — \\
BlockSparse-2x & 89.3\% & 10.0 ms & $p = 0.002$ \\
\bottomrule
\end{tabular}
\end{table}
""",
    "references.bib": """@inproceedings{dao2022neurips,
  title = {FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness},
  author = {Dao, Tri and Fu, Daniel Y. and Ermon, Stefano and Rudra, Atri and Re, Christopher},
  booktitle = {NeurIPS},
  year = {2022}
}""",
    "figures/sparse_latency.png": make_chart_png([0.31, 0.64, 0.92], (16, 185, 129)),
}

# ==============================================================================
# 03. Chinese LaTeX Paper (v1.tex vs v2.tex)
# ==============================================================================
ZH_TEX_V1 = r"""\documentclass[UTF8]{ctexart}
\title{基于自适应稀疏路由的长上下文大语言模型推理加速机制研究}
\begin{document}
\maketitle

\begin{abstract}
值得注意的是，长上下文大语言模型在自回归解码阶段面临严重的键值缓存显存膨胀，对高并发推理服务构成至关重要且不容忽视的系统瓶颈。综上所述，本文围绕自适应稀疏路由（AdaptRoute）技术开展多尺度推理基准实验（$n = 48$），全方位探讨注意力熵阈值与分块粒度对长程检索准确率的影响。结果表明，在优化工况下，AdaptRoute 处理可显著提升并发吞吐量 2.35 倍，将单令牌解码延迟降低 68.4\%（$p < 0.01$），为超长上下文大模型部署提供有力支撑。
\end{abstract}

\section{引言}
近年来，大语言模型在长文档理解与代码库级推理任务中的表现受到了广泛关注~\cite{dao2022neurips,vaswani2017neurips}。与此同时，现有全量注意力缓存方案显存开销高昂，且容易造成显存带宽饱和。利用层级注意力熵先验赋能块级键值筛选，能够在算子层面形成紧凑的稀疏索引结构，进而将关键语义令牌完整保留于高速缓存中，其调度机制如图~\ref{fig:route_cn} 所示。

\section{实验设计与分析方法}
本实验选取主流开源 7B 与 70B 架构模型，在 128K 序列长度、BF16 精度条件下开展三组平行推理测试。通过硬件性能计数器表征裁剪前后的显存带宽利用率变化，并定量测定端到端解码延迟 $L_r$（单位：$\text{ms token}^{-1}$）。

\begin{equation}
L_r = E_0 \max\!\left(0,\, \frac{\tau_b - \tau_c}{\tau_c}\right)^{1.5}
\end{equation}

\section{结果与讨论}
如表~\ref{tab:cn_res} 所示，经两阶段自适应预算校准后，128K 场景下的相对困惑度偏移控制在 4.8\%，多跳检索召回率由滑动窗口对照组的 29.5\% 提升至 87.6\%。进一步地，消融实验表明，适度稀疏压缩（保留比例高于 6.0\%）不会破坏深层检索头的长程注意力连贯性。
\end{document}
"""

ZH_TEX_V2 = r"""\documentclass[UTF8]{ctexart}
\title{基于自适应稀疏路由的长上下文大语言模型推理加速机制研究}
\begin{document}
\maketitle

\begin{abstract}
长上下文大语言模型在自回归解码阶段易出现键值缓存显存膨胀并拖慢服务响应。本文通过多尺度推理对比实验（$n = 48$），定量评估自适应稀疏路由（AdaptRoute）对长程检索任务的加速效果，并分析注意力熵阈值与分块粒度的影响规律。结果表明，在推荐配置下，AdaptRoute 使并发吞吐量提高 2.35 倍，单令牌解码延迟下降 68.4\%（$p < 0.01$），验证了低损动态缓存压缩的可行性。
\end{abstract}

\section{引言}
长文档理解与代码库级推理对大语言模型的上下文容量提出了更高要求~\cite{dao2022neurips,vaswani2017neurips}。传统全量注意力缓存占用显存过高，且易受带宽限制。依据层级注意力熵动态筛选关键键值块，可在低精度损失条件下将远距离证据令牌保留在高速缓存中（图~\ref{fig:route_cn}）。

\section{实验设计与分析方法}
实验采用开源 7B 与 70B 模型，在 128K 上下文与 BF16 精度下设置三组平行评测。使用硬件性能计数器分析压缩前后显存带宽利用率，并测定端到端解码延迟 $L_r$（$\text{ms token}^{-1}$）。

\begin{equation}
L_r = E_0 \max\!\left(0,\, \frac{\tau_b - \tau_c}{\tau_c}\right)^{1.5}
\end{equation}

\section{结果与讨论}
如表~\ref{tab:cn_res} 所示，两阶段自适应预算校准后，128K 场景下的相对困惑度偏移降至 4.6\%，多跳检索召回率由滑动窗口对照组的 29.5\% 提高至 87.6\%。消融监测显示，当保留比例维持在 6.0\% 以上时，深层检索头的长程注意力连贯性未见明显退化。
\end{document}
"""

# ==============================================================================
# 04. English Word Manuscripts (.docx)
# ==============================================================================
EN_DOCX_V1 = [
    ("title", "Speculative Tree Verification for Low-Latency LLM Decoding"),
    ("h1", "1. Introduction"),
    (
        "p",
        "Speculative decoding plays a pivotal role in accelerating autoregressive language model generation without altering output distributions (Vaswani et al., 2017). However, existing draft architectures rely on linear token chains that exhibit fundamental acceptance bottlenecks. Moreover, combining tree-structured draft verification with adaptive branch pruning offers a comprehensive paradigm for maximizing accepted tokens per step, as illustrated in Fig. 1.",
    ),
    ("h1", "2. Evaluation Suite and Benchmark Setup"),
    (
        "p",
        "We compiled 124 paired reasoning and code prompts evaluated across four model scales (n = 124; context window 4K-64K). Validation against exact greedy decoding yielded a cross-validated speedup correlation of R2 = 0.89 with a mean latency overhead of 14.2 ± 2.1% (p = 0.004) [12, 14].",
    ),
    ("image", make_chart_png([0.42, 0.58, 0.64, 0.51], (37, 99, 235))),
    ("caption", "Figure 1. Acceptance rate distribution of speculative draft trees along benchmark B3."),
    ("h1", "3. Results"),
    (
        "p",
        "Across all four model scales, tree-verified drafts peaked preferentially at depth 4-6, accounting for 58.7% of total speedup gains (Table 2). Notably, dynamic temperature shifts temporarily reduced acceptance length within 18 decode steps.",
    ),
    (
        "table",
        [
            ["Task Split", "Benchmark Metrics", "__MERGE_LEFT__", "Speedup Share (%)"],
            ["Math QA", "31", "4.2 tok", "54.2"],
            ["Code Gen", "34", "3.8 tok", ("63.8", True)],
            ["Summary", "29", "5.1 tok", "57.1"],
        ],
    ),
]

EN_DOCX_V2 = [
    ("title", "Speculative Tree Verification for Low-Latency LLM Decoding"),
    ("h1", "1. Introduction"),
    (
        "p",
        "Speculative decoding strongly accelerates autoregressive language model generation while keeping exact output distributions (Vaswani et al., 2017). Standard draft models propose linear token chains and suffer from low branch acceptance. Joint tree-structured draft verification and adaptive pruning enables higher accepted token length per forward pass, as shown in Fig. 1.",
    ),
    ("h1", "2. Evaluation Suite and Benchmark Setup"),
    (
        "p",
        "We assembled 124 paired reasoning and code prompts across four model scales (n = 124; context range 4K-64K). Validation against exact greedy decoding gave a cross-validated R2 = 0.89 and a mean latency overhead of 14.5 ± 2.1% (p = 0.004) [12].",
    ),
    ("image", make_chart_png([0.42, 0.61, 0.68, 0.53], (16, 185, 129))),
    ("caption", "Figure 1. Tree-verified speculative acceptance gains along reasoning benchmark B3."),
    ("h1", "3. Results"),
    (
        "p",
        "Across all four model scales, tree-verified acceptance peaks clustered at depth 4-6 and contributed 58.7% of total speedup gains (Table 2). Dynamic temperature shifts temporarily lowered acceptance length within 18 decode steps.",
    ),
    (
        "table",
        [
            ["Task Split", "Benchmark Metrics", "__MERGE_LEFT__", "Speedup Share (%)"],
            ["Math QA", "31", "4.2 tok", "54.2"],
            ["Code Gen", "34", "3.8 tok", ("64.1", True)],
            ["Summary", "29", "5.1 tok", "57.1"],
        ],
    ),
    (
        "p",
        "Sensitivity tests further show that omitting draft entropy pruning increases verification RMSE by 23.4%, confirming the necessity of adaptive branch constraints.",
    ),
]

# ==============================================================================
# 05. Chinese Word Manuscripts (.docx)
# ==============================================================================
ZH_DOCX_V1 = [
    ("title", "长上下文大语言模型推理加速与不确定性校准研究"),
    ("h1", "一、立项依据与研究意义"),
    (
        "p",
        "值得注意的是，长上下文大语言模型的键值缓存显存效率直接关系到复杂智能体系统的实时响应，其精准优化至关重要[1-3]。综上所述，传统固定窗口裁剪模式难以全方位捕捉长序列中的稀疏关键令牌，导致推理准确率存在较大偏差。与此同时，将注意力熵先验知识赋能自适应路由设计，能够显著提升有限显存预算下的信息保留率（见图 1）。",
    ),
    ("h1", "二、核心研究内容与技术指标"),
    (
        "p",
        "本项目拟基于 120 组长程推理评测集（n = 120），构建考虑层级头部分化与块级稀疏融合的层次概率模型，并发展面向显存约束的序贯路由策略。预期在单层 8 块缓存预算下，将长上下文推理相对误差降低 32.4% 以上，关键任务置信校准覆盖率稳定在 92.0% 至 96.0% 区间内（详见表 1）。",
    ),
    ("caption", "图 1 注意力熵先验约束下的序贯自适应稀疏路由框架示意图。"),
    ("h1", "三、预期成果"),
    (
        "p",
        "项目实施后将形成一套开源的长上下文大模型稀疏推理优化软件，并在国内外人工智能主流学术会议发表高水平论文 2-3 篇。",
    ),
]

ZH_DOCX_V2 = [
    ("title", "长上下文大语言模型推理加速与不确定性校准研究"),
    ("h1", "一、立项依据与研究意义"),
    (
        "p",
        "长上下文大语言模型键值缓存的高效压缩，是提升复杂推理系统响应速度的关键环节[1-3]。传统固定窗口裁剪往往遗漏长序列中的稀疏检索锚点，导致复杂问答任务出现系统性精度衰减。将层级注意力熵先验引入自适应路由规划，可在有限显存预算内显著提高信息保留增益（见图 1）。",
    ),
    ("h1", "二、核心研究内容与技术指标"),
    (
        "p",
        "本项目将整合 120 组长程推理评测集（n = 120），建立耦合层级头部分化与块级稀疏融合的层次概率先验模型，并提出考虑访存带宽开销的序贯路由算法。在单层 8 块缓存约束下，目标将长上下文推理相对误差降低 34.2% 以上，后验 95% 置信区间覆盖率维持在 92.0% 至 96.0% 之间。",
    ),
    ("caption", "图 1 注意力熵先验引导的序贯自适应稀疏路由工作流程图。"),
    ("h1", "三、预期成果与示范应用"),
    (
        "p",
        "项目拟发布开源的长上下文稀疏推理优化工具包，并在典型开源大模型集群上完成 1 次全链路基准验证，预计在人工智能与机器学习主流会议发表论文 2-3 篇。",
    ),
]

# ==============================================================================
# 06. Edge-Case Stress Test LaTeX (Line Wraps, Comments, Nested Macros, Math)
# ==============================================================================
EDGE_V1 = r"""\documentclass{article}
\title{Stress Testing \textbf{LaTeX} Parsing: Edge Cases \& Tricky Macros}
\begin{document}

\section{Hard Line Wrap and Comment Immunity}
% Full-line comment that should be completely ignored
This paragraph is deliberately wrapped at narrow column widths in version one
so that line breaks appear every few words, including an escaped 15.2\% percent
sign right before an inline comment % this comment must not appear in diff!
and a \textbf{\emph{nested formatted phrase}} plus a \href{https://example.org}{clickable link}.

\section{Complex Citations, Math, and Heavy Rewrites}
Multiple citations with optional page notes~\citep[see][p.~14]{alpha2023, beta2024} and cross-references to Eq.~\eqref{eq:core} and Fig.~\ref{fig:edge} must remain intact alongside inline math $J(\theta) = \sum_{i=1}^{N} (x_i + y_i)^2$.

\begin{align*}
\mathcal{L}(\theta) &= \frac{1}{N}\sum_{i=1}^N \|f_\theta(x_i) - y_i\|_2^2 + \lambda \|\theta\|_2^2
\end{align*}

This sentence is written in one verbose academic formulation that will be radically paraphrased in the revised version to test low-similarity paragraph alignment behavior under extreme editing.

\end{document}
"""

EDGE_V2 = r"""\documentclass{article}
\title{Stress Testing \textbf{LaTeX} Parsing: Edge Cases \& Tricky Macros}
\begin{document}

\section{Hard Line Wrap and Comment Immunity}
This paragraph is deliberately wrapped at narrow column widths in version one so that line breaks appear every few words, including an escaped 15.2\% percent sign right before an inline comment and a \textbf{\emph{nested formatted phrase}} plus a \href{https://example.org}{clickable link}.

\section{Complex Citations, Math, and Heavy Rewrites}
Multiple citations with optional page notes~\citep[see][p.~14]{alpha2023,beta2024} and cross-references to Eq.~\eqref{eq:core} and Fig.~\ref{fig:edge} must remain intact alongside inline math $J(\theta) = \sum_{i=1}^{N} (x_i - y_i)^2$.

\begin{align*}
\mathcal{L}(\theta) &= \frac{1}{N}\sum_{i=1}^N \|f_\theta(x_i) - y_i\|_2^2 + \lambda_{\text{reg}} \|\theta\|_1
\end{align*}

Here we drastically rewrite the final paragraph with concise wording so that lexical overlap falls near twenty percent while still testing whether block pairing holds.

\end{document}
"""


def main() -> None:
    write_text("01_en_latex_nature_revision/v1_ai_draft.tex", CASE1_V1)
    write_text("01_en_latex_nature_revision/v2_ai_polished_with_traps.tex", CASE1_V2_TRAPS)
    write_text("01_en_latex_nature_revision/v3_human_fixed_final.tex", CASE1_V3_FIXED)

    write_zip_mixed("02_en_latex_overleaf_zip/overleaf_project_v1.zip", ZIP_V1)
    write_zip_mixed("02_en_latex_overleaf_zip/overleaf_project_v2.zip", ZIP_V2)

    write_text("03_zh_latex_thesis/v1_初稿.tex", ZH_TEX_V1)
    write_text("03_zh_latex_thesis/v2_精简修订.tex", ZH_TEX_V2)

    write_docx("04_en_word_manuscript/v1_draft.docx", EN_DOCX_V1)
    write_docx("04_en_word_manuscript/v2_revised.docx", EN_DOCX_V2)

    write_docx("05_zh_word_report/v1_申报书初稿.docx", ZH_DOCX_V1)
    write_docx("05_zh_word_report/v2_修改稿.docx", ZH_DOCX_V2)

    write_text("06_edge_cases_stress_tex/edge_v1.tex", EDGE_V1)
    write_text("06_edge_cases_stress_tex/edge_v2.tex", EDGE_V2)

    print("Generated all 6 test suites successfully in:", OUT_DIR)


if __name__ == "__main__":
    main()
