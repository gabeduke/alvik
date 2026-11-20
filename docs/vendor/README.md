# Vendored libraries

Copied in as plain files (no bundler). To update: `npm pack three@<version>`, unpack, copy the same files.

| Folder | What | Version | Licence |
|---|---|---|---|
| `three/three.module.min.js` | three.js (`build/three.module.min.js`) | 0.170.0 | MIT, `three/LICENSE` |
| `three/loaders/GLTFLoader.js` | `examples/jsm/loaders/GLTFLoader.js` | 0.170.0 | MIT |
| `three/utils/BufferGeometryUtils.js` | `examples/jsm/utils/BufferGeometryUtils.js` (GLTFLoader imports it) | 0.170.0 | MIT |

The addons import `'three'`; the import map in `index.html` points that at `vendor/three/three.module.min.js`.
