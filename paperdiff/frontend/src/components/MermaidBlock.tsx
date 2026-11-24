/**
 * @file MermaidBlock.tsx
 * @description Lazy-loaded 100% offline Mermaid diagram renderer (`React.lazy` code-split chunk)
 * with PaperDiff brand indigo/slate Light & Dark palettes, automatic theme re-rendering on
 * `data-theme` mutations, and raw source toggle.
 */

import React, { useEffect, useId, useState } from 'react';
import { Code2, Eye } from 'lucide-react';

interface MermaidBlockProps {
  code: string;
}

const MermaidBlock: React.FC<MermaidBlockProps> = React.memo(({ code }) => {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function renderDiagram() {
      try {
        const mod = await import('mermaid');
        const mermaid = mod.default;
        const themeAttr = document.documentElement.getAttribute('data-theme') || 'light';
        const isDark = themeAttr === 'dark';
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: 'base',
          themeVariables: isDark
            ? {
                fontFamily: 'inherit',
                primaryColor: '#1E293B',
                primaryBorderColor: '#60A5FA',
                primaryTextColor: '#F1F5F9',
                lineColor: '#94A3B8',
                secondaryColor: '#0F172A',
                tertiaryColor: '#1E293B',
              }
            : {
                fontFamily: 'inherit',
                primaryColor: '#EEF2FF',
                primaryBorderColor: '#4F46E5',
                primaryTextColor: '#1E293B',
                lineColor: '#64748B',
                secondaryColor: '#F8FAFC',
                tertiaryColor: '#FFFFFF',
              },
        });
        const { svg: outSvg } = await mermaid.render(`pd-mermaid-${uid}-${Date.now()}`, code);
        if (!cancelled) {
          setSvg(outSvg);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Mermaid 渲染失败');
          setSvg(null);
        }
      }
    }
    renderDiagram();
    return () => {
      cancelled = true;
    };
  }, [code, uid]);

  return (
    <div className="pd-mermaid-card my-3 rounded-xl border overflow-hidden">
      <div className="flex items-center justify-between px-3.5 py-1.5 border-b border-slate-200/70 text-[11px] text-slate-500">
        <span className="font-mono font-medium">MERMAID 流程图</span>
        <button
          type="button"
          onClick={() => setShowSource((v) => !v)}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 hover:bg-slate-100 text-slate-600"
        >
          {showSource ? <Eye className="w-3 h-3" /> : <Code2 className="w-3 h-3" />}
          {showSource ? '图表视图' : '查看源码'}
        </button>
      </div>
      {showSource || error ? (
        <div className="p-3">
          {error && <div className="mb-2 text-[11px] text-amber-600">语法提示：{error}</div>}
          <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed text-slate-700">{code}</pre>
        </div>
      ) : svg ? (
        <div
          className="flex justify-center overflow-x-auto p-4"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : (
        <div className="py-6 text-center text-xs text-slate-400">正在渲染 Mermaid 矢量图…</div>
      )}
    </div>
  );
});
MermaidBlock.displayName = 'MermaidBlock';

export default MermaidBlock;
