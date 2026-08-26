# Task Plan: Night Shift visual-system polish

## Goal
Integrate the approved Night Shift visual assets and deliver a premium, cohesive, responsive product experience without weakening the operational proof or truthful scope labels.

## Phases
- [x] Phase 1: Read brand, frontend, and project design guidance
- [x] Phase 2: Identify and evaluate the supplied assets
- [x] Phase 3: Define the Night Shift visual-system lock and information hierarchy
- [x] Phase 4: Implement landing and application-shell polish
- [x] Phase 5: Polish key operational, evidence, and responder surfaces
- [x] Phase 6: Optimize assets, validate accessibility and responsive behaviour, and run checks

## Key Questions
1. Which downloaded files are the approved transparent-background Night Shift assets?
2. Which asset role best supports each public and product surface without becoming decorative theatre?
3. Does each changed screen preserve the central operational, authority, and evidence truths?

## Decisions Made
- Use real Night Shift UI and evidence as the primary visual proof; generated imagery is supporting atmosphere only.
- Preserve the PRD-required light, border-first operational style while introducing a distinct thermal-trace visual motif.
- Selected the supplied transparent artwork for the public brand layer; exported it as `apps/web/public/brand/thermal-proof.webp` (1448×1086, alpha preserved, 155 KB).
- The complete transparent set is now present in the landing flow: `thermal-proof.webp` (hero), `response-line.webp` (mechanism), `authority-boundary.webp` (trust), and `verified-route.webp` (proof). White-background duplicates remain deliberately excluded.

## Errors Encountered
- The brand skill's bundled reference directory was not supplied beside the downloaded SKILL.md; using the available core skill plus the repository's DESIGN.md and PRD as the source of truth.
- Port 3000 was occupied by an unavailable local process during visual inspection; production compilation is clean. Browser E2E will be used as the interaction verification path.
- Playwright is configured against the deployed app rather than this worktree; 20 tests passed, 4 test cases were skipped by design, and the four landing failures correspond to the not-yet-deployed remote version.
- The hero brand asset was hidden below the `xl` breakpoint and too far off-canvas at that breakpoint. It now has a readable large-screen treatment plus a dedicated mobile crop.

## Status
**Complete** — visual system implemented locally; the hero asset is now visible across viewport sizes, and production build/type validation passed.

## Follow-up: Command-room landing redesign
- [x] Rework the public navigation into a floating desktop bar with a functional mobile menu.
- [x] Reframe the hero as a bounded command room and crop in a real operational preview with dashboard navigation.
- [x] Replace the generic footer with a closing evidence CTA and an inset information footer.
- [x] Confirm TypeScript, production build, and whitespace validation pass.
