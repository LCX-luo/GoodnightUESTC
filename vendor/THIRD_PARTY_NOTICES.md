# Third-party acknowledgements and licenses

MoonUESTC is independently written integration and dashboard code, distributed under the MIT license in LICENSE.

## Referenced projects

- GoodNight, https://github.com/beichenO2/GoodNight — MIT. Referenced for current-day record checks, durable pre-submission claims, and reconciliation after uncertain submissions. The complete notice is preserved in third_party/GoodNight.LICENSE.
- UESTC-MoonCheck, https://github.com/richard297779/UESTC-MoonCheck — its supplied LICENSE contains the MIT permission and warranty text. Referenced for CAS login protocol, trusted-browser cookie, portal warmup and request schema.
- coordtransform, https://github.com/wandergis/coordtransform — MIT. WGS-84 forward-transform formulas are ported in moonuestc/coordinates.py. The complete notice is preserved in third_party/coordtransform.LICENSE.

## MoonCheck license formatting

The upstream LICENSE retrieved on 2026-10-18 (Git blob 480a7cb525870b36c6430e828fe544ab6747ce45) contains Git merge markers around two copyright notices:

- Copyright (c) 2026 MoonCheck contributors
- Copyright (c) 2026 richard297779

third_party/UESTC-MoonCheck.LICENSE retains BOTH notices and the entire MIT permission and warranty text; only the three merge-marker lines were removed. The byte-for-byte upstream file is retained as third_party/UESTC-MoonCheck.LICENSE.original. No attribution was selected over the other, no licensing permission was added, and this editorial normalization does not claim to resolve upstream authorship. SOURCE-SNAPSHOT.json preserves the referenced upstream-file hashes. The upstream projects themselves were not modified.

## Runtime dependencies

PyCryptodome, Flask, Waitress, argon2-cffi and their dependencies retain their own applicable license notices in the installed distributions. requirements.txt pins the versions; the Docker image installs their original wheels with license metadata intact.

## Coordinates and assets

The eight named campus presets use maintainer-provided AMap GCJ-02 coordinates. The original screenshot is not distributed. Coordinate conversion is an offline approximation rather than an official map calibration. Dashboard HTML, CSS, JavaScript and SVG are project code; no externally hosted fonts or JavaScript CDNs are used.

## ALTCHA registration verification

ALTCHA widget 3.4.1 is bundled locally from https://registry.npmjs.org/altcha/-/altcha-3.4.1.tgz under MIT. Its external CSS/worker build keeps resources on the instance origin; see third_party/ALTCHA.LICENSE and ALTCHA-SOURCE.json for license and exact source hashes. Official altcha Python library 2.3.0 is pinned in requirements.txt and its wheel includes its applicable license metadata. No ALTCHA Cloud or Sentinel service is called. The browser must support Web Crypto in a secure context (HTTPS or localhost).
