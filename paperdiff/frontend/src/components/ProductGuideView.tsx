/**
 * @file ProductGuideView.tsx
 * @description Clean, minimal built-in user guide for 对稿 · PaperDiff (v0.1.0).
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  BookOpen,
  Columns2,
  Download,
  FileOutput,
  FolderOpen,
  FolderPlus,
  HelpCircle,
  Keyboard,
  ListTree,
  Lock,
  ShieldCheck,
  Table2,
  Terminal,
} from 'lucide-react';
import { triggerFileDownload } from '../api';
import type { ThemePreference } from '../types';
import { ThemeMenuButton } from './ThemeSwitcher';
import { BrandMark } from './BrandMark';

export interface ProductGuideViewProps {
  hasDemoProject: boolean;
  theme: ThemePreference;
  onChangeTheme: (pref: ThemePreference) => void;
  onBackHome: () => void;
  onCreateProject: () => void;
  onOpenDemo: () => void;
  onOpenQuick: () => void;
}

const GUIDE_SECTIONS = [
  { id: 'guide-overview', title: '1. 简介' },
  { id: 'guide-workflow', title: '2. 基本用法' },
  { id: 'guide-features', title: '3. 常用功能' },
  { id: 'guide-formats', title: '4. 支持格式' },
  { id: 'guide-shortcuts', title: '5. 快捷键' },
  { id: 'guide-faq', title: '6. 常见问题' },
];

const GUIDE_MARKDOWN = `# 对稿 · PaperDiff 使用指南（v0.1.0）

一款完全在本地运行的论文阅读与版本比对工具。支持 LaTeX（.tex / .zip）、Word（.docx）与 Markdown（.md / .txt），不联网、不上传文件。

## 1. 快速上手

1. **绑定论文文件夹（推荐）**：点右上角「新建项目」→「绑定本地文件夹」，直接打开本机目录。外部编辑器或 AI 工具改完文件后，点刷新即可看到最新稿件，无需重复上传。
2. **阅读与排版**：单击任意文件直接阅读。右上角可调整缩进、行距、段距与学术排版预设；双击段落、公式或表格单元格可以直接修改。
3. **两两对比**：在左侧文件树勾选任意两份文件，点「对比」即可左右对照查看改动，自动标出数值、引文、公式、术语和表格变化。
4. **保存与导出**：修改默认「另存为新文件」，覆盖原稿前会自动生成 .paperdiff.bak 备份；也支持直接导出 Word、LaTeX、Overleaf .zip 或离线 PDF 报告。

## 2. 两种启动方式

- **macOS 桌面版**：安装 PaperDiff.app，双击即开；顶栏支持一键「浏览器打开」与安装 \`paperdiff\` 命令行（在终端运行 \`paperdiff .\` 直达当前目录）。
- **跨平台 Web 版（Windows / macOS）**：双击「启动PaperDiff.command / 启动PaperDiff.bat」在后台静默启动，不留黑框终端；点击网页顶栏状态栏即可随时停止服务。

## 3. 常用快捷键

- R：切回阅读模式
- V：切换左右对照 / 行内融合
- J / K：下一处 / 上一处改动
- N / P：下一条 / 上一条核查提醒
- ⌘1：展开或收起左侧文件树
- ⌘2：展开或收起右侧核查抽屉
- 双击段落 / 公式 / 表格单元格：直接修改（⌘↵ 暂存，Esc 取消）
`;

export const ProductGuideView: React.FC<ProductGuideViewProps> = ({
  hasDemoProject,
  theme,
  onChangeTheme,
  onBackHome,
  onCreateProject,
  onOpenDemo,
  onOpenQuick,
}) => {
  const scrollRef = useRef<HTMLElement | null>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    let rafId = 0;
    const onScroll = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        const top = el.getBoundingClientRect().top;
        let cur = 0;
        GUIDE_SECTIONS.forEach((sec, idx) => {
          const node = document.getElementById(sec.id);
          if (node && node.getBoundingClientRect().top - top <= 140) cur = idx;
        });
        setActiveIdx(cur);
      });
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      el.removeEventListener('scroll', onScroll);
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, []);

  const jumpTo = (id: string) => {
    const node = document.getElementById(id);
    if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-white text-slate-900">
      <header className="z-30 flex h-[54px] shrink-0 items-center justify-between gap-3 border-b border-[#E6E8EE] bg-white px-5">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onBackHome}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-[#FAFBFC] px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回首页
          </button>
          <span className="text-slate-200">/</span>
          <span className="inline-flex items-center gap-2 text-xs font-bold text-slate-800">
            <BrandMark size={18} />
            使用指南
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600">
              v0.1.0
            </span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          <ThemeMenuButton value={theme} onChange={onChangeTheme} />
          <button
            type="button"
            onClick={() =>
              triggerFileDownload(
                GUIDE_MARKDOWN,
                'PaperDiff_v0.1.0_使用指南.md',
                'text/markdown;charset=utf-8',
              )
            }
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            <Download className="h-3.5 w-3.5 text-slate-500" />
            导出 Markdown
          </button>
          <button
            type="button"
            onClick={onCreateProject}
            className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 shadow-xs"
          >
            <FolderPlus className="h-3.5 w-3.5" />
            新建项目
          </button>
        </div>
      </header>

      <main ref={scrollRef} className="relative flex-1 overflow-y-auto bg-white">
        <div className="mx-auto w-full max-w-[1440px] px-6 sm:px-10 pt-10 pb-24 xl:grid xl:grid-cols-[180px_minmax(0,1fr)_80px] xl:items-start xl:gap-10">
          <aside className="hidden xl:block sticky top-10">
            <div className="mb-3 inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
              <ListTree className="h-3.5 w-3.5" />
              目录
            </div>
            <nav className="border-l border-slate-100 space-y-0.5">
              {GUIDE_SECTIONS.map((sec, idx) => (
                <button
                  key={sec.id}
                  type="button"
                  onClick={() => jumpTo(sec.id)}
                  className={`-ml-px block w-full border-l-2 py-1.5 pl-3 text-left text-xs transition-colors ${
                    idx === activeIdx
                      ? 'border-blue-600 font-semibold text-slate-900'
                      : 'border-transparent text-slate-400 hover:border-slate-300 hover:text-slate-700'
                  }`}
                >
                  {sec.title}
                </button>
              ))}
            </nav>
          </aside>

          <div className="w-full min-w-0 flex justify-center">
            <article className="w-full max-w-[780px] space-y-12">
              <header id="guide-overview" className="scroll-mt-8 border-b border-slate-100 pb-8">
                <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600">
                  <Lock className="h-3 w-3" />
                  纯本地运行 · 不联网 · 不上传文稿
                </div>
                <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-900">
                  对稿 · PaperDiff 使用指南
                </h1>
                <p className="mt-3 text-[14.5px] leading-relaxed text-slate-600">
                  专门用来读论文、比对修改稿、核查关键数据并直接改回原稿的本地工具。打开文件夹就能用，支持 LaTeX、Word 和 Markdown。
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={onCreateProject}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700"
                  >
                    <FolderPlus className="h-3.5 w-3.5" />
                    新建项目
                  </button>
                  {hasDemoProject && (
                    <button
                      type="button"
                      onClick={onOpenDemo}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <BookOpen className="h-3.5 w-3.5" />
                      打开示例论文
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={onOpenQuick}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <Columns2 className="h-3.5 w-3.5" />
                    临时快速对比
                  </button>
                </div>
              </header>

              <section id="guide-workflow" className="scroll-mt-8 space-y-4">
                <h2 className="text-lg font-bold text-slate-900">基本用法</h2>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                  {[
                    {
                      step: '01',
                      title: '打开文件夹或上传',
                      desc: '新建项目时选择「绑定本地文件夹」，直接浏览本机论文目录；也可继续使用手动上传保存历史版本。',
                    },
                    {
                      step: '02',
                      title: '精读与现场修改',
                      desc: '点击文件直接阅读，支持调整缩进、行距与排版预设。双击段落、公式或表格单元格即可修改。',
                    },
                    {
                      step: '03',
                      title: '两两对比与导出',
                      desc: '勾选任意两份稿件做左右对比，核查数值、引文与公式变化；修改可另存副本、备份后覆盖或导出 PDF。',
                    },
                  ].map((item) => (
                    <div key={item.step} className="rounded-2xl border border-slate-200/80 bg-[#FAFBFC] p-4">
                      <div className="font-mono text-xs font-bold text-blue-600">{item.step}</div>
                      <h3 className="mt-1.5 text-sm font-bold text-slate-900">{item.title}</h3>
                      <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{item.desc}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section id="guide-features" className="scroll-mt-8 space-y-4">
                <h2 className="text-lg font-bold text-slate-900">常用功能</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  {[
                    {
                      icon: FolderOpen,
                      title: '本地文件夹工作区',
                      desc: '直接绑定论文所在文件夹，自动隐藏编译临时文件。外部编辑器或 AI 工具改完文件后，切回窗口即可同步最新内容；删除项目绝不动磁盘原文件。',
                    },
                    {
                      icon: BookOpen,
                      title: '清晰的学术阅读排版',
                      desc: '保留原稿首行缩进、多级列表和引用层级，内置中文论文、英文期刊等排版预设；Word 文件支持随时切换「Word 原版」核对封面和页眉。',
                    },
                    {
                      icon: ShieldCheck,
                      title: '自动核查关键改动',
                      desc: '对比两版文稿时，自动标出数值、百分比、p 值、引文、交叉引用、公式符号和关键术语的变动，核对无误后可一键标记已确认。',
                    },
                    {
                      icon: Table2,
                      title: '直接改表与正文防漏',
                      desc: '双击表格单元格即可编辑，支持加粗最优值和增删行。改动表内数值后，若正文仍引用旧数值会自动提醒并支持跳转。',
                    },
                    {
                      icon: FileOutput,
                      title: '保原格式保存与离线 PDF',
                      desc: '改完支持另存新文件或备份后覆盖原文件，保留 Word 封面边框、LaTeX 导言区与 Overleaf 目录结构；断网也能导出清晰 PDF 报告。',
                    },
                    {
                      icon: Terminal,
                      title: '跨平台启动与终端直达',
                      desc: 'macOS 支持 .dmg 桌面端与一键安装 paperdiff 命令（终端运行 paperdiff . 直达当前目录）；Windows 与 macOS 均支持后台静默 Web 启动。',
                    },
                  ].map((feat) => {
                    const Icon = feat.icon;
                    return (
                      <div key={feat.title} className="rounded-2xl border border-slate-200/80 bg-white p-4">
                        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                          <Icon className="h-4 w-4 text-blue-600 shrink-0" />
                          <span>{feat.title}</span>
                        </div>
                        <p className="mt-2 text-xs leading-relaxed text-slate-600">{feat.desc}</p>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section id="guide-formats" className="scroll-mt-8 space-y-3">
                <h2 className="text-lg font-bold text-slate-900">支持格式</h2>
                <div className="overflow-x-auto rounded-2xl border border-slate-200/80">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>
                        <th className="px-4 py-2.5 font-semibold">格式</th>
                        <th className="px-4 py-2.5 font-semibold">后缀</th>
                        <th className="px-4 py-2.5 font-semibold">说明</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      <tr>
                        <td className="px-4 py-2.5 font-semibold">LaTeX</td>
                        <td className="px-4 py-2.5 font-mono text-[11px]">.tex, .ltx, .zip</td>
                        <td className="px-4 py-2.5">支持公式宏、化学式、定理框、算法、子图、参考文献样式，可直接回写 .tex 或 Overleaf .zip。</td>
                      </tr>
                      <tr>
                        <td className="px-4 py-2.5 font-semibold">Word</td>
                        <td className="px-4 py-2.5 font-mono text-[11px]">.docx</td>
                        <td className="px-4 py-2.5">支持编号、公式、批注、Word 原版视图与修订痕迹一键拆版；导出时保留原文档封面与样式。</td>
                      </tr>
                      <tr>
                        <td className="px-4 py-2.5 font-semibold">Markdown</td>
                        <td className="px-4 py-2.5 font-mono text-[11px]">.md, .txt</td>
                        <td className="px-4 py-2.5">支持公式、表格、脚注、代码块高亮与 Mermaid 图表。</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              <section id="guide-shortcuts" className="scroll-mt-8 space-y-3">
                <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
                  <Keyboard className="h-4 w-4 text-slate-500" />
                  快捷键
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                  {[
                    ['R', '切回阅读模式'],
                    ['V', '左右对照 / 行内融合切换'],
                    ['J / K', '下一处 / 上一处改动'],
                    ['N / P', '下一条 / 上一条核查提醒'],
                    ['⌘1', '展开或收起左侧文件树'],
                    ['⌘2', '展开或收起右侧核查面板'],
                    ['双击正文 / 单元格', '直接编辑（⌘↵ 暂存，Esc 取消）'],
                    ['Esc', '关闭弹窗、抽屉或编辑框'],
                  ].map(([key, label]) => (
                    <div key={key} className="flex items-center justify-between rounded-xl border border-slate-200/70 px-3.5 py-2">
                      <span className="text-slate-600">{label}</span>
                      <kbd className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700">
                        {key}
                      </kbd>
                    </div>
                  ))}
                </div>
              </section>

              <section id="guide-faq" className="scroll-mt-8 space-y-4">
                <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
                  <HelpCircle className="h-4 w-4 text-slate-500" />
                  常见问题
                </h2>
                <div className="space-y-3 text-xs leading-relaxed text-slate-600">
                  <div className="rounded-2xl border border-slate-200/80 p-4">
                    <div className="font-bold text-slate-900">论文和基金申请书会上传到云端吗？</div>
                    <p className="mt-1">不会。软件只运行在您的本机（127.0.0.1），没有云端账号或外部上传接口，断网状态下全部功能正常使用。</p>
                  </div>
                  <div className="rounded-2xl border border-slate-200/80 p-4">
                    <div className="font-bold text-slate-900">绑定本地文件夹后，删除项目会删掉我的文件吗？</div>
                    <p className="mt-1">不会。解除绑定或删除项目只移除软件里的关联记录，磁盘上的原文件不会被删除或改动。</p>
                  </div>
                  <div className="rounded-2xl border border-slate-200/80 p-4">
                    <div className="font-bold text-slate-900">为什么不支持导入 PDF？</div>
                    <p className="mt-1">PDF 丢掉了公式源码和段落结构，反向提取容易产生大量误报，也无法改回原稿。建议直接用 .tex、.docx 或 .md 原稿核对，定稿后再用本工具导出 PDF。</p>
                  </div>
                </div>
              </section>
            </article>
          </div>
        </div>
      </main>
    </div>
  );
};
