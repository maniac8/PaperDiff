"""Built-in Demo Academic Manuscript Seeder for First-Time Onboarding.

Populates a self-contained two-version sample paper project when the local SQLite database
is empty so new users can immediately test Single-Doc Read Mode, Split Compare, fact-conservation
alerts (numeric drift, missing citations, AI cliches), and lossless export.
"""
from __future__ import annotations

from .analyzer import extract_ai_isms
from .database import create_document, create_project, create_version, list_projects
from .diff_engine import count_academic_words
from .parsers import parse_document

EN_V1_LATEX = r"""\title{Evidence-Grounded Multimodal Clinical Screening via Verifiable Conflict Resolution}

\begin{document}

\begin{abstract}
Multimodal clinical screening models leverage audio, visual, and linguistic signals to support early risk assessment. However, existing paradigms exhibit fundamental limitations when facing sensor dropout and cross-modal disagreement. In this work, we delve into an auditable evidence-verification framework that reduces prediction error by 14.8\% ($p < 0.01$, $n = 412$) while generating clinician-verifiable reasoning traces.
\end{abstract}

\section{Introduction}

Most existing screening architectures predict in a single forward pass, mapping session measurements to a scalar risk score through modality-specific encoders and a latent fusion network. This single-pass paradigm exhibits two fundamental failure modes. First, tracking loss, acoustic interference, and missing temporal windows are pervasive in real-world interviews, meaning a high-confidence prediction may rest on corrupted or incomplete measurements. Second, even intact modalities frequently disagree across an interview, and latent space fusion absorbs this cross-modal conflict into an black-box vector rather than exposing and resolving it. Prompting a multimodal large language model (LLM) to reflect on its initial answer is a natural remedy, yet re-prompting on the identical input view without new evidence largely repeats the initial prediction, as illustrated in Fig.~\ref{fig:motivation}. Moreover, neither standard neural fusion nor unconstrained reflection leaves an auditable record that a clinician can verify.

To address these challenges, we introduce \textbf{VeriScreen}, a two-stage screening framework that separates modality quality auditing from cross-modal hypothesis verification~\cite{chen2024multimodal,smith2023clinical}. Crucially, our approach preserves calibrated uncertainty across all three clinical cohorts ($n = 412$) and lowers false-negative rates from 18.4\% to 11.2\% ($p = 0.003$).

\section{Method}

Given an interview recording $x = (x_a, x_v, x_t)$, each modality encoder computes both a calibrated log-odds estimate $s_m$ and a signal reliability weight $w_m \in [0, 1]$:

\begin{equation}
\hat{y}_{\text{init}} = \sigma\!\left(\sum_{m \in \{a,v,t\}} \tilde{w}_m s_m\right), \quad \tilde{w}_m = \frac{w_m}{\sum_k w_k}.
\end{equation}

When cross-modal variance exceeds a clinical threshold $\tau = 0.35$, our verifier retrieves raw acoustic and transcript segments from the conflicting time windows rather than relying on the initial pooled embedding~\cite{smith2023clinical}.

\begin{figure}[t]
\caption{Comparison between single-pass latent fusion, unconstrained LLM reflection, and our evidence-grounded verification loop on real-world clinical interviews.}
\label{fig:motivation}
\end{figure}

\end{document}
"""

