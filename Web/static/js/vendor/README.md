# Vendored 3D dependencies (THE ARMORY deep-dive)

Committed in-repo so the app boots with zero network (Atlas CSP is
`default-src 'self'` and vendored deps are the house rule — see the deployment notes).
Loaded only by `armory3d.js`, which is itself lazy-imported the first time a
viewer opens the 3D rack — the core app never pulls three.js.

- **three.module.js** — three.js **r160** (npm `three@0.160.0`),
  `build/three.module.js`, verbatim.
- **OrbitControls.js** — `three@0.160.0` `examples/jsm/controls/OrbitControls.js`,
  with ONE change: its bare `import { ... } from 'three'` was rewritten to
  `from './three.module.js'`. A bare specifier needs an import-map, and an
  inline `<script type="importmap">` is blocked by the app's CSP — a relative
  import keeps the zero-CSP-delta path.

To upgrade: replace both files from the same three version, then re-apply the
OrbitControls import rewrite (`from 'three'` → `from './three.module.js'`).


## Chart.js 4.4.1 (`chart.umd.min.js`)

The UMD build from `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`
(sha256 `d2af8974e95271638772e9e9524db5b9a6f58d6ec2d5d781400447b4a31c681e` as fetched,
2026-09-02; the trailing `sourceMappingURL` line is removed because the map is not
shipped). MIT — `LICENSE.chart.js.md`. Vendored rather than loaded from a CDN because
the CSP is `default-src 'self'` and the design notes forbids runtime CDNs; loaded lazily by
`static/js/charts.js` the first time a native watching draws (`window.Chart`).
