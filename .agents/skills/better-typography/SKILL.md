---
name: better-typography
description: Web typography from choosing fonts to spacing, wrapping and accessibility. Use when picking or pairing typefaces, configuring variable fonts or OpenType features, setting up a type scale, checking heading hierarchy, styling text in components, truncating text, styling underlines, selection, placeholders or carets, or reviewing frontend code for typography. Triggers on typography, fonts, font formats, woff2, variable fonts, font-weight, opentype, font-feature-settings, letter-spacing, line-height, type scale, heading hierarchy, heading levels, tabular numbers, text-wrap, truncation, line clamp, underlines, text-decoration, text selection, iOS input zoom, font smoothing, text contrast, measure, line length, text-box, smart punctuation, drop cap.
---

# Great typography

Good typography is mostly restraint. A sensible scale, comfortable spacing and enough contrast beat any clever effect. Apply these principles when building or reviewing anything with text in it.

## Core Principles

### 1. Serve the Right Format
Use `.woff2` (Brotli compression, broadly supported) on the web.

### 2. Properties Over Raw Tags
Use CSS high-level properties (`font-weight: 650`, `font-variant-numeric: tabular-nums`) over raw feature tags.

### 3. Load Intended Weights and Styles
Prefer loading the faces the design actually uses. Set `font-synthesis: none` carefully.

### 4. Fewer Fonts, Sizes and Weights
Rarely use more than three fonts. Below `18px`, stay at weight `400`+. Weights under `300` are display-only (`28px`+).

### 5. Type Scale with Semantic Names
Define a small set of sizes named by use (`text-body-sm`).

### 6. Heading Sizes Descend with Level
Map heading levels to descending steps of the type scale.

### 7. Line-Height by Role
Headings tighter (~`1.1`). Body copy `1.5` to `1.6`. Prefer unitless values.

### 8. Letter-Spacing by Size
Negative letter-spacing for large headings, slightly positive for small uppercase labels, neutral for body.

### 9. Cap the Measure
Cap long-form text around 60–75 characters per line (`max-w-xl` / `65ch`).

### 10. Wrap Deliberately
Use `text-wrap: balance` on headings, `text-wrap: pretty` on descriptions, `overflow-wrap: break-word` on long links/IDs.

### 11. Tabular Numbers on Changing Values
Apply `font-variant-numeric: tabular-nums` to timers, counters, prices.

### 12. Truncate Without Losing Content
Single line: `text-overflow: ellipsis` + `overflow: hidden` + `white-space: nowrap`. Provide tooltips for full values.

### 13. Write Copy Naturally, Style with CSS
Store text in natural case, use `text-transform` for display formatting.

### 14. Underlines from the Font
Use `text-underline-position: from-font` and `text-decoration-thickness: from-font`.

### 15. Inputs at 16px on Mobile
Keep input text at `16px` on mobile viewports (`text-base sm:text-sm`) to prevent iOS Safari auto-zoom.

### 16. Font Smoothing on Root
Apply `antialiased` (`-webkit-font-smoothing: antialiased`) at root layout on macOS.
