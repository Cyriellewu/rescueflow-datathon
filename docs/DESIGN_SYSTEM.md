# RescueNYC visual system

The interface keeps a horizontal navigation, a primary city map, a right-hand summary and priority list, and the existing history and evidence sections. `app/design.css` is the source of truth for presentation.

## Visual direction

Use a near-black page with charcoal surfaces, warm white text, and a clear red accent, amber watch states and teal normal states. Create hierarchy through typography, whitespace and alignment. Avoid nested cards, pervasive borders and decorative icons. The map and data remain the visual focus.

| Role | Token | Value |
| --- | --- | --- |
| Page | `--bg` | `#0c0c0d` |
| Surface | `--panel` | `#171719` |
| Divider | `--line` | `#2a292d` |
| Primary text | `--text` | `#f0eeea` |
| Secondary text | `--muted` | `#b6b0b0` |
| Supporting text | `--quiet` | `#a69c9c` |
| Accent | `--accent` | `#e56863` |
| Alert | `--alert` | `#ff7875` |
| Watch | `--watch` | `#e9bd56` |
| Normal | `--normal` | `#78c9b0` |

Inter is the main typeface, with system fallbacks. Page titles use 40px (36px on small screens) with restrained weight; section titles use 18px; introductory descriptions use 16px; body text uses 15px; tabs and controls use 13–15px. Supporting information stays at 12–14px, including on phones. Figures use tabular numerals. Panels use a 20px radius, reduced to 17px on phones. Panel gutters are normally 22–24px.

## Components

- Navigation remains at the top at every width; at 320px its four destinations form two rows to preserve readable labels. The active destination uses warm white within a charcoal capsule.
- Primary replay buttons use white. Secondary controls use neutral surfaces. Map reset is a text action. All controls share focus and press behavior.
- Summary figures use a two-column grid and internal dividers, without additional card shells.
- Borough priorities use numbered rows, small risk bars and explicit band labels. Each row is a keyboard-operable button.
- The map starts closer to NYC: an additional half zoom level on larger maps and a quarter level on maps under 500px wide, with reduced fitting padding. Reset restores this same responsive view. The map uses low-opacity borough fills and fine boundaries. Alert regions have a separate red outline with a gentle 1.6-second opacity cycle to indicate their state; fills and labels stay fixed. This slower cadence is intentional for a persistent status indication rather than an interaction transition. Selected or hovered regions receive a stronger static outline. Reduced-motion preferences retain a static red alert outline.
- Risk history uses a single red intensity scale. Realized-stress ticks remain amber and keep their separate legend.
- Borough evidence is a two-column ledger: borough name, pressure and both probabilities on the left; the recommendation, 24-hour trend and current situation on the right. On small screens these columns stack, retaining identity and probabilities before the narrative.

At narrower widths, navigation stays above the content; the map is followed by the same summary and priority information. Reduced-motion preferences suppress movement. Model, scenario, replay and provenance semantics remain unchanged.

## Readability and color

Red (`#e56863`) identifies brand selection and comparative charts. Alerts use a brighter red (`#ff7875`); Watch is amber (`#e9bd56`); Normal is teal (`#78c9b0`). Explicit band labels accompany every semantic color. The citywide alert count and its label turn red only when at least one borough is on alert. Primary actions remain warm white.

Primary, secondary and supporting text retain their accessible contrast against the charcoal surface. The revised red, amber and teal tokens are checked for at least 4.5:1 text contrast on `#171719`; these token checks are not a claim of full accessibility conformance.

Chart labels use 13px, and map region names use 14px over a dark backing for geographic readability. Text on the darker travel-matrix cells switches to warm white. Interactive controls have larger hit areas, and navigation reflows without moving into a sidebar.

## Dashboard content hierarchy

The main heading is simply Dashboard and the map is titled Next-hour risk. Introductory eyebrow copy, repeated map subtitles and the duplicate Recorded moments selector are removed from this view; the Early warning page retains recorded moment controls.

Next-hour queue risk and onset risk sit below each borough name and its pressure indicator, with plain-language descriptions. The right column starts with the recommended action, followed by the 24-hour trend and current situation. Repeated band labels, the Why disclosure and Afterwards text are removed from the borough ledger; band labels remain on the map and priority list. Reading guidance and collapsed simulation context follow the ledger in the same column alignment. Project, keyboard and scoring metadata align with those columns below, keeping operational content above technical metadata.

## Time on borough trends

The 24-hour sparkline includes NYC local time labels along its axis. Every amber marker contains its exact date and hour in a tooltip, and a visible Stressed hours row below the graph lists those dates and times. Consecutive hours are consolidated into an inclusive range and ranges split at midnight. At narrow widths only the endpoint axis labels remain, while the complete marked-hour list wraps without truncation. An hour with no prior history displays a single risk point and one timestamp.
