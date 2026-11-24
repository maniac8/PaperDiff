import React from 'react';

/**
 * 对稿 · PaperDiff — 100% Original "Split Sheet (对页比对)" Monochrome Dual-Tone Brand System.
 * Faithfully evolves Concept 3 ("方案 3 · 对页": two offset manuscript pages with 4 left-aligned
 * ragged academic text lines, left = old draft lowered, right = new draft lifted, 2.4px center seam)
 * into a flat monochrome dual-theme system (Light / Sepia / Dark auto-switching via --pd-brand-*).
 */

export type BrandConceptId = 's1' | 's2' | 's3' | 's4';
export const DEFAULT_BRAND_CONCEPT: BrandConceptId = 's1';

const L_X = 2.2;
const L_Y = 5.8;
const R_X = 13.2;
const R_Y = 2.8;
const PW = 8.6;
const PH = 15.4;
const PR = 1.6;

function RaggedFourLines({
  x,
  y,
  ctxColor,
  hiColor,
  pad = 1.65,
  hiH = 1.9,
}: {
  x: number;
  y: number;
  ctxColor: string;
  hiColor: string;
  pad?: number;
  hiH?: number;
}) {
  const lx = x + pad;
  const maxW = PW - pad * 2;
  return (
    <>
      <rect x={lx} y={y + 2.65} width={maxW * 0.7} height={1.3} rx={0.65} fill={ctxColor} />
      <rect x={lx} y={y + 5.15} width={maxW * 0.84} height={1.3} rx={0.65} fill={ctxColor} />
      <rect x={lx} y={y + 7.75} width={maxW} height={hiH} rx={hiH / 2} fill={hiColor} />
      <rect x={lx} y={y + 11.15} width={maxW * 0.58} height={1.3} rx={0.65} fill={ctxColor} />
    </>
  );
}

/** Bare glyph: crisp architectural Split-Sheet pages directly on Light / Sepia / Dark surfaces. */
export const BrandMark: React.FC<{
  size?: number;
  className?: string;
  title?: string;
  concept?: BrandConceptId;
}> = ({ size = 20, className, title = '对稿 PaperDiff', concept = DEFAULT_BRAND_CONCEPT }) => {
  const sw = 1.45;
  const isSemantic = concept === 's4';
  const isDuotone = concept === 's2';
  const isLayered = concept === 's3';

  return (
    <svg
      viewBox="1.6 2.5 20.8 19.0"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label={title}
    >
      {isDuotone ? (
        <>
          <rect
            x={L_X + 0.82}
            y={L_Y + 0.82}
            width={PW - 1.65}
            height={PH - 1.65}
            rx={PR - 0.2}
            fill="none"
            stroke="var(--pd-brand-ink)"
            strokeWidth={1.65}
          />
          <rect x={L_X + 1.85} y={L_Y + 3.4} width={3.63} height={1.65} rx={0.82} fill="var(--pd-brand-muted, #8C959F)" />
          <rect x={L_X + 1.85} y={L_Y + 6.9} width={4.9} height={1.95} rx={0.97} fill="var(--pd-brand-ink)" />
          <rect x={L_X + 1.85} y={L_Y + 10.7} width={2.84} height={1.65} rx={0.82} fill="var(--pd-brand-muted, #8C959F)" />
          <rect x={R_X} y={R_Y} width={PW} height={PH} rx={PR} fill="var(--pd-brand-accent-on-paper, #2563EB)" />
          <rect x={R_X + 1.5} y={R_Y + 3.4} width={4.14} height={1.65} rx={0.82} fill="#DBEAFE" />
          <rect x={R_X + 1.5} y={R_Y + 6.9} width={5.6} height={1.95} rx={0.97} fill="#FFFFFF" />
          <rect x={R_X + 1.5} y={R_Y + 10.7} width={3.25} height={1.65} rx={0.82} fill="#DBEAFE" />
        </>
      ) : isLayered ? (
        <>
          <rect x={L_X} y={L_Y} width={PW} height={PH} rx={PR} fill="var(--pd-brand-muted-sheet, #C9D1DB)" />
          <RaggedFourLines
            x={L_X}
            y={L_Y}
            ctxColor="var(--pd-brand-muted, #6E7681)"
            hiColor="var(--pd-brand-ink)"
            pad={1.4}
            hiH={1.95}
          />
          <rect x={R_X} y={R_Y} width={PW} height={PH} rx={PR} fill="var(--pd-brand-ink)" />
          <RaggedFourLines
            x={R_X}
            y={R_Y}
            ctxColor="var(--pd-brand-muted, #8C959F)"
            hiColor="var(--pd-brand-accent-on-ink, #3B82F6)"
            pad={1.4}
            hiH={1.95}
          />
        </>
      ) : (
        <>
          <rect
            x={L_X + sw / 2}
            y={L_Y + sw / 2}
            width={PW - sw}
            height={PH - sw}
            rx={PR - 0.2}
            fill="var(--pd-surface, #FFFFFF)"
            stroke="var(--pd-brand-ink)"
            strokeWidth={sw}
          />
          <RaggedFourLines
            x={L_X}
            y={L_Y}
            ctxColor="var(--pd-brand-muted, #8C959F)"
            hiColor={isSemantic ? '#DC2626' : 'var(--pd-brand-ink)'}
            pad={1.7}
            hiH={1.85}
          />
          <rect
            x={R_X + sw / 2}
            y={R_Y + sw / 2}
            width={PW - sw}
            height={PH - sw}
            rx={PR - 0.2}
            fill="var(--pd-surface, #FFFFFF)"
            stroke="var(--pd-brand-ink)"
            strokeWidth={sw}
          />
          <RaggedFourLines
            x={R_X}
            y={R_Y}
            ctxColor="var(--pd-brand-muted, #8C959F)"
            hiColor={isSemantic ? '#15803D' : 'var(--pd-brand-accent-on-paper, #2563EB)'}
            pad={1.7}
            hiH={1.85}
          />
        </>
      )}
    </svg>
  );
};

