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
import math
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


def pub_key(r):
    """One key per publication: the link when there is one (arXiv and DOI forms folded), else title and year."""
    u = (r.get("url") or "").strip().lower()
    if u:
        u = re.sub(r"^https?://(www\.)?", "", u).split("#")[0].rstrip("/")
        m = re.match(r"arxiv\.org/(?:abs|pdf)/([^?]+?)(?:v\d+)?(?:\.pdf)?$", u)
        if m:
            return "arxiv:" + m.group(1)
        m = re.match(r"(?:dx\.)?doi\.org/(.+)$", u)
        if m:
            return "doi:" + m.group(1)
        return "url:" + u
    t = re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip()
    return "title:%s|%s" % (t, r.get("year") or "")


def _norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _first_author(a):
    a = re.sub(r"\([^)]*\)", " ", a or "")
    a = re.split(r",|;|&| and | et al", a)[0].strip().lower()
    toks = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", a)
    return toks[-1] if toks else ""


def _link_label(kind, url):
    u = (url or "").lower()
    if kind in ("talk", "poster"):
        return "slides" if (u.endswith((".pdf", ".pptx", ".ppt", ".key")) or "/attachments/" in u) else "abstract"
    if "arxiv.org" in u:
        return "arXiv"
    if "doi.org" in u:
        return "journal"
    return "link"


def build_publications(setups, tpc, intro, figure=None):
    """Every publication the site cites, de-duplicated, with what cites it.
    Pass 1 merges by link (or title and year). Pass 2 merges one contribution reachable by two links
    (slides and abstract page of a talk, journal and arXiv page of a paper): same title, first author and year."""
    pubs = collections.OrderedDict()

    def add(r, field, ident):
        if not isinstance(r, dict) or not r.get("title"):
            return
        k = pub_key(r)
        p = pubs.get(k)
        if p is None:
            p = pubs[k] = {"title": r.get("title"), "authors": r.get("authors"), "year": r.get("year"),
                           "venue": r.get("venue"), "url": r.get("url"), "type": r.get("type") or "web",
                           "setups": [], "sources": [], "intro": False, "rates": False, "figure": False}
        else:
            for f in ("authors", "year", "venue"):
                if not p.get(f) and r.get(f):
                    p[f] = r.get(f)
            if p["type"] == "web" and r.get("type"):
                p["type"] = r.get("type")
        if field in ("setups", "sources"):
            if ident not in p[field]:
                p[field].append(ident)
        else:
            p[field] = True

    for s in setups:
        for r in s.get("references") or []:
            add(r, "setups", s["id"])
    for x in (tpc or {}).get("sources") or []:
        for r in x.get("references") or []:
            add(r, "sources", x["id"])
    for r in (tpc or {}).get("pairing_references") or []:
        add(r, "rates", None)
    for r in (intro or {}).get("references") or []:
        add(r, "intro", None)
    for r in ((figure or {}).get("model") or {}).get("references") or []:
        add(r, "figure", None)

    merged = collections.OrderedDict()
    for n, p in enumerate(pubs.values()):
        t, fa = _norm_title(p["title"]), _first_author(p.get("authors"))
        k2 = (t, fa, p.get("year")) if (t and fa and p.get("year")) else ("single", n)
        q = merged.get(k2)
        if q is None:
            p["links"] = [{"label": _link_label(p["type"], p["url"]), "url": p["url"]}] if p.get("url") else []
            merged[k2] = p
            continue
        for f in ("setups", "sources"):
            for ident in p[f]:
                if ident not in q[f]:
                    q[f].append(ident)
        for f in ("intro", "rates", "figure"):
            q[f] = q[f] or p[f]
        for f in ("authors", "venue"):
            if not q.get(f) and p.get(f):
                q[f] = p.get(f)
        if p.get("url") and all(l["url"] != p["url"] for l in q["links"]):
            q["links"].append({"label": _link_label(p["type"], p["url"]), "url": p["url"]})
            if not q.get("url"):
                q["url"] = p["url"]
    out = list(merged.values())
    for p in out:
        if len(p["links"]) > 1:
            p["venue"] = re.sub(r"\s*\((slides|abstract|abstract page|contribution page)\)\s*$", "", p.get("venue") or "") or None
            seen = collections.Counter()
            for l in p["links"]:
                seen[l["label"]] += 1
                if seen[l["label"]] > 1:
                    l["label"] = "%s %d" % (l["label"], seen[l["label"]])
    return out


FIG_POPULATIONS = ["ac", "wimp_light", "wimp_heavy"]      # required
FIG_OPTIONAL = ["b8"]                                     # may be present as well


