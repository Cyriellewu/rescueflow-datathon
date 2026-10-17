# RescueNYC interface system

The dashboard is an operations workspace. Its first view answers three questions in sequence: where pressure is building, which borough needs attention first, and what the selected borough's evidence supports doing.

## Layout

- A persistent workspace rail holds four destinations: Dashboard, Early warning, Historical analysis, and Policy lab.
- The dashboard starts with four citywide queue summaries, followed by a geographic map and a narrower decision column.
- The decision column ranks boroughs by next-hour probability, placing unavailable labels last. Selecting a borough on the map or in the list updates one shared borough brief.
- Replay controls and a 48-hour probability chart sit below the primary workspace. The selected hour is expressed in NYC local time.
- At narrow widths, the map precedes the attention queue and borough brief. The navigation becomes a compact rail and then a top navigation row on phones.

## Tokens

Source of truth: `app/app.css`, `:root`.

| Role | Token | Value |
| --- | --- | --- |
| Page background | `--bg` | `#101115` |
| Panel | `--panel` | `#191a20` |
| Control surface | `--surface` | `#202127` |
| Border | `--line` | `#2c2d36` |
| Primary text | `--text` | `#eeedf4` |
| Secondary text | `--muted` | `#9999aa` |
| Utility text | `--subtle` | `#8b899b` |
| Interactive accent | `--accent` | `#aa94f8` |
| Alert | `--alert` | `#f18484` |
| Watch | `--watch` | `#e8bc77` |
| Normal | `--normal` | `#75bca3` |
| Unavailable label | `--none` | `#666879` |

Risk colors communicate model state. Violet communicates controls, navigation, and selection. Risk bands always include a word, so color is never the sole signal.

Typography uses IBM Plex Sans with a system fallback. Numeric summaries and probabilities use tabular figures. Spacing follows a 4px base, with 14–20px panel gaps. Panels use a 14px radius; controls use 8px. Body controls share one 36px height, with compact 28–32px controls reserved for map tools and replay transport.

## Components and interaction

- **Primary button:** solid violet, for starting or pausing replay.
- **Secondary button / select:** neutral surface and border.
- **Icon button:** same control family, fixed square dimensions and an accessible name.
- **Map layer toggle:** compact secondary button, with persistent selected styling and `aria-pressed`.
- **Borough row:** entire row is a keyboard-operable button; its selection is shared with the map.
- **Borough brief:** queue counts, recommended action, expandable evidence and the realized replay outcome.
- **Feedback:** visible focus rings, disabled controls at timeline boundaries, brief hover/press feedback, reduced-motion support.

## Geographic reference

`app/assets/boroughs.geojson` is derived from NYC DCP's Borough Boundaries dataset (26b), simplified for screen display. Attribution and the source URL are included in the asset and the interface. This local geographic layer renders without a tile service or API key. The map supports pan, zoom, and reset.

The optional incident-density layer uses the repository's real historical ZIP aggregates; it is a reference distribution, not the selected hour's individual call locations. Hospitals come from the spatial reference API. Scenario bases are assumptions and are switched off by default. There are no observed ambulance positions in these public records.

Synthetic replay data remains explicitly labeled. No label is shown as unavailable rather than a probability. A visible error state replaces the loading state if the replay service cannot load.
