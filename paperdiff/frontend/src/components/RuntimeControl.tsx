/**
 * @file RuntimeControl.tsx
 * @description Topbar runtime control for dual launch channels:
 * - macOS Desktop (`window.pywebview.api.open_in_browser`): "在浏览器中打开" button preserving active project URL.
 * - Cross-Platform Web (`health.can_shutdown`): status pill ("本地运行中 · :port") with popover and
 *   draft-protected local server shutdown modal + static stopped screen.
 */

import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ExternalLink, Power, Terminal, X } from 'lucide-react';
import type { CliInstallStatus, RuntimeHealth } from '../api';
import { getDesktopApi } from '../api';
import { evaluateStopGuard } from '../utils/runtime';

interface RuntimeControlProps {
  health: RuntimeHealth | null;
  handoffPath: string;
  draftEditsCount: number;
  onRequestShutdown: () => Promise<void>;
  onNotify?: (msg: string) => void;
}

export const RuntimeControl: React.FC<RuntimeControlProps> = ({
  health,
  handoffPath,
  draftEditsCount,
  onRequestShutdown,
  onNotify,
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [cliPopoverOpen, setCliPopoverOpen] = useState(false);
  const [cliStatus, setCliStatus] = useState<CliInstallStatus | null>(null);
  const [cliBusy, setCliBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const desktopApi = getDesktopApi();
  const isDesktop = Boolean(desktopApi?.open_in_browser);
  const hasCliBridge = Boolean(desktopApi?.install_cli_command && desktopApi?.get_cli_install_status);

  useEffect(() => {
    if (!popoverOpen && !cliPopoverOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
        setCliPopoverOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [popoverOpen, cliPopoverOpen]);

  if (isDesktop) {
    const refreshCliStatus = async () => {
      if (!desktopApi?.get_cli_install_status) return;
      try {
        const st = await desktopApi.get_cli_install_status();
        setCliStatus(st);
      } catch {
        /* ignore */
      }
    };

    return (
      <div ref={wrapRef} className="relative flex items-center gap-1.5 shrink-0">
        {hasCliBridge && (
          <div className="relative">
            <button
              type="button"
              data-desktop-cli-btn="true"
              title="安装或管理 paperdiff 终端快捷命令（支持 paperdiff . 直达论文目录）"
              onClick={() => {
                const next = !cliPopoverOpen;
                setCliPopoverOpen(next);
                if (next) void refreshCliStatus();
              }}
              className="pd-runtime-pill inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors shrink-0"
            >
              <Terminal className="h-3.5 w-3.5" />
              <span className="hidden xl:inline">命令行</span>
            </button>

            {cliPopoverOpen && (
              <div
                data-desktop-cli-popover="true"
                className="pd-runtime-popover absolute right-0 mt-1.5 w-80 rounded-2xl border p-3.5 shadow-xl z-50 text-xs"
              >
                <div className="flex items-center justify-between pb-2 border-b border-slate-200/70">
                  <span className="font-semibold">终端快捷命令 (`paperdiff .`)</span>
                  <span
                    data-desktop-cli-state={cliStatus?.installed ? 'installed' : 'not_installed'}
                    className={`rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold ${
                      cliStatus?.installed
                        ? 'bg-emerald-500/15 text-emerald-700'
                        : 'bg-slate-200/70 text-slate-600'
                    }`}
                  >
                    {cliStatus?.installed ? '已安装' : '未安装'}
                  </span>
                </div>
                <p className="pd-runtime-muted mt-2 text-[11.5px] leading-relaxed">
                  安装后，可在终端运行 <code>paperdiff .</code> 直接打开当前目录。
                </p>
                {cliStatus?.script_path && (
                  <div className="mt-2 rounded-lg border border-slate-200/70 px-2 py-1 font-mono text-[10.5px] break-all">
                    {cliStatus.script_path}
                  </div>
                )}
                {cliStatus?.installed && cliStatus.in_path === false && cliStatus.path_hint && (
                  <div
                    data-desktop-cli-path-hint="true"
                    className="pd-resume-warn mt-2 rounded-lg border px-2.5 py-1.5 text-[11px] leading-relaxed"
                  >
                    {cliStatus.path_hint.includes('setx') ? (
                      <>当前目录未在 <code>PATH</code> 中，可在终端执行下面命令添加（重开终端生效）：</>
                    ) : (
                      <>当前目录未在 <code>$PATH</code> 中，可将下面命令加入 <code>~/.zshrc</code>：</>
                    )}
                    <div className="mt-1 font-mono text-[10.5px] break-all">{cliStatus.path_hint}</div>
                  </div>
                )}
                {cliStatus?.error && (
                  <div className="mt-2 rounded-lg border border-rose-300 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700">
                    {cliStatus.error}
                  </div>
                )}
                <div className="mt-3 flex items-center gap-2">
                  {!cliStatus?.installed ? (
                    <button
                      type="button"
                      data-desktop-cli-install-btn="true"
                      disabled={cliBusy}
                      onClick={async () => {
                        setCliBusy(true);
                        try {
                          const res = await desktopApi?.install_cli_command?.();
                          if (res) {
                            setCliStatus(res);
                            onNotify?.(res.installed ? '已安装 paperdiff 命令行工具' : res.error || '安装失败');
                          }
                        } finally {
                          setCliBusy(false);
                        }
                      }}
                      className="pd-resume-cta flex-1 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-60"
                    >
                      {cliBusy ? '安装中…' : '安装 paperdiff 命令'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      data-desktop-cli-uninstall-btn="true"
                      disabled={cliBusy}
                      onClick={async () => {
                        setCliBusy(true);
                        try {
                          const res = await desktopApi?.uninstall_cli_command?.();
                          if (res) {
                            setCliStatus(res);
                            onNotify?.('已卸载 paperdiff 命令');
                          }
                        } finally {
                          setCliBusy(false);
                        }
                      }}
                      className="pd-runtime-pill flex-1 rounded-xl border px-3 py-1.5 text-xs font-medium"
                    >
                      {cliBusy ? '处理中…' : '卸载命令'}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          data-runtime-open-browser="true"
          title="在系统默认浏览器中打开当前工作台（共享同一本地端口）"
          onClick={async () => {
            try {
              const res = await desktopApi?.open_in_browser?.(handoffPath);
              if (res?.opened) {
                onNotify?.('已在系统浏览器中打开当前页面');
              } else {
                onNotify?.(res?.error || '无法在浏览器中打开');
              }
            } catch {
              onNotify?.('在浏览器中打开失败');
            }
          }}
          className="pd-runtime-pill inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors shrink-0"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          <span className="hidden xl:inline">浏览器打开</span>
        </button>
      </div>
    );
  }

  if (!health?.can_shutdown) {
    return null;
  }

  const portLabel = health.port || (typeof window !== 'undefined' && window.location.port ? Number(window.location.port) : 8765);

  const executeStop = async () => {
    setStopping(true);
    try {
      await onRequestShutdown();
    } finally {
      setStopping(false);
      setConfirmOpen(false);
      setPopoverOpen(false);
    }
  };

  const handleStopClick = () => {
    const guard = evaluateStopGuard(draftEditsCount);
    if (guard.requiresDraftConfirm) {
      setPopoverOpen(false);
      setConfirmOpen(true);
      return;
    }
    void executeStop();
  };

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        type="button"
        data-runtime-status-pill="true"
        onClick={() => setPopoverOpen((v) => !v)}
        title={`本地服务运行中（127.0.0.1:${portLabel}），点击查看状态或停止服务`}
        className="pd-runtime-pill inline-flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-medium transition-colors"
      >
        <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
        <span className="tabular-nums">本地运行中 · :{portLabel}</span>
      </button>

      {popoverOpen && (
        <div
          data-runtime-popover="true"
          className="pd-runtime-popover absolute right-0 mt-1.5 w-72 rounded-2xl border p-3.5 shadow-xl z-50 text-xs"
        >
          <div className="flex items-center justify-between pb-2 border-b border-slate-200/70">
            <div className="flex items-center gap-1.5 font-semibold">
              <Terminal className="h-3.5 w-3.5 text-emerald-600" />
              <span>本地服务状态</span>
            </div>
            <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700">
              v{health.version}
            </span>
          </div>

          <div className="mt-2.5 space-y-1.5 text-[11.5px]">
            <div className="flex items-center justify-between gap-2">
              <span className="pd-runtime-muted">监听地址</span>
              <span className="font-mono tabular-nums">127.0.0.1:{portLabel}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="pd-runtime-muted">进程 PID</span>
              <span className="font-mono tabular-nums">{health.pid}</span>
            </div>
            {health.log_path && (
              <div className="pt-1">
                <div className="pd-runtime-muted mb-0.5">运行日志</div>
                <div className="rounded-lg border border-slate-200/70 px-2 py-1 font-mono text-[10.5px] break-all">
                  {health.log_path}
                </div>
              </div>
            )}
          </div>

          <div className="mt-3 pt-2.5 border-t border-slate-200/70">
            <button
              type="button"
              data-runtime-stop-btn="true"
              disabled={stopping}
              onClick={handleStopClick}
              className="pd-runtime-stop-btn flex w-full items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-colors disabled:opacity-60"
            >
              <Power className="h-3.5 w-3.5" />
              {stopping ? '正在停止本地服务…' : '停止本地服务'}
            </button>
          </div>
        </div>
      )}

      {confirmOpen && (
        <div
          data-runtime-stop-confirm="true"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-[2px]"
        >
          <div className="pd-runtime-popover w-full max-w-md rounded-2xl border p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-bold text-amber-700">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>存在未保存修订草稿</span>
              </div>
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-2.5 text-xs leading-relaxed">
              当前工作区仍有 <strong>{draftEditsCount}</strong> 项未保存的暂存微调。立即停止本地服务会导致这些未落盘草稿丢失，建议先保存后再停止。
            </p>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                data-runtime-stop-cancel="true"
                onClick={() => setConfirmOpen(false)}
                className="pd-runtime-pill rounded-xl border px-3.5 py-1.5 text-xs font-medium"
              >
                取消，返回保存
              </button>
              <button
                type="button"
                data-runtime-stop-confirm-btn="true"
                disabled={stopping}
                onClick={() => void executeStop()}
                className="pd-runtime-stop-btn rounded-xl px-3.5 py-1.5 text-xs font-semibold"
              >
                {stopping ? '正在停止…' : '仍要停止服务'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export const ServiceStoppedOverlay: React.FC<{ port?: number }> = ({ port }) => (
  <div
    data-runtime-stopped-screen="true"
    className="flex h-screen w-screen items-center justify-center bg-[#F6F7F9] p-6"
  >
    <div className="pd-runtime-popover w-full max-w-md rounded-2xl border p-7 text-center shadow-xl">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900/10">
        <Power className="h-6 w-6" />
      </div>
      <h1 className="mt-4 text-base font-bold">本地服务已停止</h1>
      <p className="pd-runtime-muted mt-2 text-xs leading-relaxed">
        端口{port ? `（127.0.0.1:${port}）` : ''}已释放，可以安全关闭此页面。
      </p>
      <p className="pd-runtime-muted mt-3 text-[11.5px] leading-relaxed">
        下次使用时，双击启动脚本或打开 PaperDiff 即可。
      </p>
    </div>
  </div>
);
