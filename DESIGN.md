---
name: Mandate Mesh
description: Deterministic Constraint Enforcement & Cryptographic Telemetry Console
colors:
  primary: "#34d399"
  neutral-bg: "#0b0d11"
  neutral-panel: "#11141a"
  neutral-surface: "#171b23"
  neutral-recessed: "#0e1015"
  border-line: "#20242e"
  border-bright: "#2d3342"
  text-phosphor: "#e2e5eb"
  text-secondary: "#8b93a4"
  text-muted: "#565d6c"
  accent-threat: "#d03b3b"
  accent-escalation: "#d97706"
  accent-steel: "#94a3b8"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.0rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "JetBrains Mono, Consolas, Monaco, monospace"
    fontSize: "0.8rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.06em"
  body:
    fontFamily: "JetBrains Mono, Consolas, Monaco, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "normal"
  label:
    fontFamily: "JetBrains Mono, Consolas, Monaco, monospace"
    fontSize: "0.68rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.05em"
rounded:
  none: "0px"
  sm: "0px"
  md: "0px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "16px"
components:
  button-primary:
    backgroundColor: "{colors.text-phosphor}"
    textColor: "{colors.neutral-bg}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  button-primary-hover:
    backgroundColor: "#ffffff"
  button-success:
    backgroundColor: "{colors.primary}"
    textColor: "#052414"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  button-danger:
    backgroundColor: "{colors.neutral-surface}"
    textColor: "{colors.accent-threat}"
    rounded: "{rounded.none}"
    padding: "6px 12px"
  badge-proof:
    backgroundColor: "rgba(52, 211, 153, 0.12)"
    textColor: "{colors.primary}"
    rounded: "{rounded.none}"
    padding: "2px 6px"
---

# Design System: Mandate Mesh

## Overview

**Creative North Star: "The Declassified Telemetry Console"**

Mandate Mesh presents an uncompromising, high-assurance operational environment modeled on tactical aerospace telemetry consoles and cryptographic hardware security modules. The visual aesthetic is deliberately restrained, utilitarian, and high-density: every pixel is dedicated to verifiable state, cryptographic proofs, and deterministic guardrail status.

Surfaces exist on a deep obsidian foundation (`#0b0d11`) with cool chassis slate layers (`#11141a`, `#171b23`). Rather than relying on gratuitous glowing borders or neon distractions, the interface uses measured 1px hairline dividers (`#20242e`), high-legibility phosphor white typography (`#e2e5eb`), and precision-calibrated functional accents. Cryptographic state is communicated through unambiguous semantic states—verified green proofs, adversarial crimson blocks, and human-in-the-loop amber escalations.

**Key Characteristics:**
- Strict 90-degree mechanical geometry (`0px` border-radius universally).
- High information density with monospaced data alignment for SHA-256 digests and currency values.
- Flat structural depth through 1px border contrast and tonal substrate stepping.
- Restrained, purposeful color economy (accents appear exclusively on verifiable state transitions).

## Colors

The palette is anchored in deep cold neutrals with desaturated functional accents, engineered for prolonged monitoring and zero visual glare.

### Primary
- **Emerald Proof** (`#34d399`): Indicates cryptographically verified transitions, matching signatures, and settled payment mandates.

### Secondary
- **Threat Crimson** (`#d03b3b`): Applied strictly to blocked adversarial attacks, signature failures, and budget violations.

### Tertiary
- **Escalation Amber** (`#d97706`): Used for pending human-in-the-loop (HITL) authorization gates and budget limit overrides.
- **Telemetry Steel** (`#94a3b8`): Informational metadata, merchant IDs, and protocol parameters.

### Neutral
- **Terminal Obsidian** (`#0b0d11`): Base application canvas background.
- **Panel Charcoal** (`#11141a`): Structural module card container substrate.
- **Surface Slate** (`#171b23`): Interactive surface buttons, active tabs, and table header rows.
- **Recessed Well** (`#0e1015`): Monospace log output, code blocks, and hash container backgrounds.
- **Hairline Divider** (`#20242e`): Standard 1px perimeter and module partition borders.
- **Phosphor White** (`#e2e5eb`): High-contrast primary reading typography.
- **Cold Secondary** (`#8b93a4`): Field labels, table headers, and secondary metrics.
- **Muted Dim** (`#565d6c`): Disabled states, inactive icons, and supplementary metadata.

### Named Rules
**The Phosphor Economy Rule.** Functional accent colors (`#34d399`, `#d03b3b`, `#d97706`) must occupy $\le 5\%$ of any viewport. Chromatic intensity signals a state change; the resting canvas is cold monochrome slate.

**The Hash Distinctness Rule.** SHA-256 cryptographic digests, ECDSA signatures, and UUIDs are rendered in monospace typography inside recessed substrate wells (`#0e1015`) with a 1px border.

## Typography

**Display/Macro Font:** `Inter`, system-ui, -apple-system, sans-serif
**Data/Mono Font:** `JetBrains Mono`, Consolas, Monaco, monospace

**Character:** Macro navigation and module headers utilize tight, geometric sans-serif for instant scanning, while 100% of data, payloads, financial figures, and lifecycle states use tabular monospace fonts.

### Hierarchy
- **Display** (Bold 700, `1.25rem` / 20px, line-height `1.2`, letter-spacing `-0.02em`): Global command bar title and system mode.
- **Headline** (Bold 700, `1.0rem` / 16px, line-height `1.3`, letter-spacing `-0.01em`): Section headings and dialog titles.
- **Title** (Bold 700, `0.8rem` / 13px, line-height `1.4`, letter-spacing `0.06em`, uppercase): Panel headers and category markers.
- **Body** (Regular 400, `13px`, line-height `1.45`): Telemetry logs, chat transcript, table rows, and status descriptions.
- **Label** (SemiBold 600, `0.68rem` / 11px, letter-spacing `0.05em`, uppercase): Table column headers, status badges, and metric unit tags.

