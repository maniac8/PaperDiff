/**
 * @file ThemeSwitcher.tsx
 * @description WCAG-calibrated 4-state theme system controller (`light` | `sepia` | `dark` | `system`)
 * with zero-flicker `data-theme` synchronization and OS `prefers-color-scheme` listener.
 */

import React, { useEffect, useRef, useState } from 'react';
import { BookOpen, Monitor, Moon, Sun } from 'lucide-react';
import type { ThemePreference } from '../types';

export type ResolvedTheme = 'light' | 'sepia' | 'dark';

const STORAGE_KEY = 'paperdiff_theme';

export function loadSavedThemePreference(): ThemePreference {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'sepia' || v === 'dark' || v === 'auto') return v;
  } catch {
    /* ignore */
  }
  return 'light';
}

export function resolveThemePreference(pref: ThemePreference): ResolvedTheme {
  if (pref === 'auto') {
    const prefersDark =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    return prefersDark ? 'dark' : 'light';
  }
  return pref;
}

export function applyThemePreference(pref: ThemePreference): ResolvedTheme {
  const resolved = resolveThemePreference(pref);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved === 'dark' ? 'dark' : 'light';
  try {
    window.localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    /* ignore */
  }
  return resolved;
}

const THEME_OPTIONS: {
  id: ThemePreference;
  label: string;
  desc: string;
  swatchStyle: React.CSSProperties;
}[] = [
  {
    id: 'light',
    label: '浅色',
    desc: '学术纸白 · 印刷对比',
    swatchStyle: { background: '#FFFFFF', border: '1.5px solid #CBD5E1' },
  },
  {
    id: 'sepia',
    label: '护眼',
    desc: '低蓝光暖纸 · 久读不累',
    swatchStyle: { background: '#F7EFE0', border: '1.5px solid #CBB998' },
  },
  {
    id: 'dark',
    label: '深色',
    desc: '静谧炭灰 · 夜间防眩光',
    swatchStyle: { background: '#1B1F26', border: '1.5px solid #475569' },
  },
  {
    id: 'auto',
    label: '自动',
    desc: '跟随 macOS 深浅切换',
    swatchStyle: {
      background: 'linear-gradient(135deg, #FFFFFF 50%, #1B1F26 50%)',
      border: '1.5px solid #94A3B8',
    },
  },
];

/** Compact 4-pill swatch selector for Studio ⚙ Settings Popover */
export const ThemeSegmentedControl: React.FC<{
  value: ThemePreference;
  onChange: (pref: ThemePreference) => void;
}> = ({ value, onChange }) => {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-600">界面色调</span>
        <span className="text-[10.5px] text-slate-400">
          {THEME_OPTIONS.find((o) => o.id === value)?.desc}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-1 rounded-xl bg-slate-100 p-1">
        {THEME_OPTIONS.map((opt) => {
          const active = value === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => onChange(opt.id)}
              title={opt.desc}
              className={`flex flex-col items-center justify-center gap-1 rounded-lg py-1.5 text-[11px] transition-all ${
                active
                  ? 'bg-white text-slate-900 shadow-xs font-semibold ring-1 ring-blue-500/50'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              <span className="h-3.5 w-3.5 rounded-full shrink-0" style={opt.swatchStyle} />
              <span>{opt.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

/** Ultra-minimal top-bar icon dropdown for Home & Product Guide screens */
export const ThemeMenuButton: React.FC<{
  value: ThemePreference;
  onChange: (pref: ThemePreference) => void;
}> = ({ value, onChange }) => {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  const Icon =
    value === 'dark'
      ? Moon
      : value === 'sepia'
        ? BookOpen
        : value === 'auto'
          ? Monitor
          : Sun;

  const curLabel = THEME_OPTIONS.find((o) => o.id === value)?.label || '浅色';

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={`切换界面色调（当前：${curLabel}）`}
        className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:border-blue-300 hover:bg-blue-50/40 hover:text-blue-700 transition-colors"
      >
        <Icon className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{curLabel}</span>
      </button>
      {open && (
        <div className="absolute right-0 mt-1.5 w-52 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl z-40">
          <div className="px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
            外观与护眼色调
          </div>
          {THEME_OPTIONS.map((opt) => {
            const active = value === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => {
                  onChange(opt.id);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-xs transition-colors ${
                  active ? 'bg-blue-50 text-blue-700 font-semibold' : 'text-slate-700 hover:bg-slate-50'
                }`}
              >
                <span className="h-4 w-4 rounded-full shrink-0" style={opt.swatchStyle} />
                <div className="min-w-0">
                  <div className="leading-tight">{opt.label}</div>
                  <div className="text-[10px] text-slate-400 leading-tight mt-0.5">{opt.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
