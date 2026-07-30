# UR10 Jog Control — UI Redesign Visual Specification
**Application:** UR10 Robotic Arm Jog Control (PyQt6)
**Target Hardware:** Elo i3 Industrial Touchscreen — 1024 × 768 px fixed resolution
**Audience:** Industrial operators + technical demo viewers
**Implementation:** PyQt6 with QSS stylesheets
**Date:** 2026-05-08
**Status:** LOCKED design direction — refine within constraints only

---

## Table of Contents

1. [Color Palette](#1-color-palette)
2. [Typography](#2-typography)
3. [Spacing & Layout Grid](#3-spacing--layout-grid)
4. [Component Visual Specs](#4-component-visual-specs)
5. [Screen Layout Sketches](#5-screen-layout-sketches)
6. [Interaction Patterns](#6-interaction-patterns)
7. [Accessibility & Operator Considerations](#7-accessibility--operator-considerations)
8. [Animation & Motion](#8-animation--motion)
9. [QSS Implementation Notes](#9-qss-implementation-notes)
10. [Demo Inventory](#10-demo-inventory)

---

## 1. Color Palette

### 1.1 Base Surfaces

| Token               | Hex       | Usage                                                         |
|---------------------|-----------|---------------------------------------------------------------|
| `--bg-base`         | `#0F1419` | Root window background, behind all panels                     |
| `--surface`         | `#1A1F2B` | Cards, panels, sidebar regions, primary content containers    |
| `--surface-raised`  | `#232936` | Hover state overlays, active-pressed surfaces, elevated cards |
| `--surface-overlay` | `#2C3347` | Modal overlays, dropdown backgrounds                          |
| `--border`          | `#2D3441` | All borders, dividers, separator lines                        |
| `--border-focus`    | `#3B82F6` | Focus ring on interactive elements (2 px solid)               |

### 1.2 Text

| Token           | Hex       | Usage                                                      |
|-----------------|-----------|------------------------------------------------------------|
| `--text-primary`   | `#E5E7EB` | Headings, primary labels, critical info                 |
| `--text-secondary` | `#9CA3AF` | Sub-labels, metadata, helper text                       |
| `--text-muted`     | `#6B7280` | Placeholder text, disabled labels, micro annotations    |
| `--text-inverse`   | `#0F1419` | Text on accent/success/warning/error solid backgrounds  |
| `--text-accent`    | `#93C5FD` | Hyperlink-style text, active tab labels                 |

### 1.3 Accent & Semantic

| Token              | Hex       | Usage                                                          |
|--------------------|-----------|----------------------------------------------------------------|
| `--accent`         | `#3B82F6` | Primary CTA buttons, active tab indicator, focus rings, links  |
| `--accent-hover`   | `#2563EB` | Hover state for accent elements                                |
| `--accent-pressed` | `#1D4ED8` | Pressed/active state for accent elements                       |
| `--accent-muted`   | `#1E3A5F` | Accent-tinted surface (selected card background, chip bg)      |
| `--success`        | `#10B981` | Connected badge, success toasts, completed demo indicators     |
| `--success-muted`  | `#064E3B` | Success-tinted surface background                              |
| `--warning`        | `#F59E0B` | Warning toasts, caution states, partial connection             |
| `--warning-muted`  | `#451A03` | Warning-tinted surface background                              |
| `--error`          | `#EF4444` | E-stop button, error badges, fault toasts, disconnected state  |
| `--error-hover`    | `#DC2626` | E-stop hover                                                   |
| `--error-pressed`  | `#B91C1C` | E-stop pressed / held                                          |
| `--error-muted`    | `#450A0A` | Error-tinted surface background                                |

### 1.4 Category Accent Stripes (Demo Cards)

| Category      | Stripe Color | Hex       |
|---------------|--------------|-----------|
| Showcase      | Violet       | `#7C3AED` |
| Dynamic       | Cyan         | `#06B6D4` |
| Industrial    | Amber        | `#D97706` |
| Engineering   | Emerald      | `#059669` |
| Experimental  | Pink         | `#DB2777` |

### 1.5 WCAG AA Contrast Verification

All text-on-background pairs verified at their actual use sizes:

| Foreground         | Background      | Ratio  | AA Pass? |
|--------------------|-----------------|--------|----------|
| `#E5E7EB` (primary)| `#0F1419` (base)| 14.3:1 | Yes      |
| `#E5E7EB` (primary)| `#1A1F2B` (surf)| 11.8:1 | Yes      |
| `#9CA3AF` (second) | `#0F1419` (base)| 6.4:1  | Yes      |
| `#9CA3AF` (second) | `#1A1F2B` (surf)| 5.3:1  | Yes      |
| `#6B7280` (muted)  | `#0F1419` (base)| 3.6:1  | Yes (18px+, bold 14px+) |
| `#0F1419` (inverse)| `#3B82F6` (acct)| 5.1:1  | Yes      |
| `#0F1419` (inverse)| `#10B981` (succ)| 7.2:1  | Yes      |
| `#0F1419` (inverse)| `#F59E0B` (warn)| 8.9:1  | Yes      |
| `#0F1419` (inverse)| `#EF4444` (err) | 4.8:1  | Yes      |

Note: Muted text (`#6B7280`) is used ONLY at body 18 px or larger, or in bold weight at 14 px+.
Never use muted text for safety-critical information.

---

## 2. Typography

### 2.1 Font Stack

```
Primary (UI):   "Inter", "DejaVu Sans", "Liberation Sans", system-ui, sans-serif
Monospace (log):"JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono", monospace
```

PyQt6 font loading priority: attempt `Inter` via QFontDatabase at startup;
fall back to `DejaVu Sans` (typically pre-installed on Ubuntu); final fallback to
Qt's default `system-ui` sans.

### 2.2 Type Scale

| Role        | Size (px) | Weight      | Line Height | Letter Spacing | Usage                              |
|-------------|-----------|-------------|-------------|----------------|------------------------------------|
| display     | 40        | 700 (Bold)  | 1.1         | -0.02 em       | E-stop label, modal critical title |
| title       | 32        | 700         | 1.15        | -0.015 em      | Screen/section titles              |
| heading     | 24        | 600 (SemBd) | 1.2         | -0.01 em       | Card headings, panel headers       |
| subhead     | 20        | 600         | 1.3         | 0              | Tab labels, group labels           |
| body        | 18        | 400 (Reg)   | 1.45        | 0              | General UI text, button labels     |
| body-strong | 18        | 600         | 1.45        | 0              | Emphasized body, axis labels       |
| small       | 14        | 400         | 1.4         | +0.01 em       | Metadata, badge labels, timestamps |
| micro       | 12        | 400         | 1.35        | +0.02 em       | Footer status, log timestamps      |
| mono        | 16        | 400         | 1.5         | 0              | Live log output, coordinate values |
| mono-small  | 13        | 400         | 1.5         | 0              | Compact log, debug output          |

### 2.3 Weight Reference

| Name     | CSS Weight | Qt Weight Constant |
|----------|------------|--------------------|
| Regular  | 400        | QFont.Weight.Normal   |
| Medium   | 500        | QFont.Weight.Medium   |
| SemiBold | 600        | QFont.Weight.DemiBold |
| Bold     | 700        | QFont.Weight.Bold     |

---

## 3. Spacing & Layout Grid

### 3.1 Base Unit

4 px. All spacing, padding, margin, and gap values are multiples of 4.

### 3.2 Named Spacing Tokens

| Token  | Value | Usage                                                          |
|--------|-------|----------------------------------------------------------------|
| `sp-1` |  4 px | Icon-to-label gap, micro padding inside badges/chips           |
| `sp-2` |  8 px | Inner padding of small components, tight group gap             |
| `sp-3` | 12 px | Default gap between adjacent touch targets (minimum enforced)  |
| `sp-4` | 16 px | Card inner padding, form field spacing, standard row gap       |
| `sp-6` | 24 px | Section padding, card-to-card gap in grid                      |
| `sp-8` | 32 px | Screen-level horizontal padding (left/right edge margins)      |
| `sp-12`| 48 px | Between major layout sections                                  |
| `sp-16`| 64 px | Large structural gaps (rare)                                   |

### 3.3 Screen Layout Dimensions (1024 × 768)

```
┌─────────────────────────────────────────┐
│  HEADER BAR          88 px tall         │  ← always visible, never scrolls
├─────────────────────────────────────────┤
│  TAB STRIP           64 px tall         │  ← always visible
├─────────────────────────────────────────┤
│  CONTENT AREA        572 px tall        │  ← scrollable if needed
│  (768 - 88 - 64 - 44 = 572)            │
├─────────────────────────────────────────┤
│  FOOTER BAR          44 px tall         │  ← always visible
└─────────────────────────────────────────┘

Horizontal screen padding:  sp-8 (32 px) each side → 960 px usable width
Content grid columns:       2 equal columns = 464 px each, 32 px gutter
Card minimum height:        160 px
```

### 3.4 Border Radius Tokens

| Token     | Value | Usage                                              |
|-----------|-------|----------------------------------------------------|
| `r-sm`    |  4 px | Small badges, status dots, tight chips             |
| `r-md`    |  8 px | Inputs, spinboxes, small interactive elements      |
| `r-lg`    | 12 px | Cards, standard buttons, panels                    |
| `r-xl`    | 16 px | Prominent panels, modals, header connection badge  |
| `r-full`  | 999px | Pill badges, toggle switch track                   |

---

## 4. Component Visual Specs

### 4.1 Primary Button

**Purpose:** Main CTA actions (Start Demo, Connect, Save)

| Property        | Default                          | Hover                            | Pressed                          | Disabled                         |
|-----------------|----------------------------------|----------------------------------|----------------------------------|----------------------------------|
| Background      | `#3B82F6`                        | `#2563EB`                        | `#1D4ED8`                        | `#1A1F2B`                        |
| Border          | none                             | none                             | none                             | `1px solid #2D3441`              |
| Text color      | `#0F1419`                        | `#0F1419`                        | `#FFFFFF`                        | `#6B7280`                        |
| Text style      | body-strong (18 px, 600)         | body-strong                      | body-strong                      | body-strong                      |
| Min height      | 56 px                            | 56 px                            | 56 px                            | 56 px                            |
| Min width       | 120 px                           | 120 px                           | 120 px                           | 120 px                           |
| Padding         | 16 px vertical, 24 px horizontal | same                             | same                             | same                             |
| Border radius   | 12 px                            | 12 px                            | 12 px                            | 12 px                            |
| Shadow          | none                             | `0 4px 12px rgba(59,130,246,.4)` | none                             | none                             |
| Cursor          | pointer                          | pointer                          | default                          | not-allowed                      |
| Transition      | bg 150 ms ease                   | —                                | —                                | —                                |
| Opacity         | 1.0                              | 1.0                              | 1.0                              | 0.4                              |

**QSS snippet:**
```css
QPushButton[class="primary"] {
    background-color: #3B82F6;
    color: #0F1419;
    font-size: 18px;
    font-weight: 600;
    min-height: 56px;
    min-width: 120px;
    padding: 16px 24px;
    border-radius: 12px;
    border: none;
}
QPushButton[class="primary"]:hover { background-color: #2563EB; }
QPushButton[class="primary"]:pressed { background-color: #1D4ED8; color: #FFFFFF; }
QPushButton[class="primary"]:disabled {
    background-color: #1A1F2B;
    color: #6B7280;
    border: 1px solid #2D3441;
    opacity: 0.4; /* Note: Qt uses setEnabled(False) for disabled state */
}
```

---

### 4.2 E-Stop Button (Critical Variant)

**Purpose:** Emergency stop — single tap halts all robot motion immediately.
Positioned in header bar right side, visible on ALL screens.

| Property       | Default                            | Hover                              | Pressed/Active                     |
|----------------|------------------------------------|------------------------------------|-------------------------------------|
| Background     | `#EF4444`                          | `#DC2626`                          | `#B91C1C`                           |
| Border         | `3px solid #FCA5A5`                | `3px solid #F87171`                | `3px solid #B91C1C`                 |
| Text           | `E-STOP` — display (40 px, 700)    | same                               | same                                |
| Text color     | `#FFFFFF`                          | `#FFFFFF`                          | `#FFFFFF`                           |
| Size           | 200 × 72 px                        | same                               | same                                |
| Border radius  | 12 px                              | 12 px                              | 12 px                               |
| Shadow         | `0 0 0 4px rgba(239,68,68,0.3)`    | `0 0 0 8px rgba(239,68,68,0.5)`    | `0 0 0 2px rgba(239,68,68,0.2)`     |
| Pulse          | Subtle 2 s pulse on --error-muted  | none                               | none                                |

**Special behavior:**
- Tap-and-hold NOT required — single tap fires immediately (safety priority)
- After activation: button changes to pulsing `#B91C1C` with label "STOPPED"
- Resume button appears adjacent: "RESUME" — secondary style, `#10B981` background
- Must never be covered by overlays, modals, or scroll content

---

### 4.3 Secondary Button

**Purpose:** Cancel, back, non-destructive secondary actions

| Property     | Default        | Hover          | Pressed        | Disabled       |
|--------------|----------------|----------------|----------------|----------------|
| Background   | `#1A1F2B`      | `#232936`      | `#2C3347`      | `#1A1F2B`      |
| Border       | `1px solid #2D3441` | `1px solid #3B82F6` | `1px solid #2563EB` | `1px solid #2D3441` |
| Text color   | `#9CA3AF`      | `#E5E7EB`      | `#E5E7EB`      | `#6B7280`      |
| Text style   | body (18 px)   | body-strong    | body-strong    | body           |
| Min height   | 56 px          | 56 px          | 56 px          | 56 px          |
| Border radius| 12 px          | 12 px          | 12 px          | 12 px          |
| Opacity      | 1.0            | 1.0            | 1.0            | 0.5            |

---

### 4.4 Jog Axis Button (Touch-Hold Variant)

**Purpose:** Directional jog control (X+, X-, Y+, Y-, Z+, Z-, Rx+, Rx-, etc.)
Activated by press-and-hold; robot moves while held, stops on release.

| Property     | Default         | Hold-Active                        | Released        |
|--------------|-----------------|------------------------------------|-----------------|
| Background   | `#232936`       | Axis-color (see below)             | `#1A1F2B`       |
| Border       | `1px solid #2D3441` | `2px solid` axis-color-light   | `1px solid #2D3441` |
| Text color   | `#9CA3AF`       | `#FFFFFF`                          | `#9CA3AF`       |
| Text         | ± symbol + axis | ± symbol + axis                    | ± symbol + axis |
| Text style   | heading (24 px, 600) | heading bold                  | heading         |
| Size         | 88 × 64 px      | 88 × 64 px                         | 88 × 64 px      |
| Border radius| 12 px           | 12 px                              | 12 px           |
| Shadow       | none            | `0 0 12px` axis-color `opacity .4` | none            |

**Axis colors:**
- X axis: `#EF4444` (red) — matches robotics convention
- Y axis: `#10B981` (green)
- Z axis: `#3B82F6` (blue)
- Rx/Ry/Rz: desaturated variants — `#F87171`, `#6EE7B7`, `#93C5FD`

---

### 4.5 Card (Base)

**Purpose:** Grouping panel for related controls or info

| Property         | Value                                       |
|------------------|---------------------------------------------|
| Background       | `#1A1F2B`                                   |
| Border           | `1px solid #2D3441`                         |
| Border radius    | 12 px                                       |
| Min height       | 160 px                                      |
| Inner padding    | 16 px (sp-4)                                |
| Shadow           | `0 2px 8px rgba(0,0,0,0.4)`                 |
| Hover (card list)| background → `#232936`, translateY -2 px, shadow → `0 6px 16px rgba(0,0,0,0.5)` |
| Hover transition | 150 ms ease                                 |

#### 4.5a Demo Card (Category Accent Stripe)

Extends base card. Left edge has a 4 px vertical stripe in category color.

```
┌─╔══════════════════════════════╗
│ ║ CATEGORY BADGE (small, 12px) ║  ← top-left, text in category color
│ ║                              ║
│ ║ Demo Name (heading 24px)     ║
│ ║ Description (body 18px,      ║
│ ║   secondary color)           ║
│ ║                              ║
│ ║ Duration · Steps  (small)    ║
└─╚══════════════════════════════╝
  ↑ 4 px left border in category color
```

| State    | Left border           | Background   |
|----------|-----------------------|--------------|
| Default  | 4px solid cat-color   | `#1A1F2B`    |
| Hover    | 4px solid cat-color   | `#232936`    |
| Running  | 4px solid cat-color + pulsing glow | `#1E3A5F` (accent-muted) |
| Disabled | 4px solid `#2D3441`   | `#1A1F2B` at 0.5 opacity |

---

### 4.6 Slider (Touch-Optimized)

**Purpose:** Speed control, step size, delay values

| Property           | Value                                   |
|--------------------|-----------------------------------------|
| Track height       | 8 px                                    |
| Track background   | `#2D3441`                               |
| Track fill color   | `#3B82F6` (accent)                      |
| Track border radius| 4 px (r-sm)                             |
| Thumb diameter     | 40 px (min per spec)                    |
| Thumb background   | `#3B82F6`                               |
| Thumb border       | `3px solid #1A1F2B`                     |
| Thumb shadow       | `0 2px 8px rgba(59,130,246,0.5)`        |
| Thumb hover        | background → `#2563EB`, diameter 44 px  |
| Thumb pressed      | background → `#1D4ED8`, diameter 40 px  |
| Label below track  | current value, body-strong (18px)       |
| Min/Max labels     | small (14px), text-muted                |
| Total height       | 72 px (thumb + labels)                  |

**QSS snippet:**
```css
QSlider::groove:horizontal {
    height: 8px;
    background: #2D3441;
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: #3B82F6;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    width: 40px;
    height: 40px;
    margin: -16px 0;
    background: #3B82F6;
    border: 3px solid #1A1F2B;
    border-radius: 20px;
}
QSlider::handle:horizontal:hover { background: #2563EB; }
QSlider::handle:horizontal:pressed { background: #1D4ED8; }
```

---

### 4.7 Spinbox / Numeric Input

**Purpose:** Precise numeric entry for step size, angles, coordinates

| Property       | Default              | Focus                 | Disabled             |
|----------------|----------------------|-----------------------|----------------------|
| Background     | `#1A1F2B`            | `#1A1F2B`             | `#0F1419`            |
| Border         | `1px solid #2D3441`  | `2px solid #3B82F6`   | `1px solid #2D3441`  |
| Border radius  | 8 px                 | 8 px                  | 8 px                 |
| Text color     | `#E5E7EB`            | `#E5E7EB`             | `#6B7280`            |
| Text style     | mono (16 px)         | mono                  | mono                 |
| Height         | 56 px                | 56 px                 | 56 px                |
| Padding        | 12 px horizontal     | 12 px                 | 12 px                |
| Up/down arrows | `#6B7280`            | `#3B82F6`             | `#2D3441`            |
| Arrow size     | 24 × 24 px each      | same                  | same                 |
| Arrow hit area | 40 × 40 px (touch)   | same                  | same                 |
| Unit suffix    | small (14px), muted  | small, accent         | small, muted         |

---

### 4.8 Status Badge (Robot Connection)

**Purpose:** Shows current robot connection state. Lives in header bar, center.

**Dimensions:** pill shape, height 36 px, min-width 140 px, border-radius 999 px (r-full)

| State       | Dot Color   | Label        | Badge Background | Badge Border       | Text Color  |
|-------------|-------------|--------------|------------------|--------------------|-------------|
| Idle        | `#6B7280`   | "Idle"       | `#1A1F2B`        | `1px solid #2D3441`| `#9CA3AF`   |
| Connecting  | `#F59E0B` pulse | "Connecting..." | `#451A03`   | `1px solid #F59E0B`| `#F59E0B`   |
| Connected   | `#10B981`   | "Connected"  | `#064E3B`        | `1px solid #10B981`| `#10B981`   |
| Error       | `#EF4444` pulse | "Error"  | `#450A0A`        | `1px solid #EF4444`| `#EF4444`   |
| Fault       | `#EF4444` fast-pulse | "FAULT" | `#450A0A`   | `2px solid #EF4444`| `#FFFFFF`   |

**Dot:** 10 px diameter circle, 8 px left margin from badge left edge.
**Connecting/Error dot:** CSS animation pulse — scale 1.0→1.4→1.0, 1.2 s infinite.
Note: Qt animates this via QPropertyAnimation on a custom painted dot widget.

**Semantic icons (color-blind safety):**
- Idle: ○ (outline circle)
- Connecting: ◌ (rotating arc, implemented as animated QLabel)
- Connected: ✓ (checkmark)
- Error/Fault: ✕ (cross)

---

### 4.9 Toggle / Switch

**Purpose:** Binary settings (joint mode vs TCP mode, enable/disable options)

| Property        | Off State           | On State             |
|-----------------|---------------------|----------------------|
| Track width     | 56 px               | 56 px                |
| Track height    | 30 px               | 30 px                |
| Track color     | `#2D3441`           | `#3B82F6`            |
| Track radius    | 15 px (r-full)      | 15 px                |
| Thumb diameter  | 22 px               | 22 px                |
| Thumb color     | `#6B7280`           | `#FFFFFF`            |
| Thumb position  | left (4 px margin)  | right (4 px margin)  |
| Thumb shadow    | none                | `0 2px 6px rgba(59,130,246,.5)` |
| Transition      | 150 ms ease         | 150 ms ease          |
| Total hit area  | 80 × 44 px (with label) | same            |

Note: Implement as custom QWidget subclass with paintEvent; QSS cannot fully style
QCheckBox into a toggle-switch appearance on all Qt platforms.

---

### 4.10 Tab Strip

**Purpose:** Primary navigation — Jog / Demos / Settings

| Property          | Inactive Tab         | Active Tab           | Hover (inactive)     |
|-------------------|----------------------|----------------------|----------------------|
| Height            | 64 px                | 64 px                | 64 px                |
| Background        | `#1A1F2B`            | `#0F1419`            | `#232936`            |
| Bottom indicator  | none                 | `3px solid #3B82F6`  | `3px solid #2D3441`  |
| Text color        | `#9CA3AF`            | `#3B82F6`            | `#E5E7EB`            |
| Text style        | subhead (20 px, 600) | subhead (20 px, 700) | subhead (20 px, 600) |
| Min width         | 160 px               | 160 px               | 160 px               |
| Tab separator     | `1px solid #2D3441` vertical, inset 16 px top/bottom |
| Icon (optional)   | 24 × 24 px, above label, secondary color | accent color | primary color |

Full-width tab strip spans 1024 px. Three tabs = 341 px each (approximately).

---

### 4.11 Scroll Area

**Purpose:** Demos card grid, settings sections, event log

| Property           | Value                           |
|--------------------|---------------------------------|
| Scrollbar width    | 8 px                            |
| Scrollbar track bg | `#1A1F2B`                       |
| Scrollbar thumb bg | `#2D3441`                       |
| Scrollbar thumb hover | `#3B82F6`                    |
| Scrollbar thumb radius | 4 px                        |
| Scroll fade edge   | gradient fade to `--bg-base` at top/bottom of scroll area (12 px) |

```css
QScrollBar:vertical {
    width: 8px;
    background: #1A1F2B;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #2D3441;
    border-radius: 4px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover { background: #3B82F6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
```

---

### 4.12 Modal / Dialog

**Purpose:** Confirm destructive actions, connection dialogs, parameter entry

| Property         | Value                                                    |
|------------------|----------------------------------------------------------|
| Overlay          | `rgba(15,20,25,0.85)` full-screen behind modal           |
| Panel background | `#1A1F2B`                                                |
| Panel border     | `1px solid #2D3441`                                      |
| Panel radius     | 16 px (r-xl)                                             |
| Panel shadow     | `0 24px 48px rgba(0,0,0,0.7)`                            |
| Panel max-width  | 640 px                                                   |
| Panel padding    | 32 px (sp-8)                                             |
| Title            | heading (24 px, 600), primary color                      |
| Body text        | body (18 px), secondary color                            |
| Button row       | right-aligned, gap 12 px, primary + secondary buttons    |
| Animation        | scale 0.95→1.0 + opacity 0→1, 150 ms ease               |

**Critical (destructive) modal variant:**
- Panel left border: `4px solid #EF4444`
- Title color: `#EF4444`

---

### 4.13 Toast / Notification

**Purpose:** Ephemeral feedback (demo started, connection lost, command sent)

| Property         | Value                                            |
|------------------|--------------------------------------------------|
| Position         | Bottom-center of content area, above footer      |
| Width            | 480 px max, 320 px min                           |
| Height           | auto, min 56 px                                  |
| Background       | `#232936`                                        |
| Border           | `1px solid #2D3441`                              |
| Border radius    | 12 px                                            |
| Left accent bar  | 4 px solid in semantic color (success/warn/error/info) |
| Shadow           | `0 8px 24px rgba(0,0,0,0.6)`                     |
| Icon             | 20 × 20 px semantic icon (✓ ⚠ ✕ ℹ), colored     |
| Text             | body (18 px), primary, max 2 lines               |
| Duration         | 4 s auto-dismiss (error: 8 s, manual dismiss)    |
| Entry animation  | translateY +24px→0 + opacity 0→1, 200 ms ease-out |
| Exit animation   | translateY 0→+24px + opacity 1→0, 150 ms ease-in |
| Stack            | max 3 toasts, newest on top, 8 px gap            |

---

## 5. Screen Layout Sketches

All sketches are proportional to 1024 × 768. Characters represent pixel blocks.
Scale: ~1 char ≈ 4 px wide, ~1 row ≈ 8 px tall.

---

### 5.1 Jog Screen (Primary)

```
1024 px wide
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER [88px tall] bg:#0F1419 border-bottom:1px #2D3441                                        │
│ ┌─────────────────────────┐  ┌───────────────────────┐  ┌────────────────────────────────────┐ │
│ │ UR10 Jog Control        │  │  ● Connected  (badge) │  │       ██ E-STOP ██  [200×72]       │ │
│ │ heading / white 24px    │  │  success pill badge   │  │       bg:#EF4444 text:white        │ │
│ └─────────────────────────┘  └───────────────────────┘  └────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TAB STRIP [64px tall] bg:#1A1F2B border-bottom:1px #2D3441                                     │
│ ┌──────────────────────────────────┐┌─────────────────────────┐┌────────────────────────────┐  │
│ │ ▌ JOG       (active, blue line) ││  DEMOS                  ││  SETTINGS                  │  │
│ │  subhead 20px, #3B82F6          ││  subhead 20px, #9CA3AF  ││  subhead 20px, #9CA3AF     │  │
│ └──────────────────────────────────┘└─────────────────────────┘└────────────────────────────┘  │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CONTENT AREA [572px tall] bg:#0F1419  padding: 0 32px                                          │
│                                                                                                │
│ ┌──────────────────────────────────────────┐  ┌─────────────────────────────────────────────┐  │
│ │ MOTION MODE PANEL  [card, 80px]          │  │ READOUT PANEL  [card, ~200px]               │  │
│ │ bg:#1A1F2B border:#2D3441 r:12           │  │ bg:#1A1F2B border:#2D3441                   │  │
│ │  ┌──────────────────────────────────┐    │  │                                             │  │
│ │  │ TCP MODE  ◄○►  JOINT MODE toggle │    │  │  TCP Position      Joint Angles             │  │
│ │  └──────────────────────────────────┘    │  │  X:  +123.4 mm     J1:  +12.34°            │  │
│ │  Step: [spinbox 60px] mm  [ slider ]     │  │  Y:  -045.2 mm     J2:  -08.12°            │  │
│ └──────────────────────────────────────────┘  │  Z:  +312.1 mm     J3:  +45.67°            │  │
│                                               │  Rx:  +10.00°      J4:  -23.45°            │  │
│ ┌──────────────────────────────────────────────  Ry:  -05.50°      J5:  +78.90°            │  │
│ │ TRANSLATION AXES                          │  │  Rz:  +00.00°      J6:  +00.00°            │  │
│ │ [card, ~220px tall]                       │  └─────────────────────────────────────────────┘  │
│ │                                           │                                                │
│ │  ┌──────────────────────────────────────┐ │  ┌─────────────────────────────────────────────┐  │
│ │  │   [X-] [88×64]   [X+] [88×64]       │ │  │ SPEED CONTROL  [card, ~120px]               │  │
│ │  │   bg:#232936 red-accent on hold      │ │  │ Speed:  [═══════════●──────] 50%           │  │
│ │  ├──────────────────────────────────────┤ │  │         [slider, 40px thumb]               │  │
│ │  │   [Y-] [88×64]   [Y+] [88×64]       │ │  │ Step:   [spinbox] mm  [slider]             │  │
│ │  ├──────────────────────────────────────┤ │  └─────────────────────────────────────────────┘  │
│ │  │   [Z-] [88×64]   [Z+] [88×64]       │ │                                                │
│ │  └──────────────────────────────────────┘ │  ┌─────────────────────────────────────────────┐  │
│ └──────────────────────────────────────────┘  │ HOME      ZERO     WAYPOINT   RECORD        │  │
│                                               │ [secondary buttons, 56px min-height each]   │  │
│ ┌──────────────────────────────────────────┐  └─────────────────────────────────────────────┘  │
│ │ ROTATION AXES                            │                                                │
│ │ [card, ~160px tall]                      │                                                │
│ │  [Rx-][Rx+]  [Ry-][Ry+]  [Rz-][Rz+]    │                                                │
│ │  88×64 each, desaturated axis colors     │                                                │
│ └──────────────────────────────────────────┘                                                │
│                                                                                                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ FOOTER [44px] bg:#1A1F2B border-top:1px #2D3441                                                │
│  ● Ready — TCP mode, step 1.0 mm, speed 50%                   [LOG ▲] last event 0:00:12 ago  │
│  micro 12px, #6B7280                                                          #9CA3AF          │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 5.2 Demos Screen

```
1024 px wide
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER [88px]  same as Jog screen — E-STOP always in same position                             │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TAB STRIP [64px]   JOG  |  ▌ DEMOS (active)  |  SETTINGS                                      │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CONTENT AREA [572px] — SCROLLABLE                                                              │
│                                                                                                │
│ ┌──────────────────────────────────────────────────────────────────────────────────────────┐   │
│ │ ★ CURRENTLY RUNNING: "Wave & Greet"  ██ STOP ██  [pinned banner — only when demo active]│   │
│ │ bg:#1E3A5F border:1px #3B82F6 r:12  subhead 20px                         error button   │   │
│ └──────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                │
│  ── SHOWCASE ──────────────────────────────────────────────────────  (violet #7C3AED)          │
│                                                                                                │
│ ┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐             │
│ │▌ SHOWCASE                           │  │▌ SHOWCASE                           │             │
│ │  Wave & Greet                        │  │  Bow                                 │             │
│ │  Friendly greeting wave sequence     │  │  Formal bow demonstration            │             │
│ │  ~45s · 6 segments       [RUN ▶]    │  │  ~30s · 4 segments       [RUN ▶]    │             │
│ └──────────────────────────────────────┘  └──────────────────────────────────────┘             │
│  4px violet left stripe                    4px violet left stripe                              │
│  card: 464×160px  gap: 32px                                                                    │
│                                                                                                │
│  ── DYNAMIC ───────────────────────────────────────────────────────  (cyan #06B6D4)            │
│                                                                                                │
│ ┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐             │
│ │▌ DYNAMIC                            │  │▌ DYNAMIC                            │             │
│ │  Pendulum                            │  │  Sprint                              │             │
│ │  Pendulum swing motion               │  │  High-speed linear traversal         │             │
│ │  ~60s · 8 segments       [RUN ▶]    │  │  ~20s · 3 segments       [RUN ▶]    │             │
│ └──────────────────────────────────────┘  └──────────────────────────────────────┘             │
│                                                                                                │
│  ── INDUSTRIAL ────────────────────────────────────────────────────  (amber #D97706)           │
│                                                                                                │
│ ┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐             │
│ │▌ INDUSTRIAL     ...Sorting  Stacking │  │▌ INDUSTRIAL                         │             │
│ │  Industrial                          │  │  Sorting                             │             │
│ │  ...                    [RUN ▶]     │  │  ...                    [RUN ▶]     │             │
│ └──────────────────────────────────────┘  └──────────────────────────────────────┘             │
│                                                                                                │
│  ── ENGINEERING ───────────────────────────────────────────────────  (emerald #059669)         │
│                                                                                                │
│ ┌──────────────────────────────────────┐  ┌──────────────────────────────────────┐             │
│ │▌ ENGINEERING  Reach  Technical  etc  │  │▌ ENGINEERING    Record & Replay ▧    │             │
│ │  Plunge                              │  │  Record & Replay                     │             │
│ │  ...                    [RUN ▶]     │  │  Record and replay custom path [BETA]│             │
│ └──────────────────────────────────────┘  └──────────────────────────────────────┘             │
│                                                                                                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ FOOTER [44px]                                                                                  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 5.3 Demo Runner Screen

```
1024 px wide
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER [88px]  ← back to Demos (breadcrumb left)   ● Connected   ██ E-STOP ██                 │
│  ← Demos / Wave & Greet     [heading 24px, secondary color]                                   │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TAB STRIP [64px]  JOG | ▌ DEMOS (active) | SETTINGS                                           │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CONTENT AREA [572px]                                                                           │
│                                                                                                │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ PHASE INDICATOR PANEL  [card, 100px]  bg:#1A1F2B                                          │ │
│ │                                                                                            │ │
│ │  PHASE 2 of 6: APPROACH    ████████████████████░░░░░░░  65%  segment 4 of 6              │ │
│ │  title 32px, accent        [segment progress bar, 16px tall, full-width]                  │ │
│ │  Phase label: heading 24px, white                                                          │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
│ ┌────────────────────────────────────────────┐  ┌──────────────────────────────────────────┐  │
│ │ PARAMETER CONTROLS  [card, ~240px]         │  │ LIVE EVENT LOG  [scroll area, ~240px]    │  │
│ │                                            │  │ bg:#0F1419 border:#2D3441 r:12           │  │
│ │  Audience Direction                        │  │                                          │  │
│ │  [toggle: LEFT ◄○► RIGHT]                 │  │ 00:01:23 Phase 2 started                 │  │
│ │                                            │  │ 00:01:20 Speed override: 75%             │  │
│ │  Demo Speed                                │  │ 00:01:15 Phase 1 completed               │  │
│ │  [slider  25%────●────────────] 75%        │  │ 00:01:00 Demo started                    │  │
│ │                                            │  │ 00:00:55 Robot connected                 │  │
│ │  Cycle Delay                               │  │ ...                                      │  │
│ │  [spinbox] 2.5 s                           │  │ [auto-scrolls to latest, mono 16px]      │  │
│ │                                            │  └──────────────────────────────────────────┘  │
│ │  Cycles                                    │                                                │
│ │  [spinbox] 3  (0=infinite)                 │                                                │
│ │                                            │                                                │
│ └────────────────────────────────────────────┘                                                │
│                                                                                                │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ ACTION ROW  [card, 80px]                                                                   │ │
│ │                                                                                            │ │
│ │  [▶ START  — primary 200px]  [⏹ STOP — error 200px]  [TEST SEGMENT — secondary 180px]   │ │
│ │   bg:#3B82F6                  bg:#EF4444               bg:#1A1F2B                          │ │
│ │   all 56px tall, 12px gap between                                                          │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ FOOTER [44px]  ● Running: Wave & Greet — Phase 2/6, Cycle 1/3, Speed 75%    [LOG ▲]           │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Segment progress bar spec:**
- Track height: 16 px, full width of panel minus padding
- Background: `#2D3441`
- Fill: gradient `#3B82F6` → `#2563EB`
- Border radius: 8 px
- Animated fill: transitions over 250 ms ease-in-out as segments complete

---

### 5.4 Settings Screen

```
1024 px wide
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ HEADER [88px]                                                    ██ E-STOP ██                  │
│  UR10 Jog Control                  ● Connected                                                 │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TAB STRIP [64px]   JOG | DEMOS | ▌ SETTINGS (active)                                          │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ CONTENT AREA [528px] — SCROLLABLE (save/cancel in footer pinned)                               │
│                                                                                                │
│  ── ROBOT CONNECTION ───────────────────────────────────────────────────────────────────────   │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │  Robot IP Address   [input field: 192.168.1.100      ]  [CONNECT] [DISCONNECT]            │ │
│ │  Port               [spinbox: 30002               ]                                        │ │
│ │  Timeout            [spinbox: 5.0 s               ]                                        │ │
│ │  Auto-reconnect     [toggle: OFF ◄○► ON ]                                                  │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
│  ── DEMO DEFAULTS ─────────────────────────────────────────────────────────────────────────   │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │  Default speed      [slider: ─────●────────]  75%                                         │ │
│ │  Default cycles     [spinbox: 1             ]  (0 = infinite)                              │ │
│ │  Default delay      [spinbox: 2.0 s         ]                                              │ │
│ │  Audience direction [toggle: LEFT ◄○► RIGHT ]                                              │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
│  ── UI PREFERENCES ────────────────────────────────────────────────────────────────────────   │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │  Confirm before run  [toggle: ON ]                                                         │ │
│ │  Sound feedback      [toggle: OFF]                                                         │ │
│ │  Log verbosity       [dropdown: INFO ▾ ]                                                   │ │
│ │  Screen brightness   [slider: ─────────●──] 90%                                           │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
│  ── ABOUT ─────────────────────────────────────────────────────────────────────────────────   │
│ ┌────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │  App version:  2.0.0          Robot firmware:  5.12.3                                      │ │
│ │  PyQt6:        6.7.0          Python:          3.11.x                                      │ │
│ └────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ FOOTER [44px — settings save/cancel replaces normal status]                                    │
│  [CANCEL — secondary, left]                                         [SAVE SETTINGS — primary]  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Interaction Patterns

### 6.1 Hover States (Touchscreen Context)

On a capacitive touchscreen, hover states fire only when using a mouse (e.g., during dev/debug)
or for accessibility pointers. They should not create confusion on pure-touch interaction.

- **Cards:** Background lightens `#1A1F2B` → `#232936`, translateY -2 px, shadow grows.
  Implemented via QGraphicsDropShadowEffect transition on QPropertyAnimation.
- **Buttons:** Background color shifts per state table. No translateY on buttons (touch jitter risk).
- **Tab items:** Bottom border appears `3px solid #2D3441` on hover when inactive.
- **Slider thumb:** Grows from 40 px to 44 px diameter on hover.

### 6.2 Pressed / Touch Feedback

- **All buttons:** Background darkens by one step (see state tables). No delay.
- **Jog buttons:** Immediate visual hold state (axis color, glow). Color fires in <16 ms.
- **Cards (demo run):** Scale 0.98 on press, 150 ms restore. Visual confirmation of tap.
- **Color shift only** — no hardware haptic (Elo i3 does not provide haptic feedback).
  Consider brief audio click (100 ms, 440 Hz, opt-in in settings) for tactile substitute.

### 6.3 Tap-and-Hold for Jog Buttons

- **Hold threshold:** 0 ms — motion begins immediately on press (industrial safety convention:
  operator decides intent by holding; no delay before motion starts).
- **Hold indicator:** Button background transitions to active axis-color over 100 ms.
- **Release behavior:** Motion stops within 1 robot control cycle (<8 ms). Button returns to
  default state over 100 ms.
- **Implementation:** QAbstractButton::pressed signal starts jog command loop (10 Hz timer);
  QAbstractButton::released signal sends stop command.
- **Multi-touch guard:** Only one axis active at a time. If a second axis button is pressed
  while another is held, ignore the second press (safety: no simultaneous axis jogging).

### 6.4 Debouncing

- **E-stop:** No debounce. Fires immediately on first signal. Hardware-level interrupt preferred.
- **Standard buttons:** 150 ms software debounce (ignore repeated signals within window).
- **Jog buttons:** No debounce on press (latency critical). Debounce release by 50 ms
  (prevents flicker on finger lift).
- **Slider:** Value change events throttled to 60 Hz (16 ms) to avoid flooding robot TCP.
- **Spinbox:** Value committed on focus loss or Enter press; not on every keystroke.

### 6.5 Touch Target Compliance Summary

| Element              | Min Touch Size     | Implemented Size   | Gap to Neighbor  |
|----------------------|--------------------|--------------------|------------------|
| Primary button       | 56 × 44 px         | 56 × 120 px+       | ≥12 px           |
| E-stop button        | 56 × 44 px         | 72 × 200 px        | ≥24 px (isolated)|
| Jog axis button      | 56 × 44 px         | 64 × 88 px         | ≥12 px           |
| Tab item             | 64 × 64 px         | 64 × 341 px        | 0 (spans full)   |
| Slider thumb         | 40 × 40 px         | 40 × 40 px         | ≥32 px from edge |
| Toggle switch        | 44 × 44 px         | 44 × 80 px (w/lbl) | ≥12 px           |
| Demo card RUN button | 56 × 44 px         | 56 × 100 px        | ≥24 px (inside card) |
| Scrollbar thumb      | 8 × 40 px          | 8 × 40 px min      | edge of viewport |

---

## 7. Accessibility & Operator Considerations

### 7.1 Contrast Summary

All primary text exceeds WCAG AA (4.5:1 for normal, 3.0:1 for large/bold ≥18px or bold 14px).
All interactive element labels exceed 4.5:1. E-stop white on red: 4.8:1 (AA pass at display size).

### 7.2 Readability at Arm's Length (~50 cm)

Minimum readable size at 50 cm viewing distance on a 1024×768 / ~17" screen (≈85 dpi):
- At 85 dpi, 18 px ≈ 5.4 mm physical. Angular size at 50 cm: ~0.62°.
- Recommended minimum for comfortable reading: 0.5° → 4.4 mm → ~15 px at 85 dpi.
- All body text is 18 px — exceeds minimum. Micro (12 px) used only for footer status
  where operator can approach screen if needed.
- Coordinate readout values (mono 16 px): borderline — recommend bold weight for readouts.
- Recommendation: Mono readout values should use mono-bold 18 px.

### 7.3 Color-Blind Safety

Status states use THREE channels simultaneously (never color alone):

| State       | Color          | Icon/Symbol | Text Label      |
|-------------|----------------|-------------|-----------------|
| Idle        | gray           | ○ ring      | "Idle"          |
| Connecting  | amber          | ◌ spinner   | "Connecting..."  |
| Connected   | green          | ✓ check     | "Connected"     |
| Error       | red            | ✕ cross     | "Error"         |
| Fault       | red (bold)     | ✕ cross     | "FAULT" (caps)  |
| Running     | blue fill      | ▶ triangle  | "Running"       |
| Stopped     | red fill       | ⏹ square   | "Stopped"       |
| Success     | green bg       | ✓ check     | message text    |
| Warning     | amber bg       | ⚠ triangle  | message text    |

Axis jog buttons use color AND letter labels (X, Y, Z) AND ± symbols.

### 7.4 Motor Accessibility

- All interactive targets meet 40 px minimum dimension on both axes.
- 12 px minimum gap between adjacent targets prevents accidental activation.
- E-stop is 200 × 72 px with 24 px clearance — designed for gloved or tremor-affected touch.
- Jog buttons at 88 × 64 px allow imprecise touch while remaining distinct.

### 7.5 Cognitive Load Reduction

- E-stop is always in the same position (top-right) regardless of screen.
- Three-tab structure is always visible — operator always knows where they are.
- Footer provides persistent machine state summary in one line.
- Demo cards show duration and segment count — operators can predict time commitment.
- Settings changes require explicit SAVE action — no accidental commits.

---

## 8. Animation & Motion

### 8.1 Principles

- **Motion serves function.** No decorative animations. Every transition communicates state.
- **Short and crisp.** Maximum 250 ms for any transition. Elo i3 has limited GPU acceleration.
- **Reduce motion:** If OS-level reduce-motion preference is set (Qt: QAccessible), disable
  all translateY transitions and reduce color transitions to instant (0 ms).

### 8.2 Timing Tokens

| Token       | Duration | Easing           | Usage                              |
|-------------|----------|------------------|------------------------------------|
| `t-instant` |  0 ms    | —                | Safety-critical (e-stop, jog start)|
| `t-fast`    | 100 ms   | ease-out         | Button press feedback, jog hold    |
| `t-normal`  | 150 ms   | ease-in-out      | Hover lift, tab switch, modal open |
| `t-slow`    | 250 ms   | ease-in-out      | Status badge transitions, progress |
| `t-toast`   | 200 ms   | cubic-bezier(.22,1,.36,1) | Toast entry              |

### 8.3 Specific Animations

| Element           | Animation                                                   | Duration  |
|-------------------|-------------------------------------------------------------|-----------|
| Card hover        | shadow grows, translateY -2px (QPropertyAnimation)          | 150 ms    |
| Card press        | scale 0.98 (QPropertyAnimation on size)                     | 100 ms    |
| Button press      | background color shift                                       | 100 ms    |
| Tab switch        | content area: opacity 0.8→1.0 (fast cross-fade)             | 150 ms    |
| Modal appear      | opacity 0→1, scale 0.95→1.0                                 | 150 ms    |
| Modal dismiss     | opacity 1→0, scale 1.0→0.95                                 | 120 ms    |
| Toast entry       | translateY +24→0, opacity 0→1                               | 200 ms    |
| Toast exit        | translateY 0→+24, opacity 1→0                               | 150 ms    |
| Status badge      | background-color, border-color cross-fade                    | 250 ms    |
| Progress bar fill | width transition as segment completes                        | 250 ms    |
| Connection dot    | scale pulse 1.0→1.4→1.0 (connecting/error states)           | 1200 ms ∞ |
| Jog button hold   | background color shift to axis-color                         | 100 ms    |
| Jog button release| background color back to default                             | 150 ms    |

### 8.4 Qt Animation Implementation Notes

Qt does not natively tween QSS color properties via QPropertyAnimation.
Use these patterns:
- **Color transitions:** Custom QWidget.paintEvent with lerped QColor values,
  driven by QPropertyAnimation on a float `t` property (0.0 → 1.0).
- **Scale/translate:** QGraphicsOpacityEffect + QPropertyAnimation on pos/size.
- **Pulsing dot:** QTimer (50 ms tick) updating a float property used in paintEvent.
- **Tab content fade:** QStackedWidget with QGraphicsOpacityEffect on outgoing widget.

---

## 9. QSS Implementation Notes

### 9.1 Global Application Stylesheet

Apply to QApplication via `app.setStyleSheet(...)`. Define once at startup.

```css
/* Root window */
QMainWindow, QDialog {
    background-color: #0F1419;
    color: #E5E7EB;
}

/* Generic widget default */
QWidget {
    background-color: transparent;
    color: #E5E7EB;
    font-family: "Inter", "DejaVu Sans", sans-serif;
    font-size: 18px;
}

/* Panel / card base */
QFrame[class="card"] {
    background-color: #1A1F2B;
    border: 1px solid #2D3441;
    border-radius: 12px;
}

/* Header bar */
QFrame[class="header"] {
    background-color: #0F1419;
    border-bottom: 1px solid #2D3441;
    min-height: 88px;
    max-height: 88px;
}

/* Tab strip */
QTabBar::tab {
    background-color: #1A1F2B;
    color: #9CA3AF;
    font-size: 20px;
    font-weight: 600;
    min-width: 160px;
    min-height: 64px;
    padding: 0 24px;
    border: none;
    border-bottom: 3px solid transparent;
}
QTabBar::tab:selected {
    background-color: #0F1419;
    color: #3B82F6;
    border-bottom: 3px solid #3B82F6;
}
QTabBar::tab:hover:!selected {
    background-color: #232936;
    color: #E5E7EB;
    border-bottom: 3px solid #2D3441;
}
QTabWidget::pane {
    background-color: #0F1419;
    border: none;
}

/* Footer bar */
QFrame[class="footer"] {
    background-color: #1A1F2B;
    border-top: 1px solid #2D3441;
    min-height: 44px;
    max-height: 44px;
}

/* Text inputs */
QLineEdit, QTextEdit {
    background-color: #1A1F2B;
    border: 1px solid #2D3441;
    border-radius: 8px;
    color: #E5E7EB;
    padding: 12px;
    selection-background-color: #1E3A5F;
    selection-color: #E5E7EB;
    min-height: 56px;
}
QLineEdit:focus, QTextEdit:focus {
    border: 2px solid #3B82F6;
}
QLineEdit:disabled { color: #6B7280; }
```

### 9.2 QSS Limitations to Work Around

| CSS Feature        | QSS Support | Workaround                                          |
|--------------------|-------------|-----------------------------------------------------|
| `::before/::after` | No          | Custom paintEvent or overlay QLabel                 |
| CSS transitions    | No          | QPropertyAnimation on custom properties             |
| CSS variables      | No          | Python constants; generate QSS string with f-string |
| `transform:`       | No          | QGraphicsEffect or move/resize animation            |
| `box-shadow:`      | No (limited)| QGraphicsDropShadowEffect                           |
| `clip-path:`       | No          | Custom paintEvent with QPainterPath                 |
| `gradient on border`| No         | Outer wrapper widget with gradient background       |

### 9.3 Property-Based Styling Pattern

Use `setProperty()` + `style().unpolish()/polish()` to dynamically switch QSS states:

```python
# Example: mark a button as active axis
btn.setProperty("axis_active", True)
btn.style().unpolish(btn)
btn.style().polish(btn)
```

```css
QPushButton[axis_active="true"] {
    background-color: #EF4444;
    border: 2px solid #FCA5A5;
}
```

---

## 10. Demo Inventory

All 12+ demos must appear on the Demos screen. Category assignments below:

| Demo Name          | Category    | Stripe Color | Notes                                |
|--------------------|-------------|--------------|--------------------------------------|
| Wave & Greet       | Showcase    | `#7C3AED`    | Flagship demo                        |
| Bow                | Showcase    | `#7C3AED`    |                                      |
| Pendulum           | Dynamic     | `#06B6D4`    | Continuous oscillation               |
| Sprint             | Dynamic     | `#06B6D4`    | High-speed traversal                 |
| Plunge             | Dynamic     | `#06B6D4`    |                                      |
| Industrial         | Industrial  | `#D97706`    | Simulates production task            |
| Sorting            | Industrial  | `#D97706`    |                                      |
| Stacking           | Industrial  | `#D97706`    |                                      |
| Demo               | Industrial  | `#D97706`    | Generic demo slot                    |
| Technical          | Engineering | `#059669`    |                                      |
| Reach              | Engineering | `#059669`    |                                      |
| Juggle             | Engineering | `#059669`    | Complex trajectory                   |
| Record & Replay    | Engineering | `#059669`    | PLACEHOLDER — UI present, grayed out |

**Grid layout:** 2 columns × N rows per category section.
Category header is a full-width row (text label + thin divider line in category color).
Demos with `PLACEHOLDER` status: card shown at 0.5 opacity, RUN button disabled,
badge shows "Coming Soon" in muted text.

---

## Appendix A: Color Swatch Reference (Hex Only)

```
Background:     #0F1419    Surface:       #1A1F2B    Surface+:    #232936
Overlay:        #2C3347    Border:        #2D3441    Focus:       #3B82F6

Text/Primary:   #E5E7EB    Text/Sec:      #9CA3AF    Text/Muted:  #6B7280
Text/Inverse:   #0F1419    Text/Accent:   #93C5FD

Accent:         #3B82F6    Accent/Hover:  #2563EB    Accent/Press:#1D4ED8
Accent/Muted:   #1E3A5F

Success:        #10B981    Success/Muted: #064E3B
Warning:        #F59E0B    Warning/Muted: #451A03
Error:          #EF4444    Error/Hover:   #DC2626    Error/Press: #B91C1C
Error/Muted:    #450A0A

Cat/Showcase:   #7C3AED    Cat/Dynamic:   #06B6D4    Cat/Industrial: #D97706
Cat/Engineering:#059669    Cat/Experimental: #DB2777
```

---

*End of UI Redesign Visual Specification*
*For questions: refer to Section 6 (interaction patterns) and Section 9 (QSS notes) for implementation guidance.*