### Named Rules
**The Tabular Numbers Rule.** All prices (paise / INR), timestamps (IST), and hash digests must render using monospace fonts with tabular alignment to ensure vertical column stability.

## Layout

The control tower utilizes an operational split grid designed for simultaneous agent interaction and cryptographic telemetry tracking:
- **Global Container:** Constrained max-width (`1720px`) with consistent `16px` padding and `14px` module gaps.
- **Command Deck Header:** Fixed 48px height telemetry strip housing live gateway status, ledger height, active session, and purge actions.
- **Primary Grid:** Responsive asymmetric two-column layout (`440px` left interactive agent chat rail, `1fr` right multi-module telemetry canvas).
- **Responsive Behavior:** Below `1240px`, collapses to a single continuous operational column without loss of functionality.

## Elevation & Depth

**Flat-By-Default Invariant.** Mandate Mesh uses zero blur drop-shadows. Depth is conveyed strictly through structural layering and 1px border contrast:
1. **Base Layer (`#0b0d11`):** Global terminal canvas.
2. **Chassis Layer (`#11141a`):** Module panel cards with 1px border (`#20242e`).
3. **Elevated Surface Layer (`#171b23`):** Action buttons, interactive chips, and active tabs with 1px border (`#2d3342`).
4. **Recessed Wells (`#0e1015`):** Monospace telemetry blocks and hash chains with inset border (`#161922`).

### Named Rules
**The No-Shadow Doctrine.** No `box-shadow` or `filter: drop-shadow` is permitted on containers or surfaces. Depth is defined solely by perimeter borders and background contrast.

## Shapes

- **Corner Radius:** Universally `0px`. Every button, card, input, badge, modal, tooltip, and avatar features crisp 90-degree corners.
- **Dividers:** Clean 1px solid lines (`#20242e`) separating data rows and module headers.
- **Borders:** 1px solid with hover states stepping from `#20242e` $\rightarrow$ `#2d3342` $\rightarrow$ `#e2e5eb`.

## Components

### Buttons
- **Shape:** `0px` border-radius, `6px 12px` padding, uppercase monospace (`0.75rem`), letter-spacing `0.05em`.
- **Primary:** Phosphor white background (`#e2e5eb`), dark text (`#0b0d11`), hover transitions to `#ffffff`.
- **Success:** Emerald green (`#34d399`), dark emerald text (`#052414`), hover transitions to `#4ade80`.
- **Danger:** Subtle slate surface (`#171b23`) with crimson text (`#d03b3b`) and border `rgba(208, 59, 59, 0.3)`.
- **Secondary:** Surface slate (`#171b23`) with secondary text (`#8b93a4`) and border (`#20242e`).

### Badges / Status Chips
- **Style:** Compact `2px 6px` padding, `0.68rem` uppercase monospace, `1px` border.
- **Proof / Verified:** Emerald background tint `rgba(52, 211, 153, 0.12)`, emerald text (`#34d399`), border `rgba(52, 211, 153, 0.35)`.
- **Threat / Blocked:** Crimson background tint `rgba(208, 59, 59, 0.12)`, crimson text (`#d03b3b`), border `rgba(208, 59, 59, 0.35)`.
- **Neutral / Steel:** Steel background tint `rgba(148, 163, 184, 0.08)`, text (`#e2e5eb`), border (`#2d3342`).

### Cards / Panels
- **Container:** Background `#11141a`, border `1px solid #20242e`, internal padding `14px`.
- **Header:** Bottom border `1px solid #20242e`, padding-bottom `8px`, title in bold uppercase monospace (`0.8rem`).

### Inputs / Terminal Prompts
- **Style:** Background `#0a0c10`, border `1px solid #20242e`, text `#e2e5eb`, font `JetBrains Mono` (`13px`).
- **Focus:** Border transitions to `#e2e5eb` with zero outline or blur.

### Signature Component: Mandate State Visualizer Pipeline
- **Structure:** 5-hop sequential telemetry rail (Intent $\rightarrow$ Quote Routing $\rightarrow$ Mandate $\rightarrow$ Razorpay Capture $\rightarrow$ Audit Ledger).
- **Interactive State:** Sequential checkmark verification, 1-click clipboard digest copying (`[ COPY ]` $\rightarrow$ `✓ COPIED`), and pulse status indicator.

## Do's and Don'ts

### Do:
- **Do** enforce `border-radius: 0px` across every DOM element.
- **Do** render all currency calculations as integer paise formatted to INR with two decimal places (e.g. `₹1,249.00`).
- **Do** format all ledger timestamps in Indian Standard Time (IST) with explicit `+05:30` offset.
- **Do** truncate SHA-256 hashes cleanly (e.g. `0x3a8f...9d12`) with full string copy-to-clipboard affordances.
- **Do** preserve the 48px compact Command Bar height for maximum vertical canvas economy.

### Don't:
- **Don't** introduce rounded corners, pill badges, or circular buttons.
- **Don't** add decorative ambient glow, neon scanlines, or vibrating CRT animations that distract from telemetry reading.
- **Don't** use floating-point math for any financial representation.
- **Don't** use generic color names; rely on the semantic tokens defined in `index.css`.
- **Don't** display unverified LLM output as authoritative state without passing through the cryptographic state machine.
