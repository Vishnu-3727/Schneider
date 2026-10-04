"""Build the static GitHub Pages copy of the console into site/.

Copies every file from apps/console (incl. vendor/), vendors plotly.min.js
from the installed plotly package (same lookup as
apps/backend/main.py::console_vendor_plotly), rewrites absolute /console/
asset paths to relative ones, and pins the copy to snapshot mode via
window.JM_SNAPSHOT.

Does NOT record data: an existing site/snapshot.json is kept (copied aside
before recreating site/ and put back).

Usage:
    .venv\\Scripts\\python scripts\\demo\\build_static_site.py

Stdlib only.
"""

import pathlib
import shutil

REPO = pathlib.Path(__file__).resolve().parents[2]
CONSOLE_DIR = REPO / "apps" / "console"
SITE_DIR = REPO / "site"


def find_plotly():
    try:
        from importlib import resources

        p = resources.files("plotly") / "package_data" / "plotly.min.js"
        if pathlib.Path(str(p)).is_file():
            return pathlib.Path(str(p))
    except (ImportError, OSError, TypeError):
        pass
    import plotly

    base = pathlib.Path(plotly.__file__).resolve().parent
    return base / "package_data" / "plotly.min.js"


def main():
    kept = None
    snap_file = SITE_DIR / "snapshot.json"
    if snap_file.is_file():
        kept = snap_file.read_bytes()
        print("keeping existing site/snapshot.json (%d bytes)" % len(kept))

    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)

    for src in sorted(CONSOLE_DIR.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(CONSOLE_DIR)
        dst = SITE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    print("copied %s -> %s" % (CONSOLE_DIR, SITE_DIR))

    plotly_src = find_plotly()
    if not plotly_src.is_file():
        raise SystemExit("build_static_site: plotly.min.js not found at %s" % plotly_src)
    (SITE_DIR / "vendor").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plotly_src, SITE_DIR / "vendor" / "plotly.min.js")
    print("vendored plotly from %s" % plotly_src)

    # index.html: absolute vendor + console paths -> relative, then pin
    # snapshot mode right before the console.js script tag.
    idx = SITE_DIR / "index.html"
    html = idx.read_text(encoding="utf-8")
    html = html.replace("/console-vendor/plotly.min.js", "vendor/plotly.min.js")
    html = html.replace("/console/", "")
    tag = '<script src="console.js"'
    if tag not in html:
        raise SystemExit("build_static_site: console.js script tag not found in site/index.html")
    html = html.replace(
        tag,
        "<script>window.JM_SNAPSHOT = 'snapshot.json';</script>\n" + tag,
        1,
    )
    idx.write_text(html, encoding="utf-8")

    # Any other absolute /console/ asset path left in shipped JS/CSS.
    for f in list(SITE_DIR.glob("*.js")) + list(SITE_DIR.glob("*.css")):
        text = f.read_text(encoding="utf-8")
        if "/console/" in text:
            f.write_text(text.replace("/console/", ""), encoding="utf-8")
            print("rewrote /console/ paths in %s" % f.name)

    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    if kept is not None:
        snap_file.write_bytes(kept)
        print("restored site/snapshot.json")
    print("built %s" % SITE_DIR)


if __name__ == "__main__":
    main()
