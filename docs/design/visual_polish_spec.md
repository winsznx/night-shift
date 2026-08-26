# Night Shift Visual Polish Specification

## Source of truth

This specification extends `DESIGN.md` and PRD §34. It does not change the product's factual claims, evidence boundaries, or synthetic-data disclosure requirements.

## Signature

**Thermal trace:** thin, precise routing contours that connect an anomaly, controlled response, and durable receipt. It is a semantic system motif—not decorative background noise.

## Visual hierarchy on every product surface

1. Operational truth: what is happening now.
2. Authority truth: who is allowed to cause the next action.
3. Evidence truth: which receipt, trace, or verifier result proves it.

## Asset rules

- Use transparent assets over the native surface; avoid pre-composited white-background variants.
- Prefer AVIF for opaque photographic/illustrative assets when supported and WebP as a compatibility fallback.
- Preserve PNG for transparent assets when AVIF/WebP conversion damages alpha edges; generate responsive widths and serve via `next/image`.
- No raster text, UI screenshots, logos, or metrics in generated imagery.
