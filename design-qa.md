**Comparison Target**

- Source visual truth: `/var/folders/w9/0b6b385d5h1fq5h6kdz202mm0000gn/T/codex-clipboard-8eb61462-bc69-4ccb-9f19-fc32c982aecd.png`
- Implementation evidence: browser-rendered Portal Hub capture, `http://localhost:4173/`, captured 2026-07-21 during this QA run (desktop viewport, running-services view).
- State: two running local services; no modal open.

**Findings**

- No actionable P0/P1/P2 differences for the requested simplification. The service cards now show only the operational summary: status, URL, port, PID, process, last check, tags, and actions. Project path and startup command are no longer rendered in the default card view.
- The source image showed the two removed values consuming most of each card's height. The revised cards retain the same visual tokens, type hierarchy, and controls, while reducing the default card height and using a four-column metadata grid.

**Required Fidelity Surfaces**

- Fonts and typography: existing Inter/system Chinese fallback stack and hierarchy are retained; long service names and URLs still wrap safely.
- Spacing and layout rhythm: card detail blocks were removed, the internal gap is consistent, and the four summary cells align across the card width.
- Colors and visual tokens: existing neutral panel, green running state, and control colors are unchanged.
- Image quality and asset fidelity: no image or icon assets are present in this card area.
- Copy and content: the search hint no longer advertises paths; startup configuration remains available only in the edit flow.

**Implementation Checklist**

- [x] Hide project path from the default service card.
- [x] Hide startup command from the default service card.
- [x] Preserve both fields in the editor so existing start/restart behavior remains intact.
- [x] Verify the rendered running-services view and browser console.

**Follow-up Polish**

- [P3] If action density becomes a concern with many cards, the secondary actions can later move into an overflow menu.

**Comparison History**

1. Removed the two diagnostic blocks, reduced the metadata grid from five to four cells, and shortened the card's minimum height.
2. Re-rendered the running-services view. The card contents are compact, no path or command text is visible, and no console errors were reported.

final result: passed
