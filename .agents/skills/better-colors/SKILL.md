---
name: better-colors
description: OKLCH color space and color usage for web projects. Convert hex/rgb/hsl to oklch, generate palettes, check contrast, handle gamut boundaries, theme with Tailwind v4, and apply color with meaning. Triggers on oklch, color conversion, palette generation, contrast ratio, gamut, display p3, design tokens, semantic color tokens, hue drift, chroma, dark mode colors, accent color, color meaning, light and dark appearance, increased contrast.
---

# OKLCH Colors

OKLCH is a perceptually uniform color space where lightness, chroma, and hue are useful design controls. Use it when creating or updating color systems or palette work.

## Core Principles

### 1. Perceptual Uniformity & Stable Hue
`oklch(L C H)` provides equal perceptual brightness steps and stable hue across lightness shifts.

### 2. Format Syntax
`oklch(L C H)` or `oklch(L C H / alpha)`. Use 3 decimal places for L and C.

### 3. Contrast & Gamut Baseline
- Light/dark boundary: L > 0.73 = light background -> dark text.
- WCAG 2 AA normal text: 4.5:1, AAA: 7:1.
- APCA body text: |Lc| >= 75 minimum.

### 4. Semantic Tokens & Meaning
One color, one meaning. Define semantic role tokens (primary, background, surface, danger, accent) instead of hardcoding raw color values across UI elements.