def check_figure(fig):
    """Problems in the Home figure data, as a list of strings (empty when it is sound)."""
    errs = []
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if not isinstance(fig, dict):
        return ["intro_figure.json: not an object"]
    ok_axes = True
    for ax in ("x", "y"):
        a = fig.get(ax)
        if not isinstance(a, dict) or not a.get("label") or not num(a.get("min")) or not num(a.get("max")) or not a["min"] < a["max"]:
            errs.append("intro_figure.json: axis %s needs a label and numeric min < max" % ax)
            ok_axes = False
        elif not isinstance(a.get("ticks"), list) or not all(num(t) for t in a["ticks"]):
            errs.append("intro_figure.json: axis %s ticks must be a list of numbers" % ax)
    if ok_axes and fig["y"]["min"] <= 0:
        errs.append("intro_figure.json: y min must be above 0 (log axis)")
        ok_axes = False
    pops = fig.get("populations") or []
    ids = [p.get("id") for p in pops if isinstance(p, dict)]
    if len(set(ids)) != len(ids) or any(i not in ids for i in FIG_POPULATIONS) or any(i not in FIG_POPULATIONS + FIG_OPTIONAL for i in ids):
        errs.append("intro_figure.json: populations must be %s, each once, optionally with %s (found %s)"
                    % (", ".join(FIG_POPULATIONS), ", ".join(FIG_OPTIONAL), ", ".join(str(i) for i in ids)))
    if ok_axes:
        x0, x1 = fig["x"]["min"], fig["x"]["max"]
        l0, l1 = math.log10(fig["y"]["min"]), math.log10(fig["y"]["max"])
        tx, tl = 0.02 * (x1 - x0), 0.02 * (l1 - l0)
        for p in pops:
            if not isinstance(p, dict):
                continue
            if not p.get("label"):
                errs.append("intro_figure.json: population %r has no label" % p.get("id"))
            if not p.get("contours"):
                errs.append("intro_figure.json: population %r has no contours" % p.get("id"))
            for c in p.get("contours") or []:
                w = "population %s, level %s" % (p.get("id"), c.get("level") if isinstance(c, dict) else "?")
                if not isinstance(c, dict) or not num(c.get("level")) or not c.get("polygons"):
                    errs.append("intro_figure.json: %s needs a numeric level and polygons" % w)
                    continue
                for k, poly in enumerate(c["polygons"]):
                    if not isinstance(poly, list) or len(poly) < 4 or not all(isinstance(q, list) and len(q) == 2 and num(q[0]) and num(q[1]) for q in poly):
                        errs.append("intro_figure.json: %s polygon %d needs at least four [x, y] points" % (w, k))
                        continue
                    if abs(poly[0][0] - poly[-1][0]) > 1e-6 * (x1 - x0) or abs(poly[0][1] - poly[-1][1]) > 1e-6 * max(abs(poly[0][1]), 1e-12):
                        errs.append("intro_figure.json: %s polygon %d is not closed" % (w, k))
                    bad = [q for q in poly if q[1] <= 0 or not (x0 - tx <= q[0] <= x1 + tx) or not (l0 - tl <= math.log10(q[1]) <= l1 + tl)]
                    if bad:
                        errs.append("intro_figure.json: %s polygon %d has %d point(s) outside the axes, e.g. %r" % (w, k, len(bad), bad[0]))
    for t in fig.get("thresholds") or []:
        if not isinstance(t, dict) or t.get("axis") not in ("x", "y") or not num(t.get("value")):
            errs.append("intro_figure.json: a threshold needs axis x or y and a numeric value")
    for k, v in (fig.get("overlap") or {}).items():
        if not num(v):
            errs.append("intro_figure.json: overlap %s is not a number" % k)
    return errs


