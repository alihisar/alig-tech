# alig.tech design notes

## References (principles only; nothing was copied)

Three sites were examined. Note: the pages were read at the markup level with a tool,
the rendered result was not seen in a browser; inferences about colour and spacing are not certain.

| Site | Principle taken |
| --- | --- |
| Tailscale | Sparse hero, dense navigation and footer. A single saturated accent colour, the rest neutral. |
| Linear | Sparse marketing text, dense product imagery; the density changes deliberately. The accent colour only in status indicators. |
| PostgreSQL | Content is ordered by urgency, dates and versions on a single line, no decoration. Trust comes from simplicity. |

Resulting conclusion: show the product immediately (a working console in the hero), increase the density
from top to bottom, tie the accent colour to meaning.

## Design plan (written before coding, reviewed afterwards)

### Defaults noticed in the first draft and changed

| What came to mind first | Why it changed | Instead |
| --- | --- | --- |
| Light direction: cream background, high-contrast serif, earth-tone accent | The most common pattern in generated sites | Cool white background, navy ink, the accent only meaning "human approval" |
| Dark direction: near-black background, a single bright green accent | A pattern in the same way | Navy-slate background, the same semantic amber |
| Hero: a big number + gradient | Not specific to the subject | A working example cluster: stop the leader, watch the agent's finding and the hash-chained record |
| A grid of three equal cards | Forces all content into the same mould | Rows and tables; the form is whatever the content is |
| A small lowercase label above, dot-separated meta, an arrow mark | A template pattern | Not used |
| Monospace on every label | A template pattern | Monospace only in real terminal output |

### Shared principles

- Amber (#f2b441) is the single accent and has a single meaning: a human
  has to make a decision (an approval button, the approval step in the flow, the CTA). It is not used elsewhere.
- Status colours (green/red) only in the console output, where they carry meaning.
- The single memorable element of this page is the hero console. The rest is calm.
- Motion only in response to the user's action: when the leader is stopped, the event flow
  appears in order. There is no animation that appears on scrolling. With `prefers-reduced-motion`
  on, the flow completes instantly.
- No gradients, glass effects, blur, shadows, emoji or uppercase transformation
  (`ci/check_banned.py` checks these).
- Copy: first person plural, concrete, short.

### Direction A: Console (dark)

- Colour: background #1b2433, surface #243044, line #3a4a63, text #e4e9f1,
  secondary text #9aa8bf, accent #f2b441.
- Type: Schibsted Grotesk (headings and body, a single family), Red Hat Mono (console only).
- Layout: left-aligned; in the hero, text on the left, console on the right (5/7). Section
  headings above the content. Services and tiers as table rows.
- Corners: 4 px for buttons and fields, 8 px for the console. No shadows.

### Direction B: Report (light)

- Colour: background #ffffff, ink #16233b (navy), secondary #4d5b73,
  line #cfd6e0, accent #f2b441 (as a background, with navy text).
- Type: Source Serif 4 (headings and body), Red Hat Mono (console only).
- Layout: audit report layout. The heading on top at full width, the console below
  at full width as a "figure". Section headings in a left margin column (sticky),
  content on the right. Links navy, with an amber underline.
- Corners: none, 1 px lines.

## Logo and favicon

- Wordmark: "alig.tech", in the direction's own typeface, a single weight.
- Favicon 1 (`site/assets/favicon.svg`): one leader, two standbys (a cluster).
- Favicon 2 (`site/assets/favicon-alt.svg`): three log lines, the first amber.