EN_V2_LATEX = r"""\title{Evidence-Grounded Multimodal Clinical Screening via Verifiable Conflict Resolution}

\begin{document}

\begin{abstract}
Multimodal clinical screening models combine audio, visual, and text signals to support early risk assessment. Existing single-pass designs struggle with sensor dropout and conflicting modalities. We present a structured evidence-verification framework that reduces prediction error by 14.8\% ($p < 0.01$, $n = 412$) and produces clear reasoning records that clinicians can inspect directly.
\end{abstract}

\section{Introduction}

Most existing screening models make predictions in a single forward pass by feeding session measurements through modality encoders and a fusion network. This single-pass design has two clear drawbacks. First, tracking failures, acoustic noise, and missing time windows are common in recorded interviews, so a confident prediction may rely on corrupted data. Second, even clean modalities often point in opposite directions within the same session, and standard feature fusion averages out these conflicts inside hidden layers rather than resolving them explicitly. Asking a large language model to reflect on its initial answer is a natural alternative, but re-prompting on the exact same input without new evidence mostly repeats the first prediction, as shown in Fig.~\ref{fig:motivation}. Neither standard feature fusion nor simple re-prompting leaves a clear record that a clinician can verify.

To address these drawbacks, we introduce \textbf{VeriScreen}, a two-stage screening framework that separates signal quality checks from cross-modal verification~\cite{chen2024multimodal}. Our method guarantees calibrated uncertainty across all three clinical cohorts ($n = 412$) and lowers false-negative rates from 18.4\% to 11.5\% ($p = 0.003$).

\section{Method}

Given an interview recording $x = (x_a, x_v, x_t)$, each modality encoder computes a calibrated log-odds estimate $s_m$ and a signal reliability weight $w_m \in [0, 1]$:

\begin{equation}
\hat{y}_{\text{init}} = \sigma\!\left(\sum_{m \in \{a,v,t\}} \tilde{w}_m s_m\right), \quad \tilde{w}_m = \frac{w_m}{\sum_k w_k}.
\end{equation}

When cross-modal disagreement exceeds a threshold $\tau = 0.35$, the verifier pulls raw audio and transcript clips from the conflicting time windows instead of reusing the pooled embedding~\cite{smith2023clinical}.

\begin{figure}[t]
\caption{Comparison of single-pass feature fusion, simple LLM re-prompting, and our evidence-grounded verification workflow across recorded clinical interviews.}
\label{fig:motivation}
\end{figure}

\end{document}
"""

EN_V3_LATEX = r"""\title{Evidence-Grounded Multimodal Clinical Screening via Verifiable Conflict Resolution}

\begin{document}

\begin{abstract}
Multimodal clinical screening models combine audio, visual, and text signals to support early risk assessment. Existing single-pass designs struggle with sensor dropout and conflicting modalities. We present a structured evidence-verification framework that reduces prediction error by 14.8\% ($p < 0.01$, $n = 412$) and produces clear reasoning records that clinicians can inspect directly.
\end{abstract}

\section{Introduction}

Most existing screening models make predictions in a single forward pass by feeding session measurements through modality encoders and a fusion network. This single-pass design has two clear drawbacks. First, tracking failures, acoustic noise, and missing time windows are common in recorded interviews, so a confident prediction may rely on corrupted data. Second, even clean modalities often point in opposite directions within the same session, and standard feature fusion averages out these conflicts inside hidden layers rather than resolving them explicitly. Asking a large language model to reflect on its initial answer is a natural alternative, but re-prompting on the exact same input without new evidence mostly repeats the first prediction, as shown in Fig.~\ref{fig:motivation}. Neither standard feature fusion nor simple re-prompting leaves a clear record that a clinician can verify.

To address these drawbacks, we introduce \textbf{VeriScreen}, a two-stage screening framework that separates signal quality checks from cross-modal verification~\cite{chen2024multimodal,smith2023clinical}. Under our evaluation protocol, the method maintains calibrated uncertainty across all three clinical cohorts ($n = 412$) and lowers false-negative rates from 18.4\% to 11.2\% ($p = 0.003$).

\section{Method}

Given an interview recording $x = (x_a, x_v, x_t)$, each modality encoder outputs a calibrated log-odds estimate $s_m$ and a signal reliability weight $w_m \in [0, 1]$:

\begin{equation}
\hat{y}_{\text{init}} = \sigma\!\left(\sum_{m \in \{a,v,t\}} \tilde{w}_m s_m\right), \quad \tilde{w}_m = \frac{w_m}{\sum_k w_k}.
\end{equation}

When cross-modal disagreement exceeds $\tau = 0.35$, the verifier inspects raw audio and transcript clips from the conflicting windows rather than reusing the pooled embedding~\cite{smith2023clinical}.

\begin{figure}[t]
\caption{Comparison of single-pass feature fusion, simple LLM re-prompting, and our evidence-grounded verification workflow across recorded clinical interviews.}
\label{fig:motivation}
\end{figure}

\end{document}
"""

ZH_V1_TEX = r"""\section{引言}

值得注意的是，大语言模型在长上下文推理中的键值缓存（KV-Cache）显存开销对实际部署与吞吐效率至关重要。综上所述，传统推理方案往往依赖固定窗口的稀疏裁剪，难以全方位捕捉远距离语境中的关键检索令牌。与此同时，利用注意力熵先验赋能自适应稀疏路由（AdaptRoute），能够显著提升有限显存预算下的长程推理精度，如图~\ref{fig:route_profile} 所示~\cite{vaswani2017neurips}。

\section{实验结果}

在 128K 长上下文推理基准集（$n = 88$）上，本文提出的多层自适应令牌路由策略将相对误差从 0.412 降低至 0.286，误差降幅达到 30.6\%，且在低显存预算条件下依然保持稳定收敛。
"""

