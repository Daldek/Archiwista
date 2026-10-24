"""Build-free browser interface served at ``/`` and ``/static/`` (A-ADR-028).

``index.html`` loads ``src/main.js`` (ES modules: Preact and htm, no build
step and no CDN); ``vendor/`` holds the pinned third-party files listed with
their licenses in ``vendor/vendor.json``; ``styles.css`` is the shared
stylesheet.
"""
