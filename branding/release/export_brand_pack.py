"""Export the complete release-ready Brand & Promo Asset Pack for 对稿 · PaperDiff (S1 · split-frame).

Outputs into branding/release/:
  - Vectors (.svg):
      logo-light.svg, logo-dark.svg, logo-mono-light.svg, logo-mono-dark.svg
      app-icon-ink.svg, app-icon-elev.svg, app-icon-paper.svg
      favicon.svg
      lockup-light.svg, lockup-dark.svg
  - High-DPI Rasters (.png via Headless Chrome):
      app-icon-1024.png, app-icon-512.png, app-icon-256.png, app-icon-128.png
      app-icon-dark-1024.png, app-icon-paper-1024.png
      apple-touch-icon-180.png (also synced to paperdiff/frontend/public/apple-touch-icon.png)
      promo-banner-light.png, promo-banner-dark.png (1280x640 @ 2x)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAND_V2 = ROOT / "branding" / "v2"
REL = Path(__file__).resolve().parent
TMP = REL / "_render_tmp"
PUBLIC = ROOT / "paperdiff" / "frontend" / "public"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

sys.path.insert(0, str(BRAND_V2))
import build_mono as bm  # noqa: E402


def render_html_to_png(html_path: Path, png_path: Path, w: int, h: int, dpr: int = 1) -> None:
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            f"--force-device-scale-factor={dpr}",
            f"--window-size={w},{h}",
            "--default-background-color=00000000",
            f"--screenshot={png_path}",
            str(html_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def lockup_svg(theme: str) -> str:
    is_light = theme == "light"
    ink = bm.INK_LIGHT if is_light else bm.INK_DARK
    blue = bm.BLUE_LIGHT if is_light else bm.BLUE_DARK
    sub = "#57606A" if is_light else "#8B949E"
    mode = "ink" if is_light else "elev"
    tile_fill = bm.TILE_INK if is_light else bm.TILE_ELEV
    tile_ring = "" if is_light else ' stroke="#3B434F" stroke-width="1.0"'
    inner = bm.glyph_shapes("s1", "dark", mono=False, on_tile=mode)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 96" width="420" height="96">
  <g transform="translate(12 12) scale(3)">
    <rect x="0.5" y="0.5" width="23" height="23" rx="5.4" fill="{tile_fill}"{tile_ring}/>
    <g transform="translate(12 12) scale(0.68) translate(-12 -12)">{inner}</g>
  </g>
  <text x="104" y="48" font-family="-apple-system,'SF Pro Display','Helvetica Neue',sans-serif" font-size="34" font-weight="800" letter-spacing="-0.6" fill="{ink}">Paper<tspan fill="{blue}">Diff</tspan></text>
  <line x1="274" y1="22" x2="274" y2="52" stroke="{sub}" stroke-width="1.6" opacity="0.45"/>
  <text x="292" y="48" font-family="'STSongti-SC-Bold','Songti SC',serif" font-size="32" font-weight="700" letter-spacing="2" fill="{ink}">对稿</text>
  <text x="105" y="76" font-family="-apple-system,'SF Pro Text','PingFang SC',sans-serif" font-size="13.5" font-weight="500" letter-spacing="0.6" fill="{sub}">本地学术文稿阅读 · 版本比对 · 事实守恒审计</text>
</svg>
"""


def promo_banner_html(theme: str) -> str:
    is_light = theme == "light"
    bg = "#FFFFFF" if is_light else "#0D1117"
    card_bg = "#F8FAFC" if is_light else "#161B22"
    border = "#E5E7EB" if is_light else "#262C36"
    ink = bm.INK_LIGHT if is_light else bm.INK_DARK
    sub = "#57606A" if is_light else "#8B949E"
    blue = bm.BLUE_LIGHT if is_light else bm.BLUE_DARK
    icon_file = "app-icon-ink.svg"
    icon_style = "" if is_light else "border-radius:52px;box-shadow:0 0 0 1.5px #3B434F;"
    pill_bg = "#EFF6FF" if is_light else "rgba(59,130,246,0.14)"
    pill_bd = "#BFDBFE" if is_light else "rgba(59,130,246,0.35)"
    pill_fg = "#1D4ED8" if is_light else "#93C5FD"
    tags = ["单稿纯净阅读", "左右对照 / 行内融合", "三线表数值 Δ 审计", "AI 腔标注", "LaTeX 无损回写", "Word 原生修订"]
    tag_html = "".join(f'<span class="tag">{t}</span>' for t in tags)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/><style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; width: 1280px; height: 520px; background: {bg};
    font-family: -apple-system, 'SF Pro Display', 'SF Pro Text', 'PingFang SC', sans-serif;
    display: flex; align-items: center; justify-content: center;
    -webkit-font-smoothing: antialiased;
  }}
  .frame {{
    width: 1180px; height: 420px; border-radius: 28px;
    background: {card_bg}; border: 1.5px solid {border};
    padding: 56px 64px; display: flex; align-items: center; justify-content: space-between; gap: 48px;
  }}
  .left {{ flex: 1; min-width: 0; }}
  .eyebrow {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 999px;
    background: {pill_bg}; border: 1px solid {pill_bd}; color: {pill_fg};
    font-size: 13px; font-weight: 700; letter-spacing: 0.04em;
  }}
  .wm {{
    margin-top: 22px; font-size: 62px; font-weight: 800; letter-spacing: -0.025em;
    color: {ink}; display: flex; align-items: center; line-height: 1;
  }}
  .vbar {{ display: inline-block; width: 2px; height: 50px; background: {sub}; opacity: 0.35; margin: 0 24px; }}
  .zh {{ font-family: 'STSongti-SC-Bold', 'Songti SC', serif; font-size: 58px; letter-spacing: 0.06em; }}
  .sub {{ margin-top: 18px; font-size: 19.5px; line-height: 1.55; color: {sub}; white-space: nowrap; }}
  .tags {{ margin-top: 26px; display: flex; flex-wrap: nowrap; gap: 8px; }}
  .tag {{
    padding: 6px 11px; border-radius: 9px; font-size: 12.5px; font-weight: 600; white-space: nowrap;
    background: {bg}; border: 1px solid {border}; color: {ink};
  }}
  .right {{ flex-shrink: 0; display: flex; flex-direction: column; align-items: center; gap: 14px; }}
  .cap {{ font-family: 'SF Mono', Menlo, monospace; font-size: 12px; color: {sub}; letter-spacing: 0.06em; }}
