"""Build-free browser interface served at ``/`` and ``/static/`` (A-ADR-028).

``index.html`` loads ``src/main.js`` (ES modules: Preact and htm, no build
step and no CDN); ``vendor/`` holds the pinned third-party files listed with
their licenses in ``vendor/vendor.json``; ``nogat/`` holds Nogat's GUI kit
(the menu „Aplikacje”, the hand-off, the marks of the GUIs), copied byte for
byte with its own ``nogat-kit.json`` (A-ADR-054); ``styles.css`` is the shared
stylesheet.
"""