ZH_V2_TEX = r"""\section{引言}

大语言模型在长上下文推理中的键值缓存（KV-Cache）开销直接影响推理延迟与吞吐效率。传统稀疏方案多采用固定窗口裁剪，容易遗漏远距离语境中的关键信息令牌。结合层级注意力熵先验与自适应稀疏路由（AdaptRoute），可在有限显存预算下更有效地改善长程推理精度，如图~\ref{fig:route_profile} 所示~\cite{vaswani2017neurips}。

\section{实验结果}

在 128K 长上下文推理基准集（$n = 88$）上，所提出的多层自适应令牌路由策略将相对误差由 0.412 降至 0.286（下降 30.6\%），并在低显存预算场景中保持稳定收敛。
"""


REBUTTAL_V1 = r"""\section{Response to Reviewer 1}

We thank Reviewer 1 for the constructive feedback regarding calibration under missing modality windows. We have added a dedicated sensitivity analysis across 412 sessions in Section 4.2 and clarified that false-negative rates drop from 18.4\% to 11.2\% ($p = 0.003$).
"""


def _register_version(
    project_id: int,
    document_id: int,
    label: str,
    tag: str,
    filename: str,
    content: str,
    notes: str,
    is_milestone: bool = False,
) -> None:
    fmt, blocks = parse_document(content, "auto", filename)
    clean_full = "\n\n".join(b.clean_text for b in blocks if b.block_type != "heading")
    wc = count_academic_words(clean_full)
    pc = sum(1 for b in blocks if b.block_type != "heading")
    ai_cnt = len(extract_ai_isms(clean_full))
    create_version(
        project_id,
        label,
        tag,
        filename,
        fmt,
        content,
        notes,
        wc,
        pc,
        ai_cnt,
        document_id=document_id,
        is_milestone=is_milestone,
    )


def seed_demo_data_if_empty() -> None:
    if list_projects():
        return

    p1 = create_project(
        name="Multimodal Clinical Screening (英文论文示例)",
        description="含参考截图经典去 AI 味段落、数值/引文/断言告警与多文档层级演示",
        category="paper",
        status="revising",
        primary_format="latex",
        protected_terms=["VeriScreen", "log-odds", "cross-modal"],
        default_doc_name="主论文正文 (Main Manuscript)",
    )
    doc1 = p1["documents"][0]["id"]
    _register_version(p1["id"], doc1, "v1 · AI 初稿", "AI初稿", "manuscript_v1.tex", EN_V1_LATEX, "初版 LaTeX 稿，含较多 AI 套话表达")
    _register_version(p1["id"], doc1, "v2 · AI 去味润色", "AI润色", "manuscript_v2.tex", EN_V2_LATEX, "去 AI 味改写（含 11.2%->11.5% 数值变动与引文丢失演示）")
    _register_version(p1["id"], doc1, "v3 · 人工校验投稿版", "人工修复", "manuscript_v3.tex", EN_V3_LATEX, "修复审计告警后的初次投稿定稿", is_milestone=True)

    doc1_reb = create_document(p1["id"], "审稿回复 (Response Letter)", "rebuttal", "latex", "一审意见逐点回复")
    _register_version(p1["id"], doc1_reb["id"], "v1 · 回复初稿", "手改", "rebuttal_v1.tex", REBUTTAL_V1, "Reviewer 1 初步回复")

    p2 = create_project(
        name="2026 长上下文大模型稀疏推理优化 (中文示例)",
        description="演示中文论文的精准分词比对、去冗余改写与实验数值核查",
        category="paper",
        status="polishing",
        primary_format="latex",
        protected_terms=["KV-Cache", "AdaptRoute", "FlashAttention"],
        default_doc_name="论文正文",
    )
    doc2 = p2["documents"][0]["id"]
    _register_version(p2["id"], doc2, "v1 · 论文初稿", "AI初稿", "cn_v1.tex", ZH_V1_TEX, "含典型中文过渡套话")
    _register_version(p2["id"], doc2, "v2 · 精简修订版", "手改", "cn_v2.tex", ZH_V2_TEX, "去除空泛套话，保留全部实验数值与引文", is_milestone=True)
