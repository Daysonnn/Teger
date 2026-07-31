---
name: better-ui
description: Design engineering principles for making interfaces feel polished. Use when building UI components, reviewing frontend code, implementing animations, hover states, shadows, borders, micro-interactions, enter/exit animations, choosing or reviewing icons, or any visual detail work. Triggers on UI polish, design details, "make it feel better", "feels off", stagger animations, border radius, optical alignment, image outlines, box shadows, icons, icon stroke weight, icon states, motion restraint.
---

# Details that make interfaces feel better

Great interfaces rarely come from a single thing. It's usually a collection of small details that compound into a great experience. Apply these principles when building or reviewing UI code.

When reviewing, slow the interface down: replay motion at 10% speed in the browser's Animations panel and walk every state: hover, focus, active, loading, empty. What feels off at 10% speed is what's subtly wrong at full speed.

Preserve the project's component library, tokens, and density. Match its established motion language except where a principle below prescribes an exact interaction pattern.

Typography (text wrapping, font rendering, tabular numbers, spacing) is covered by the `better-typography` skill; use that for anything text-related. Accessibility (hit areas, focus states, keyboard support, ARIA, reduced motion) is covered by the `better-accessibility` skill. Layout structure (grouping, spacing between sections, breakpoints, spatial RTL) is covered by the `better-layout` skill.

## Core Principles

### 1. Concentric Border Radius
Outer radius = inner radius + padding. Mismatched radii on nested elements is the most common thing that makes interfaces feel off.

### 2. Optical Over Geometric Alignment
When geometric centering looks off, align optically. Buttons with icons, play triangles, and asymmetric icons all need manual adjustment.

### 3. Shadows for Elevation, Borders for Structure
For buttons, cards, and containers whose border exists only to create depth, prefer layered transparent `box-shadow` values. Keep borders that communicate structure or state: dividers, layout separators, and selected or focus states.

### 4. Interruptible Animations
Use CSS transitions for interactive state changes: they can be interrupted mid-animation. Reserve keyframes for staged sequences that run once.

### 5. Split and Stagger Enter Animations
For an infrequent staged entrance where sequence helps communicate hierarchy, break content into semantic chunks and stagger them by ~100ms instead of animating one container. Do not stagger routine, high-frequency interactions.

### 6. Subtle Exit Animations
Use a small fixed `translateY` instead of full height. Exits should be softer than enters. Use `ease-out` for both enter and exit transitions.

### 7. Contextual Icon Animations
Animate icons with `opacity`, `scale`, and `blur` instead of toggling visibility. Use scale from `0.25` to `1`, opacity from `0` to `1`, blur from `4px` to `0px`.

### 8. Image Outlines
Add a subtle `1px` outline with low opacity to images for consistent depth (`oklch(0 0 0 / 0.1)` in light mode, `oklch(1 0 0 / 0.1)` in dark mode).

### 9. Scale on Press
A subtle `scale(0.96)` on click gives buttons tactile feedback. Always use `0.96`. Never use a value smaller than `0.95`.

### 10. Skip Animation on Page Load
Use `initial={false}` on `AnimatePresence` to prevent enter animations on first render.

### 11. Never Use `transition: all`
Always specify exact properties: `transition-property: scale, opacity`.

### 12. Use `will-change` Sparingly
Only for `transform`, `opacity`, `filter`. Never use `will-change: all`.

### 13. Match Icon Stroke to Text Weight
`1.5px` stroke beside regular (400) text, `2px` beside semibold (600). One stroke weight per icon set.

### 14. One SVG, Recolored per State
Icons use `currentColor` and get their states from CSS color and opacity.

### 15. Motion Restraint
No custom animation on high-frequency interactions. Every animated state change also needs a static cue.