/** App-icon tile: matte obsidian plate (#0D1117) on Light / elevated charcoal (#161B22) on Dark
 *  framing two crisp snow-white Split-Sheet pages — faithful monochrome evolution of Concept 3. */
export const BrandAppIcon: React.FC<{
  size?: number;
  className?: string;
  title?: string;
  concept?: BrandConceptId;
}> = ({ size = 32, className, title = '对稿 PaperDiff', concept = DEFAULT_BRAND_CONCEPT }) => {
  const isSemantic = concept === 's4';
  const isDuotone = concept === 's2';
  const isLayered = concept === 's3';

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-label={title}
    >
      <rect
        x={0.5}
        y={0.5}
        width={23.0}
        height={23.0}
        rx={5.4}
        fill="var(--pd-brand-tile, #0D1117)"
        stroke="var(--pd-brand-tile-ring, transparent)"
        strokeWidth={1.0}
      />
      <g transform="translate(12 12) scale(0.68) translate(-12 -12)">
        {isDuotone ? (
          <>
            <rect
              x={L_X + 0.82}
              y={L_Y + 0.82}
              width={PW - 1.65}
              height={PH - 1.65}
              rx={PR - 0.2}
              fill="none"
              stroke="#F3F6FA"
              strokeWidth={1.65}
            />
            <rect x={L_X + 1.85} y={L_Y + 3.4} width={3.63} height={1.65} rx={0.82} fill="#6E7681" />
            <rect x={L_X + 1.85} y={L_Y + 6.9} width={4.9} height={1.95} rx={0.97} fill="#F3F6FA" />
            <rect x={L_X + 1.85} y={L_Y + 10.7} width={2.84} height={1.65} rx={0.82} fill="#6E7681" />
            <rect x={R_X} y={R_Y} width={PW} height={PH} rx={PR} fill="#3B82F6" />
            <rect x={R_X + 1.5} y={R_Y + 3.4} width={4.14} height={1.65} rx={0.82} fill="#DBEAFE" />
            <rect x={R_X + 1.5} y={R_Y + 6.9} width={5.6} height={1.95} rx={0.97} fill="#FFFFFF" />
            <rect x={R_X + 1.5} y={R_Y + 10.7} width={3.25} height={1.65} rx={0.82} fill="#DBEAFE" />
          </>
        ) : isLayered ? (
          <>
            <rect x={L_X} y={L_Y} width={PW} height={PH} rx={PR} fill="#343C4A" />
            <RaggedFourLines x={L_X} y={L_Y} ctxColor="#8B949E" hiColor="#E2E8F0" pad={1.4} hiH={1.95} />
            <rect x={R_X} y={R_Y} width={PW} height={PH} rx={PR} fill="#F3F6FA" />
            <RaggedFourLines x={R_X} y={R_Y} ctxColor="#8C959F" hiColor="#2563EB" pad={1.4} hiH={1.95} />
          </>
        ) : (
          <>
            <rect x={L_X} y={L_Y} width={PW} height={PH} rx={PR} fill="#FFFFFF" />
            <RaggedFourLines
              x={L_X}
              y={L_Y}
              ctxColor="#8C959F"
              hiColor={isSemantic ? '#DC2626' : '#0D1117'}
              pad={1.35}
              hiH={2.0}
            />
            <rect x={R_X} y={R_Y} width={PW} height={PH} rx={PR} fill="#FFFFFF" />
            <RaggedFourLines
              x={R_X}
              y={R_Y}
              ctxColor="#8C959F"
              hiColor={isSemantic ? '#15803D' : '#2563EB'}
              pad={1.35}
              hiH={2.0}
            />
          </>
        )}
      </g>
    </svg>
  );
};

/** Horizontal lockup: app icon + "PaperDiff | 对稿" wordmark (+ optional tagline). */
export const BrandLockup: React.FC<{
  subtitle?: string;
  compact?: boolean;
  concept?: BrandConceptId;
}> = ({ subtitle, compact, concept = DEFAULT_BRAND_CONCEPT }) => (
  <div className="flex items-center gap-2.5">
    <BrandAppIcon size={compact ? 28 : 32} concept={concept} />
    <div className="leading-none">
      <div className="flex items-center text-[15px] font-bold tracking-tight text-slate-900">
        Paper<span style={{ color: 'var(--pd-brand-accent-on-paper, #2563EB)' }}>Diff</span>
        <span className="mx-2 inline-block h-3.5 w-px bg-slate-300" />
        <span className="font-brand-zh text-[14px] tracking-[0.06em]">对稿</span>
      </div>
      {subtitle && <div className="mt-1 text-[11px] text-slate-400">{subtitle}</div>}
    </div>
  </div>
);
