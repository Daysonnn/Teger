---
name: better-accessibility
description: Accessibility engineering for product interfaces, from focus states and keyboard support to ARIA, forms, and screen readers. Use when building or reviewing UI components, modals, menus, forms, custom widgets, or when the user says "make this accessible" or reports keyboard or screen-reader issues. Triggers on accessibility, a11y, WCAG, aria, focus ring, focus-visible, focus trap, keyboard navigation, tab order, tabindex, screen reader, sr-only, aria-live, alt text, hit area, touch target, prefers-reduced-motion, autoplay, toast duration, skip link, semantic HTML, aria-label, form errors, disabled buttons, "not keyboard accessible".
---

# Accessibility engineering

Accessibility is the floor for interface craft. Use platform defaults over custom rebuilds whenever possible.

## Core Principles

### 1. Native Elements First
Use `<button>` for actions, `<a href>` for navigation. Avoid `<div onClick>`.

### 2. Visible Focus Rings
Style `:focus-visible` to show focus indicators for keyboard users without cluttering mouse clicks. Use at least 2px solid perimeter.

### 3. Keyboard Support
Support Escape for overlays, Arrow keys within composite widgets, Tab for navigation, Enter/Space for activation. Use `tabindex="0"` or `tabindex="-1"`.

### 4. Trap and Restore Focus
Modals set `inert` on background, move focus inside on open, restore focus on close.

### 5. Minimum Hit Area
Aim for 44x44px target sizes in touch contexts and 40x40px on desktop interfaces.

### 6. Labels and Inputs
Every input requires a clear `<label>`. Do not use placeholder as a sole label. Keep inputs at `16px` on mobile to avoid auto-zoom.

### 7. Accessible Names
Icon-only buttons must have descriptive `aria-label`. Decorative icons get `aria-hidden="true"`.

### 8. Reduced Motion
Wrap animations in `@media (prefers-reduced-motion: no-preference)`. Under reduced motion, replace scale/slide with opacity crossfades.