def publications_summary(pubs):
    by_type = collections.Counter(p["type"] for p in pubs)
    return "publications: %d after de-duplication (%s); without link: %d" % (
        len(pubs), ", ".join("%s %d" % kv for kv in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        sum(1 for p in pubs if not p.get("url")))


INTRO_SECTIONS = ["what", "rate", "why", "xenon", "argon", "handling", "open"]


def check_intro(intro):
    """Problems in the introduction data, as a list of strings (empty when it is sound)."""
    errs = []
    if not isinstance(intro, dict):
        return ["intro.json: not an object"]
    refs = intro.get("references") or []
    n = len(refs)
    for key in ("title", "lede"):
        if not intro.get(key):
            errs.append("intro.json: missing %s" % key)
    kf = intro.get("key_facts") or []
    if len(kf) != 3:
        errs.append("intro.json: key_facts must have exactly three entries (has %d)" % len(kf))
    for i, k in enumerate(kf):
        if not isinstance(k, dict) or not k.get("value") or not k.get("label"):
            errs.append("intro.json: key fact %d needs value and label" % i)
        elif k.get("ref") is not None and not (isinstance(k.get("ref"), int) and 0 <= k["ref"] < n):
            errs.append("intro.json: key fact %d ref %r is not an index into references" % (i, k.get("ref")))
    ids = [s.get("id") for s in intro.get("sections") or [] if isinstance(s, dict)]
    for sid in INTRO_SECTIONS:
        if sid not in ids:
            errs.append("intro.json: section %r is missing" % sid)
    texts = [("lede", intro.get("lede") or "")]
    for s in intro.get("sections") or []:
        if not isinstance(s, dict):
            continue
        if not s.get("heading") or not s.get("paragraphs"):
            errs.append("intro.json: section %r needs a heading and paragraphs" % s.get("id"))
        for i, p in enumerate(s.get("paragraphs") or []):
            texts.append(("section %s paragraph %d" % (s.get("id"), i + 1), p if isinstance(p, str) else ""))
        for r in s.get("refs") or []:
            if not (isinstance(r, int) and 0 <= r < n):
                errs.append("intro.json: section %r refs entry %r is not an index into references" % (s.get("id"), r))
    for where, text in texts:
        for m in re.finditer(r"\[(\d+)\]", text):
            if not (1 <= int(m.group(1)) <= n):
                errs.append("intro.json: %s cites [%s], but there are %d references" % (where, m.group(1), n))
    for i, r in enumerate(refs):
        if not isinstance(r, dict) or not r.get("title"):
            errs.append("intro.json: reference %d has no title" % (i + 1))
    for g in intro.get("glossary") or []:
        if not isinstance(g, dict) or not g.get("term") or not g.get("definition"):
            errs.append("intro.json: a glossary entry needs term and definition")
    return errs


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

    intro, warnings = None, []
    intro_path = os.path.join(DATA, "intro.json")
    if os.path.exists(intro_path):
        try:
            intro = load(intro_path)
        except (OSError, ValueError) as exc:
            sys.exit("build.py: cannot read data/intro.json: %s" % exc)
    else:
        warnings.append("no data/intro.json: the Home view shows 'introduction text pending'")
    figure, fig_path = None, os.path.join(DATA, "intro_figure.json")
    if os.path.exists(fig_path):
        try:
            figure = load(fig_path)
        except (OSError, ValueError) as exc:
            sys.exit("build.py: cannot read data/intro_figure.json: %s" % exc)
    else:
        warnings.append("no data/intro_figure.json: the Home view has no template figure")
    errors = validate(setups, sources_doc, meta)
    if figure is not None:
        errors += check_figure(figure)
        if isinstance(figure, dict) and isinstance(figure.get("model"), dict):
            check_refs(figure["model"].get("references") or [], "intro_figure.json", errors)
    if intro is not None:
        errors += check_intro(intro)
        check_refs(intro.get("references") or [], "intro.json", errors)
    errors += ["src/template.html sizes a bare svg to 100% under a container: " + sel for sel in check_svg_sizing(template)]
    wording = []
    for x in setups:
        find_wording(x, "setup", None, wording)
    for x in sources_doc.get("sources") or []:
        find_wording(x, "source", None, wording)
    find_wording({k: v for k, v in sources_doc.items() if k != "sources"}, "sources.json", None, wording)
    find_wording(meta, "meta.json", None, wording)
    if intro is not None:
        find_wording(intro, "intro.json", None, wording)
    if figure is not None:
        find_wording(figure, "intro_figure.json", None, wording)
    publications = build_publications(setups, sources_doc, intro, figure)

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
    print("introduction: %s" % ("%d sections, %d references" % (len(intro.get("sections") or []), len(intro.get("references") or [])) if intro else "absent"))
    print("home figure: %s" % ("%d populations" % len(figure.get("populations") or []) if isinstance(figure, dict) else "absent"))
    print(publications_summary(publications))
    for w in warnings:
        print("WARNING: " + w)
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
        "intro": intro,
        "figure": figure,
        "publications": publications,
    }
    page = template.replace(DATA_MARK, inline_json(data)).replace(TOPO_MARK, inline_json(topo))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("world geometry: %d of %d arcs kept" % (len(topo["arcs"]), n_before))
    print("wrote site/index.html (%.0f kB)" % (os.path.getsize(OUT) / 1000.0))


if __name__ == "__main__":
    main()
