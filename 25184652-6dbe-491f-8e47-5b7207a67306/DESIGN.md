# AgentOps Operator Console — Design Brief

Local-first governance harness for AI coding runs. The operator (solo engineer)
launches, watches, and judges governed runs that resolve real GitHub issues on
real repos. Brand promise: **honest evidence** — the UI makes truth legible; a
failed run is a first-class outcome, never hidden or spun.

---

## 1. Tokens (six + state colors)

All colors in OKlch. Monochrome-dark surfaces; one signal-green accent.
Semantic state colors are fixed and never decorative:

```css
:root {
  --bg:      oklch(20% 0.02 260);      /* page background, near-black blue-graphite */
  --surface: oklch(25% 0.022 260);     /* cards, panels, raised areas */
  --fg:      oklch(93% 0.005 250);     /* primary text */
  --muted:   oklch(64% 0.015 255);     /* secondary text, captions */
  --border:  oklch(32% 0.02 260);      /* hairlines, dividers */

  --accent:  oklch(80% 0.19 150);       /* signal green — live, primary CTA */

  /* semantic states (fixed mapping, AA on --bg) */
  --ok:      oklch(78% 0.17 150);      /* completed */
  --fail:    oklch(66% 0.20 25);       /* failed */
  --warn:    oklch(80% 0.15 85);       /* blocked / inconclusive */
  --info:    oklch(75% 0.12 240);      /* informational links, running stage */

  /* derived — via color-mix only */
  --accent-soft: color-mix(in oklch, var(--accent) 15%, transparent);
}
```

## 2. Typography

- **Display:** `Space Grotesk` (fallback: system-ui sans). Used for screen
  titles, KPI numerals, showcase headline. Tight tracking, no italic.
- **Body/UI:** `Inter` (fallback: system-ui). 13–14px UI text, 12px meta.
- **Mono (mandatory for code/test ids/commands/hashes):**
  `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace` with
  `font-variant-numeric: tabular-nums`.
- Data-dense console: 12px floor for tabular meta, 13px body, 14px section
  heads, nothing below 12px.

## 3. Layout system

- **App shell with fixed left sidebar** (240px): brand → primary nav (Runs,
  New Run, Task Specs) → worker status → harness identity footer.
- Top bar per screen: breadcrumb, search/omnibar placeholder area, live
  indicator, showcase toggle.
- Content column max 1160px; tables full-bleed within content; 8-pt spacing
  grid; hairline `--border` dividers, `--surface` panels, 8px radii.
- Desktop-first, min-width 1280px; no horizontal scroll at ≥1280.
- Density: compact, data-dense. Rows ~40px; chrome minimal; no decoration that
  does not encode state.

## 4. Rules of the visual language (observed)

1. **Status colors are semantic, never decorative.** Green=completed,
   red=failed, amber=blocked/inconclusive. State color appears only on status
   chips, stage dots, exit-code badges, and KPI delta — never as a wash.
2. **Every claim links to its evidence.** Test rows link to logs, findings to
   citations, risk badge to its factor list, stage dot to its event bundle.
   Anything unverifiable is labeled `inconclusive`, distinct from failure.
3. **Monospace is a truth signal.** Commit hashes, commands, test ids, paths,
   exit codes always mono + tabular numerals.
4. **One flourish: the pipeline stage timeline.** Plan → Dispatch → Enforce →
   Validate → Retry → Report as a lit track with elapsed times; it is the one
   distinctive composition, reused on runs-list (micro) and run detail (hero).
   Showcase mode reuses the same data at presentation grade — same truth, larger type.
5. **Honest empty/loading/error states.** No skeleton theater: empty states
   name the exact condition and the next action; error states carry the real
   stderr; loading states keep last-known content with a live indicator.

## 5. Region state coverage

Every data region implements empty / loading / error variants (see
`CRITIQUE.md`). Failure payloads come from real `.agentops/runs/` records.

## 6. Accessibility

- Contrast AA minimum against `--bg`/`--surface` for all text; state colors
  chosen at ≥4.5:1 for text, ≥3:1 for large text/icons on dark surfaces.
- Focus-visible rings: 2px `--accent` offset ring on every interactive element.
- Long-stretch readability: 13px UI text at 1.5 line-height, no pure white.
- Touch/click targets ≥24px inline for dense tables (operator desktop, mouse);
  all primary controls ≥32px height.