</style></head><body>
  <div class="frame">
    <div class="left">
      <div class="eyebrow">LOCAL-FIRST ACADEMIC WORKBENCH · 100% 本地零上传</div>
      <div class="wm">Paper<span style="color:{blue}">Diff</span><span class="vbar"></span><span class="zh">对稿</span></div>
      <div class="sub">面向 AI 科研写作的学术文稿纯净阅读、版本比对与无损回写工作台</div>
      <div class="tags">{tag_html}</div>
    </div>
    <div class="right">
      <img src="../{icon_file}" width="232" height="232" style="{icon_style}"/>
      <div class="cap">SPLIT SHEET · {'LIGHT' if is_light else 'DARK'} EDITION</div>
    </div>
  </div>
</body></html>"""


def svg_square_html(svg_rel: str, size: int, inset: int = 0) -> str:
    inner = size - inset * 2
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/><style>
  html, body {{ margin: 0; padding: 0; width: {size}px; height: {size}px; background: transparent; overflow: hidden; display: flex; align-items: center; justify-content: center; }}
  img {{ display: block; width: {inner}px; height: {inner}px; }}
</style></head><body><img src="../{svg_rel}"/></body></html>"""


def main() -> None:
    REL.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)

    # 1. Generate core SVGs from build_mono (S1 · split-frame)
    (REL / "logo-light.svg").write_text(bm.glyph_svg("s1", "light", mono=False), encoding="utf-8")
    (REL / "logo-dark.svg").write_text(bm.glyph_svg("s1", "dark", mono=False), encoding="utf-8")
    (REL / "logo-mono-light.svg").write_text(bm.glyph_svg("s1", "light", mono=True), encoding="utf-8")
    (REL / "logo-mono-dark.svg").write_text(bm.glyph_svg("s1", "dark", mono=True), encoding="utf-8")
    (REL / "app-icon-ink.svg").write_text(bm.app_icon_svg("s1", "ink"), encoding="utf-8")
    (REL / "app-icon-elev.svg").write_text(bm.app_icon_svg("s1", "elev"), encoding="utf-8")
    (REL / "app-icon-paper.svg").write_text(bm.app_icon_svg("s1", "paper"), encoding="utf-8")
    (REL / "favicon.svg").write_text(bm.favicon_svg("s1"), encoding="utf-8")
    (REL / "lockup-light.svg").write_text(lockup_svg("light"), encoding="utf-8")
    (REL / "lockup-dark.svg").write_text(lockup_svg("dark"), encoding="utf-8")

    # 2. Render multi-resolution App Icon PNGs (1024/512/256/128/180)
    for sz in (1024, 512, 256, 128):
        h = TMP / f"icon_{sz}.html"
        h.write_text(svg_square_html("app-icon-ink.svg", sz), encoding="utf-8")
        render_html_to_png(h, REL / f"app-icon-{sz}.png", sz, sz, dpr=1)

    for name, src_svg, sz, inset in [
        ("app-icon-macos-1024.png", "app-icon-ink.svg", 1024, 100),
        ("app-icon-dark-1024.png", "app-icon-elev.svg", 1024, 0),
        ("app-icon-paper-1024.png", "app-icon-paper.svg", 1024, 0),
        ("apple-touch-icon-180.png", "app-icon-ink.svg", 180, 0),
    ]:
        h = TMP / f"{name}.html"
        h.write_text(svg_square_html(src_svg, sz, inset=inset), encoding="utf-8")
        render_html_to_png(h, REL / name, sz, sz, dpr=1)

    # Sync apple-touch-icon & favicon to frontend/public/
    shutil.copy2(REL / "apple-touch-icon-180.png", PUBLIC / "apple-touch-icon.png")
    shutil.copy2(REL / "favicon.svg", PUBLIC / "favicon.svg")

    # 3. Render Promo Banners (Light & Dark, 1280x520 @ 2x)
    for th in ("light", "dark"):
        h = TMP / f"promo_{th}.html"
        h.write_text(promo_banner_html(th), encoding="utf-8")
        render_html_to_png(h, REL / f"promo-banner-{th}.png", 1280, 520, dpr=2)

    shutil.rmtree(TMP, ignore_errors=True)
    print("Exported complete release brand asset pack to", REL)


if __name__ == "__main__":
    main()
