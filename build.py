#!/usr/bin/env python3
"""Build the site: validate the data, inline it with the world geometry into
src/template.html and write site/index.html (one self-contained file).

Usage:  python3 build.py [--date YYYY-MM-DD]

Python 3 standard library only. Paths are resolved from this file's location.
Exits non-zero on validation errors or when the wording check finds text that
should not be published.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
TEMPLATE = os.path.join(ROOT, "src", "template.html")
TOPO = os.path.join(ROOT, "vendor", "countries-50m.json")
OUT = os.path.join(ROOT, "site", "index.html")

DATA_MARK = "/*__APP_DATA__*/"
TOPO_MARK = "/*__WORLD_TOPOJSON__*/"

TARGETS = {"xenon", "argon", "both", "materials"}
KINDS = {"lab", "in-situ"}                      # shown as "R&D setup" and "Experiment"
PHASES = {"running", "construction", "completed", "unknown"}
PROVENANCE = {"opened", "abstract", "unchecked"}
REF_TYPES = {"paper", "arXiv", "thesis", "talk", "poster", "web"}
SIGNALS = {"S1", "S2", "both"}
MEDIA = {"xenon", "argon", "both"}
EVIDENCE = {"established", "supported", "hypothesised"}
IMPORTANCE = {"dominant", "significant", "sub-dominant", "unknown", "contested"}
TAG_IDS = set("ABCDEFGHI")
# Regions the detector drawing in src/template.html has anchors for (REG there).
REGIONS = {
    "top_pmt_array", "top_pmt_window", "top_screen", "gas_gap", "anode", "liquid_surface",
    "extraction_region", "gate", "bulk_liquid", "impurities_in_bulk", "ptfe_wall",
    "wall_charge_insensitive", "field_shaping_rings", "cathode", "below_cathode", "bottom_screen",
    "bottom_pmt_window", "bottom_pmt_array", "outer_volume", "cryostat", "wall_reflector_tpb",
}
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED_IDS = {"map", "list", "detector", "about"}

# Working-note wording that must not be published (checked on every text field).
WORDING_RE = re.compile(r"\b(seed|orchestrator|enrichment|extractor|agents?|I opened|I found|deck|doc table|not re-checked)\b", re.I)
WORDING_SKIP_KEYS = {"id", "url", "slides_url", "provenance", "type", "region", "extra_regions", "setups", "categories",
                     "signal", "evidence", "importance", "target", "kind", "phase", "country_code", "tags"}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def is_url(u):
    return isinstance(u, str) and re.match(r"^https?://[^\s<>\"']+$", u) is not None


def check_refs(refs, where, errors):
    if not isinstance(refs, list):
        errors.append("%s: references must be a list" % where)
        return 0
    for i, r in enumerate(refs):
        if not isinstance(r, dict) or not r.get("title"):
            errors.append("%s: reference %d has no title" % (where, i))
            continue
        if r.get("type") not in REF_TYPES:
            errors.append("%s: reference %d has type %r (allowed: %s)" % (where, i, r.get("type"), ", ".join(sorted(REF_TYPES))))
        if r.get("url") is not None and not is_url(r.get("url")):
            errors.append("%s: reference %d url is not an http(s) link" % (where, i))
    return len(refs)


def validate(setups, sources_doc, meta):
    errors = []
    ids = collections.Counter(s.get("id") for s in setups)
    for sid, n in ids.items():
        if n > 1:
            errors.append("setup id %r is used %d times" % (sid, n))
    for s in setups:
        sid = s.get("id")
        w = "setup %s" % sid
        if not isinstance(sid, str) or not ID_RE.match(sid) or sid in RESERVED_IDS or sid.startswith("src-"):
            errors.append("%s: id must be lower-case letters, digits and hyphens, and not a view name" % w)
        for key in ("name", "kind", "target", "phase", "provenance"):
            if not s.get(key):
                errors.append("%s: missing %s" % (w, key))
        if s.get("kind") not in KINDS:
            errors.append("%s: kind %r (allowed: %s)" % (w, s.get("kind"), ", ".join(sorted(KINDS))))
        if s.get("target") not in TARGETS:
            errors.append("%s: target %r" % (w, s.get("target")))
        if s.get("phase") not in PHASES:
            errors.append("%s: phase %r" % (w, s.get("phase")))
        if s.get("provenance") not in PROVENANCE:
            errors.append("%s: provenance %r" % (w, s.get("provenance")))
        lat, lon = s.get("lat"), s.get("lon")
        if (lat is None) != (lon is None):
            errors.append("%s: give both lat and lon, or neither" % w)
        elif lat is not None and not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                                      and -90 <= lat <= 90 and -180 <= lon <= 180):
            errors.append("%s: lat/lon out of range" % w)
        for t in s.get("tags") or []:
            if t not in TAG_IDS:
                errors.append("%s: tag %r is not one of A-I" % (w, t))
        n_refs = check_refs(s.get("references") or [], w, errors)
        for i, m in enumerate(s.get("measurements") or []):
            if not isinstance(m, dict) or not m.get("what"):
                errors.append("%s: measurement %d has no 'what'" % (w, i))
                continue
            ref = m.get("ref")
            if ref is not None and not (isinstance(ref, int) and 0 <= ref < n_refs):
                errors.append("%s: measurement %d ref %r is not an index into references" % (w, i, ref))
        for key in ("people", "cited_authors", "mechanisms", "caveats"):
            if s.get(key) is not None and not isinstance(s.get(key), list):
                errors.append("%s: %s must be a list" % (w, key))

    sources = sources_doc.get("sources") or []
    sids = collections.Counter(x.get("id") for x in sources)
    for sid, n in sids.items():
        if n > 1:
            errors.append("source id %r is used %d times" % (sid, n))
    for x in sources:
        w = "source %s" % x.get("id")
        if not isinstance(x.get("id"), str) or not ID_RE.match(x.get("id")):
            errors.append("%s: id must be lower-case letters, digits and hyphens" % w)
        if not x.get("name"):
            errors.append("%s: missing name" % w)
        if x.get("signal") not in SIGNALS:
            errors.append("%s: signal %r" % (w, x.get("signal")))
        if x.get("medium") not in MEDIA:
            errors.append("%s: medium %r" % (w, x.get("medium")))
        if x.get("evidence") not in EVIDENCE:
            errors.append("%s: evidence %r" % (w, x.get("evidence")))
        if x.get("importance") is not None and x.get("importance") not in IMPORTANCE:
            errors.append("%s: importance %r" % (w, x.get("importance")))
        for reg in [x.get("region")] + list(x.get("extra_regions") or []):
            if reg not in REGIONS:
                errors.append("%s: region %r is not drawn in the detector figure" % (w, reg))
        for sid in x.get("setups") or []:
            if sid not in ids:
                errors.append("%s: setup id %r does not exist in data/setups.json" % (w, sid))
        n_refs = check_refs(x.get("references") or [], w, errors)
        for i, k in enumerate(x.get("key_numbers") or []):
            if not isinstance(k, dict) or not k.get("text"):
                errors.append("%s: key number %d has no text" % (w, i))
                continue
            ref = k.get("ref")
            if ref is not None and not (isinstance(ref, int) and 0 <= ref < n_refs):
                errors.append("%s: key number %d ref %r is not an index into references" % (w, i, ref))
    check_refs(sources_doc.get("pairing_references") or [], "pairing_references", errors)

    cats = sources_doc.get("categories") or []
    cat_ids = collections.Counter(c.get("id") for c in cats)
    for c in cats:
        w = "category %s" % c.get("id")
        if not isinstance(c.get("id"), str) or not ID_RE.match(c.get("id")):
            errors.append("%s: id must be lower-case letters, digits and hyphens" % w)
        if cat_ids[c.get("id")] > 1:
            errors.append("%s: id is used more than once" % w)
        if not c.get("name"):
            errors.append("%s: missing name" % w)
        if c.get("signal") not in ("S1", "S2"):
            errors.append("%s: signal %r (allowed: S1, S2)" % (w, c.get("signal")))
        if not c.get("sources"):
            errors.append("%s: has no sources" % w)
        for sid in c.get("sources") or []:
            if sid not in sids:
                errors.append("%s: source id %r does not exist" % (w, sid))
    if cats:
        for x in sources:
            mine = x.get("categories") or []
            if not mine:
                errors.append("source %s: is in no category" % x.get("id"))
            for cid in mine:
                if cid not in cat_ids:
                    errors.append("source %s: category id %r does not exist" % (x.get("id"), cid))
                elif x.get("id") not in (next(c for c in cats if c.get("id") == cid).get("sources") or []):
                    errors.append("source %s: lists category %r, but that category does not list it" % (x.get("id"), cid))
        for c in cats:
            for sid in c.get("sources") or []:
                src = next((x for x in sources if x.get("id") == sid), None)
                if src is not None and c.get("id") not in (src.get("categories") or []):
                    errors.append("category %s: lists source %r, but that source does not list the category" % (c.get("id"), sid))

    tag_ids = [t.get("id") for t in meta.get("tags") or []]
    if sorted(tag_ids) != sorted(TAG_IDS):
        errors.append("meta.json: tags must be exactly A-I, each once")
    for t in meta.get("tags") or []:
        if not t.get("name"):
            errors.append("meta.json: tag %r has no name" % t.get("id"))
    for l in meta.get("leads") or []:
        if not l.get("name"):
            errors.append("meta.json: a lead has no name")
    return errors


def find_wording(obj, where, key=None, out=None):
    """Collect (where, field, excerpt) for every text field that matches WORDING_RE."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        label = where
        if key is None and isinstance(obj.get("id"), str):
            label = "%s %s" % (where, obj["id"])
        for k, v in obj.items():
            if k in WORDING_SKIP_KEYS:
                continue
            find_wording(v, label, (key + "." + k) if key else k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_wording(v, where, ("%s[%d]" % (key, i)) if key else None, out)
    elif isinstance(obj, str):
        m = WORDING_RE.search(obj)
        if m:
            a = max(0, m.start() - 40)
            out.append((where, key or "?", obj[a:m.end() + 40].replace("\n", " ")))
    return out


def _dp(points, eps2):
    """Douglas-Peucker on a list of (x, y); keeps both end points. Iterative."""
    n = len(points)
    if n < 3:
        return points
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if den == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / den
                t = 0 if t < 0 else 1 if t > 1 else t
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, bi = d, i
        if best > eps2 and bi > 0:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [pt for pt, k in zip(points, keep) if k]


def simplify_topology(topo, eps_deg=0.02, min_island_deg=0.2):
    """Shrink the world geometry for the page: drop islands smaller than min_island_deg
    and thin every arc. Shared borders stay shared, so no gaps open."""
    sx, sy = topo["transform"]["scale"]
    dec = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for d in arc:
            x += d[0]
            y += d[1]
            pts.append((x, y))
        dec.append(pts)
    obj = topo["objects"]["countries"]
    use = collections.Counter()

    def rings_of(g):
        if g.get("type") == "Polygon":
            return [g["arcs"]]
        if g.get("type") == "MultiPolygon":
            return g["arcs"]
        return []

    for g in obj["geometries"]:
        for poly in rings_of(g):
            for ring in poly:
                for i in ring:
                    use[i if i >= 0 else ~i] += 1

    def tiny(poly):
        ring = poly[0]
        if len(ring) != 1:
            return False
        i = ring[0] if ring[0] >= 0 else ~ring[0]
        if use[i] != 1:
            return False
        xs = [pt[0] for pt in dec[i]]
        ys = [pt[1] for pt in dec[i]]
        return (max(xs) - min(xs)) * sx < min_island_deg and (max(ys) - min(ys)) * sy < min_island_deg

    geoms = []
    for g in obj["geometries"]:
        polys = [poly for poly in rings_of(g) if not tiny(poly)]
        if not polys:
            continue
        g2 = dict(g)
        if len(polys) == 1:
            g2["type"], g2["arcs"] = "Polygon", polys[0]
        else:
            g2["type"], g2["arcs"] = "MultiPolygon", polys
        geoms.append(g2)
    remap, new_arcs = {}, []

    def idx(i):
        j = i if i >= 0 else ~i
        if j not in remap:
            pts = dec[j]
            deg = [(px * sx, py * sy) for px, py in pts]
            kept = _dp(deg, eps_deg * eps_deg)
            if len(kept) < 4 and pts[0] == pts[-1] and len(pts) >= 4:      # keep closed rings as rings
                step = max(1, (len(pts) - 1) // 3)
                kept = [deg[0], deg[step], deg[min(len(pts) - 2, 2 * step)], deg[-1]]
            qp = [(int(round(px / sx)), int(round(py / sy))) for px, py in kept]
            enc, lx, ly = [], 0, 0
            for qx, qy in qp:
                enc.append([qx - lx, qy - ly])
                lx, ly = qx, qy
            remap[j] = len(new_arcs)
            new_arcs.append(enc)
        return remap[j] if i >= 0 else ~remap[j]

    for g in geoms:
        if g["type"] == "Polygon":
            g["arcs"] = [[idx(i) for i in ring] for ring in g["arcs"]]
        else:
            g["arcs"] = [[[idx(i) for i in ring] for ring in poly] for poly in g["arcs"]]
    return {"type": "Topology", "transform": topo["transform"], "arcs": new_arcs,
            "objects": {"countries": {"type": "GeometryCollection", "geometries": geoms}}}


def check_svg_sizing(template):
    """Guard: a rule such as `.figure svg { width: 100% }` also stretches every small icon inside
    that container. Returns the offending selectors (bare `svg` reached by a descendant combinator)."""
    css = "\n".join(re.findall(r"<style>(.*?)</style>", template, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    bad = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if not re.search(r"(?<![-\w])width\s*:\s*100%", m.group(2)):
            continue
        for sel in m.group(1).split(","):
            sel = sel.strip()
            if re.search(r"[^\s>+~]\s+svg$", sel):
                bad.append(sel)
    return bad


def inline_json(obj):
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # Safe inside <script>: no "</", no "<!--", no raw line separators.
    return (s.replace("</", "<\\/").replace("<!--", "\\u003c!--")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def main():
    ap = argparse.ArgumentParser(description="Build site/index.html from data/ and src/template.html.")
    ap.add_argument("--date", default=None, help="build date shown on the page, YYYY-MM-DD (default: today)")
    args = ap.parse_args()
    build_date = args.date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", build_date):
        sys.exit("build.py: --date must be YYYY-MM-DD")

    try:
        setups = load(os.path.join(DATA, "setups.json")).get("setups") or []
        sources_doc = load(os.path.join(DATA, "sources.json"))
        meta = load(os.path.join(DATA, "meta.json"))
        topo = load(TOPO)
        with open(TEMPLATE, encoding="utf-8") as fh:
            template = fh.read()
    except (OSError, ValueError) as exc:
        sys.exit("build.py: cannot read input: %s" % exc)
    for mark in (DATA_MARK, TOPO_MARK):
        if template.count(mark) != 1:
            sys.exit("build.py: src/template.html must contain %s exactly once" % mark)

    errors = validate(setups, sources_doc, meta)
    errors += ["src/template.html sizes a bare svg to 100% under a container: " + sel for sel in check_svg_sizing(template)]
    wording = []
    for x in setups:
        find_wording(x, "setup", None, wording)
    for x in sources_doc.get("sources") or []:
        find_wording(x, "source", None, wording)
    find_wording({k: v for k, v in sources_doc.items() if k != "sources"}, "sources.json", None, wording)
    find_wording(meta, "meta.json", None, wording)

    sources = sources_doc.get("sources") or []
    count = lambda items, key: ", ".join("%s %d" % kv for kv in sorted(collections.Counter(x.get(key) for x in items).items(), key=lambda kv: (-kv[1], str(kv[0]))))
    print("build %s" % build_date)
    print("setups: %d  (by type: %s; by target: %s; by status: %s)"
          % (len(setups), count(setups, "kind"), count(setups, "target"), count(setups, "phase")))
    print("sources: %d in %d categories  (by signal: %s; by evidence: %s)"
          % (len(sources), len(sources_doc.get("categories") or []), count(sources, "signal"), count(sources, "evidence")))
    n_refs = sum(len(x.get("references") or []) for x in setups + sources)
    n_nourl = sum(1 for x in setups + sources for r in (x.get("references") or []) if not r.get("url"))
    print("references: %d, of which %d without link; leads: %d" % (n_refs, n_nourl, len(meta.get("leads") or [])))
    for e in errors:
        print("ERROR: " + e)
    for where, field, text in wording:
        print("WORDING: %s | %s | ...%s..." % (where, field, text))
    print("validation: %d error(s); wording check: %d hit(s)" % (len(errors), len(wording)))
    if errors or wording:
        sys.exit(1)

    topo.get("objects", {}).pop("land", None)       # only the countries object is drawn
    n_before = len(topo.get("arcs", []))
    topo = simplify_topology(topo)
    tpc = dict(sources_doc)
    tpc["provisional"] = False
    data = {
        "build_date": build_date,
        "setups": setups,
        "leads": meta.get("leads") or [],
        "past_detectors": meta.get("past_detectors") or [],
        "tags": meta.get("tags") or [],
        "tpc": tpc,
    }
    page = template.replace(DATA_MARK, inline_json(data)).replace(TOPO_MARK, inline_json(topo))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("world geometry: %d of %d arcs kept" % (len(topo["arcs"]), n_before))
    print("wrote site/index.html (%.0f kB)" % (os.path.getsize(OUT) / 1000.0))


if __name__ == "__main__":
    main()
