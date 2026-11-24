/**
 * @file DocxOriginalViewer.tsx
 * @description Lazy-loaded pixel-faithful Word (`.docx`) original layout viewer powered by
 * Apache-2.0 `docx-preview`. Fetches the archived binary blob from `/api/versions/{id}/source-blob`
 * and renders paginated A4 pages with headers, footnotes, endnotes, and reviewer comments.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';
import { api } from '../api';

interface DocxOriginalViewerProps {
  versionId?: number;
  localFile?: { projectId: number; relPath: string } | null;
}

const DocxOriginalViewer: React.FC<DocxOriginalViewerProps> = ({ versionId, localFile }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function mountDocx() {
      setLoading(true);
      setError(null);
      try {
        const fetchBuf = localFile
          ? api.fetchLocalRawBlob(localFile.projectId, localFile.relPath)
          : versionId
            ? api.fetchVersionSourceBlob(versionId)
            : Promise.reject(new Error('缺少 Word 原文档来源'));
        const [buf, docxPreview] = await Promise.all([
          fetchBuf,
          import('docx-preview'),
        ]);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = '';
        await docxPreview.renderAsync(buf, containerRef.current, undefined, {
          className: 'pd-docx-orig',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          renderHeaders: true,
          renderFootnotes: true,
          renderEndnotes: true,
          renderComments: true,
          useBase64URL: true,
          experimental: true,
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : '无法加载 Word 原版视图');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    mountDocx();
    return () => {
      cancelled = true;
    };
  }, [versionId, localFile?.projectId, localFile?.relPath]);

  return (
    <div className="relative min-h-[480px] rounded-2xl border border-slate-200/80 bg-slate-100/80 p-4 overflow-x-auto">
      {loading && (
        <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500">
          <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
          正在还原 Word 原版分页、封面与排版…
        </div>
      )}
      {error && (
        <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-sm text-rose-600">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
          <span className="text-xs text-slate-500">
            请重新上传原始 .docx 文件以归档原版二进制（仅支持 v1.1 起新导入的 Word 版本）
          </span>
        </div>
      )}
      <div ref={containerRef} className="pd-docx-preview-host mx-auto" />
    </div>
  );
};

export default DocxOriginalViewer;
