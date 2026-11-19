#!/usr/bin/env python3
# MIT License - Copyright (c) 2026 Maxime Pierre. See LICENSE in the repository root.
"""Toy model behind the home-page figure "Where accidental coincidences fall,
compared with a WIMP signal" (cS1 versus cS2 in a XENONnT-like xenon TPC).

Usage:  python3 tools/make_template_figure.py --out intro_figure.json

Needs numpy, nestpy (the Python bindings of NEST) and wimprates, at the versions
pinned in tools/requirements.txt; see tools/README.md. The script is not needed
to build the site. All random generators are started from fixed states, so the
same package versions reproduce the output file byte for byte. A run takes a
few minutes.

What it does
------------
1. Recoil spectra. Spin-independent elastic WIMP-xenon rates for 6 and
   50 GeV/c2 from wimprates with its standard halo model; the 8B solar-neutrino
   CEvNS recoil spectrum on xenon as parametrised inside NEST; flat spectra for
   the electronic- and nuclear-recoil reference bands. Only shapes matter.
2. Yields, fluctuations and detector response from NEST, end to end, through
   its vectorised runner (FullCalculation, then GetS1 and GetS2 for each
   event), for a detector description filled with published XENONnT numbers.
3. Thresholds: a 3-fold S1 coincidence with NEST's rule and cS2 >= 120 PE.
4. Accidental coincidences: an isolated S1 and an isolated S2 drawn
   independently from two ASSUMED falling spectra (not measured ones) and
   passed through the same single-photoelectron and single-electron response.
5. Highest-density regions holding 50 % and 90 % of each population, from a
   smoothed 2-D histogram in (cS1, log10 cS2), traced with marching squares.

Everything here uses published numbers, public software or stated assumptions;
it is an illustration, not a template of any experiment.
"""
import argparse
import json
import math
import warnings
from importlib.metadata import version

import numpy as np

import numericalunits as nu
nu.reset_units("SI")          # fixed unit values, so that the spectra are bit-reproducible

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import wimprates          # noqa: E402  (must come after the unit reset)
import nestpy                 # noqa: E402

# ----------------------------------------------------------------------------
# Fixed state of the random generators (numpy streams and NEST's own generator)
# ----------------------------------------------------------------------------
RNG_STATE = 20261119

# The wheel of nestpy 2.1.3 does not report the NEST version it was built from;
# its source tree pins this commit of github.com/NESTCollaboration/nest.
NEST_SOURCE = "NEST commit 541b643, 23 commits after v2.4.5beta"

# ----------------------------------------------------------------------------
# Detector description handed to NEST (see REFERENCES below for the index)
# ----------------------------------------------------------------------------
G1_PE = 0.151          # PE per photon, XENONnT SR0                          [ref 0]
G2_PE = 16.5           # PE per electron, XENONnT SR0                        [ref 0]
SE_GAIN_PE = 31.15     # PE per extracted electron                           [ref 2]
DRIFT_FIELD = 23.0     # V/cm                                                [ref 0]
P_DPE = 0.2            # double-photoelectron probability, typical R11410 (assumed)
SPE_RES = 0.35         # single-photoelectron resolution, sigma/mean (assumed)
SPE_THR = 0.13         # PE, per-channel threshold                           [ref 0]
SPE_EFF = 0.912        # single-photoelectron acceptance, SR0                [ref 1]
N_PMT = 477            # 494 PMTs minus 17 excluded in SR0                   [ref 0]
COIN_LEVEL = 3         # 3-fold S1 coincidence of the WIMP search            [ref 0]
COIN_WINDOW_NS = 100.0 # +-50 ns                                             [ref 0]
PRESSURE_BAR = 1.89    #                                                     [ref 0]
# Published temperature is 176.8 K; NEST places 176.8 K at 1.89 bar on the gas
# side of its phase boundary, so the liquid is described 0.8 K colder.
TEMPERATURE_K = 176.0
# Geometry in mm: 1486 mm drift, liquid level 5 mm above the gate, anode 8 mm
# above the gate (3 mm gas gap)                                              [refs 0, 1]
Z_CATHODE, Z_GATE, Z_LIQUID, Z_ANODE = 1.0, 1487.0, 1492.0, 1495.0
RADIUS_MM = 664.0
# Tuned so that NEST returns the published extraction efficiency (g2 / single-
# electron gain = 0.53) and single-electron gain. NEST's extraction model needs
# 6.85 kV/cm in the gas for that; this is a tuning knob, not the real field.
GAS_FIELD_KV_CM = 6.85
G1_GAS = 0.154         # photons detected per electroluminescence photon
ELECTRON_LIFETIME_US = 1e7   # no loss during the drift
EVENT_POSITION = (0.0, 0.0, 746.0)   # centre: corrected and raw areas coincide

S2_MIN_PE = 120.0      # S2 threshold of the 8B CEvNS search                 [ref 1]
E_MIN_KEV = 0.1        # lowest recoil energy simulated; NEST gives no quanta below ~0.2 keV

# 8B CEvNS recoil spectrum on xenon as parametrised in NEST (TestSpectra::B8_spectrum),
# with its constants for the neutrino spectrum of Winter et al.
B8_M1, B8_M2 = -2.2965e-13, 7.4129

# ----------------------------------------------------------------------------
# Assumed isolated-pulse spectra for the accidental population
# ----------------------------------------------------------------------------
AC_S1_MEAN_EXCESS = 1.2   # mean number of detected photons above three (geometric)
AC_S1_TAIL_FRACTION = 0.03
AC_S1_TAIL_MAX = 40       # flat tail between 3 and 40 detected photons
AC_S2_INDEX = 2.0         # dN/dn ~ n^-2 in extracted electrons, see parameters
AC_S2_MIN_ELECTRONS = 2
AC_S2_MAX_ELECTRONS = 400

# ----------------------------------------------------------------------------
# Figure window and histogram used for the contours
# ----------------------------------------------------------------------------
X_MIN, X_MAX = 0.0, 30.0
Y_MIN, Y_MAX = 100.0, 5000.0
GRID_X_MAX = 150.0        # the histogram extends beyond the window
GRID_LOGY_MAX = 4.6
DX = 0.25                 # PE
DLOGY = 0.02              # dex
SMOOTH_X = 0.5            # PE, Gaussian smoothing before contouring
SMOOTH_LOGY = 0.05        # dex
N_EVENTS = 300000         # events above thresholds per population
CHUNK = 1000000           # recoils handed to NEST at a time
N_POINTS = 120            # sampled events written for an optional scatter
MAX_VERTICES = 120

REFERENCES = [
    {"title": "First Dark Matter Search with Nuclear Recoils from the XENONnT Experiment",
     "authors": "E. Aprile et al. (XENON)", "year": 2023,
     "venue": "Phys. Rev. Lett. 131, 041003 (2023); arXiv:2303.14729",
     "url": "https://arxiv.org/abs/2303.14729", "type": "paper"},
    {"title": "First Indication of Solar 8B Neutrinos via Coherent Elastic Neutrino-Nucleus Scattering with XENONnT",
     "authors": "E. Aprile et al. (XENON)", "year": 2024,
     "venue": "Phys. Rev. Lett. 133, 191002 (2024), doi:10.1103/PhysRevLett.133.191002; arXiv:2408.02877",
     "url": "https://arxiv.org/abs/2408.02877", "type": "paper"},
    {"title": "Search for Light Dark Matter in Low-Energy Ionization Signals from XENONnT",
     "authors": "E. Aprile et al. (XENON)", "year": 2025,
     "venue": "Phys. Rev. Lett. 134, 161004 (2025); arXiv:2411.15289",
     "url": "https://arxiv.org/abs/2411.15289", "type": "paper"},
    {"title": "Recommended conventions for reporting results from direct dark matter searches",
     "authors": "D. Baxter et al.", "year": 2021,
     "venue": "Eur. Phys. J. C 81, 907 (2021); arXiv:2105.00599",
     "url": "https://arxiv.org/abs/2105.00599", "type": "paper"},
    {"title": "NEST: Noble Element Simulation Technique (NESTCollaboration/nest)",
     "authors": "J. Brodsky, C. Tunnell, M. Szydagis et al. (NEST Collaboration)", "year": 2026,
     "venue": "software, github.com/NESTCollaboration/nest; Zenodo, doi:10.5281/zenodo.2535713",
     "url": "https://doi.org/10.5281/zenodo.2535713", "type": "web"},
    {"title": "nestpy: Python bindings for the NEST noble element simulation, v2.1.3",
     "authors": "S. Farrell, C. Tunnell, J. R. Angevaare et al.", "year": 2026,
     "venue": "software, github.com/NESTCollaboration/nestpy; Zenodo, doi:10.5281/zenodo.1345595",
     "url": "https://doi.org/10.5281/zenodo.1345595", "type": "web"},
    {"title": "wimprates: differential rates of WIMP-nucleus scattering, v0.5.0",
     "authors": "J. Aalbers, B. Pelssers, J. R. Angevaare, K. D. Morå", "year": 2023,
     "venue": "software, github.com/JelleAalbers/wimprates; Zenodo, doi:10.5281/zenodo.2604222",
     "url": "https://doi.org/10.5281/zenodo.2604222", "type": "web"},
]
REF_NEST, REF_WIMPRATES = 4, 6


# ============================================================================
# NEST detector and runner
# ============================================================================
def build_detector():
    """A NEST detector description filled with published XENONnT-like numbers."""
    d = nestpy.detectors.VDetector()
    d.set_g1(G1_PE / (1.0 + P_DPE))       # NEST counts detected photons, not PE
    d.set_P_dphe(P_DPE)
    d.set_sPEres(SPE_RES)
    d.set_sPEthr(SPE_THR)
    d.set_sPEeff(SPE_EFF)
    d.set_noiseBaseline(0.0, 0.0, 0.0, 0.0)
    d.set_noiseLinear(0.0, 0.0)
    d.set_noiseQuadratic(0.0, 0.0)
    d.set_coinLevel(COIN_LEVEL)
    d.set_coinWind(COIN_WINDOW_NS)
    d.set_numPMTs(N_PMT)
    d.set_T_Kelvin(TEMPERATURE_K)
    d.set_p_bar(PRESSURE_BAR)
    d.set_cathode(Z_CATHODE)
    d.set_gate(Z_GATE)
    d.set_TopDrift(Z_LIQUID)
    d.set_anode(Z_ANODE)
    d.set_radius(RADIUS_MM)
    d.set_radmax(RADIUS_MM)
    d.set_eLife_us(ELECTRON_LIFETIME_US)
    d.set_s2_thr(0.0)                     # the S2 threshold is applied below, on cS2
    d.set_E_gas(GAS_FIELD_KV_CM)
    d.set_g1_gas(G1_GAS)
    return d                              # s2Fano is left at the NEST default


class NestStream:
    """Hands out consecutive states for NEST's generator, one per call."""

    def __init__(self, first):
        self.state = first

    def next(self):
        self.state += 1
        return self.state


def distinct_pmt_probability():
    """NEST's probability that k counted photons sit in at least COIN_LEVEL
    different PMTs (the last step of the coincidence rule in NESTcalc::GetS1)."""
    table = np.ones(64)
    table[:COIN_LEVEL] = 0.0
    for k in range(COIN_LEVEL, 11):
        terms = [math.comb(N_PMT, i) for i in range(1, k + 1)]
        table[k] = sum(terms[COIN_LEVEL - 1:]) / sum(terms)
    return table


P_DISTINCT = distinct_pmt_probability()


def coincidence(rng, counted):
    """NEST's S1 coincidence rule: at least COIN_LEVEL photons counted above the
    single-photoelectron threshold, in different PMTs. The vectorised runner
    returns unsigned areas and so drops the flag NEST sets; the rule is applied
    here on the counted photons it does return."""
    return rng.random(len(counted)) < P_DISTINCT[np.minimum(counted, 63)]


def run_nest(det, interaction, energies, nest_state):
    """NEST chain for a batch of recoils: counted S1 photons, cS1 and cS2 in PE."""
    pos = np.tile(EVENT_POSITION, (len(energies), 1))
    out = nestpy.array.runNESTvec(det, interaction, energies, pos, inField=DRIFT_FIELD, seed=nest_state)
    return (np.asarray(out["s1_nhits_thr"]), np.asarray(out["s1c_phe"]), np.asarray(out["s2c_phe"]),
            np.asarray(out["n_photons"]), np.asarray(out["n_electrons"]))


def simulate_recoils(det, rng, nest, interaction, draw_energy, n_wanted, need_s2=True):
    """Simulate in fixed-size chunks until n_wanted events pass the thresholds."""
    xs, ys, n_pass, n_drawn = [], [], 0, 0
    while n_pass < n_wanted:
        e = draw_energy(rng, nest, CHUNK)
        n_drawn += CHUNK
        counted, cs1, cs2, _, _ = run_nest(det, interaction, e[e >= E_MIN_KEV], nest.next())
        keep = coincidence(rng, counted)
        keep &= (cs2 >= S2_MIN_PE) if need_s2 else (cs2 > 1.0)
        xs.append(cs1[keep])
        ys.append(cs2[keep])
        n_pass += int(keep.sum())
    return np.concatenate(xs)[:n_wanted], np.concatenate(ys)[:n_wanted], n_pass / n_drawn


# ============================================================================
# Recoil spectra
# ============================================================================
def wimp_sampler(mass_gev, e_max):
    """Inverse-CDF sampler of the wimprates spin-independent spectrum on xenon."""
    e_grid = np.linspace(E_MIN_KEV, e_max, 4000)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rate = wimprates.rate_wimp_std(e_grid, mass_gev, 1e-45)
    cdf = np.concatenate(([0.0], np.cumsum(0.5 * (rate[1:] + rate[:-1]) * np.diff(e_grid))))
    cdf /= cdf[-1]
    return lambda rng, nest, n: np.interp(rng.random(n), cdf, e_grid)


def b8_sampler(rng, nest, n):
    """8B CEvNS recoil energies (0-5 keV) drawn by NEST's own spectrum routine."""
    nestpy.RandomGen.rndm().set_seed(nest.next())
    return np.asarray(nestpy.spectra.B8(n, 0.0, 5.0, B8_M1, B8_M2))


def flat_sampler(e_lo, e_hi):
    return lambda rng, nest, n: rng.uniform(e_lo, e_hi, n)


# ============================================================================
# Accidental coincidences (assumed spectra, same single-quantum response)
# ============================================================================
def spe_area(rng, n):
    """Area of n detected photons with NEST's single-photoelectron model: a
    Gaussian truncated at zero with unit mean, plus a second photoelectron with
    probability P_DPE; the photon is counted when its area exceeds SPE_THR."""
    z = 1.0 / SPE_RES
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    centre = 1.0 / (1.0 + SPE_RES * pdf / cdf)      # makes the truncated mean equal to 1

    def one(m):
        a = rng.normal(centre, SPE_RES, m)
        bad = a <= 0.0
        while bad.any():
            a[bad] = rng.normal(centre, SPE_RES, int(bad.sum()))
            bad = a <= 0.0
        return a

    area = one(n) + np.where(rng.random(n) < P_DPE, one(n), 0.0)
    low = area <= SPE_THR
    while low.any():
        k = int(low.sum())
        area[low] = one(k) + np.where(rng.random(k) < P_DPE, one(k), 0.0)
        low = area <= SPE_THR
    return area


def isolated_s1(rng, n):
    """Isolated S1s: a few counted photons, 3 plus a geometric excess, with a
    small flat tail; areas from the single-photoelectron model above."""
    counted = COIN_LEVEL + rng.geometric(1.0 / (1.0 + AC_S1_MEAN_EXCESS), n) - 1
    tail = rng.random(n) < AC_S1_TAIL_FRACTION
    counted = np.where(tail, rng.integers(COIN_LEVEL, AC_S1_TAIL_MAX + 1, n), counted)
    owner = np.repeat(np.arange(n), counted)
    area = np.bincount(owner, weights=spe_area(rng, len(owner)), minlength=n)
    keep = coincidence(rng, counted)
    return area[keep]


def isolated_s2(det, rng, nest, n):
    """Isolated S2s: a falling spectrum in the number of extracted electrons,
    each pulse built by NEST's GetS2 (electroluminescence, photon detection,
    double photoelectrons, single-photoelectron smearing)."""
    calc = nestpy.NESTcalc(det)
    rho = det.density_liquid
    v_drift = calc.SetDriftVelocity(TEMPERATURE_K, rho, DRIFT_FIELD, PRESSURE_BAR)
    g2_params = list(calc.CalculateG2(0))
    g2_params[1] = 1.0                   # the electrons handed over are already extracted
    x, y, z = EVENT_POSITION
    dt = (Z_LIQUID - z) / v_drift
    n_el = np.arange(AC_S2_MIN_ELECTRONS, AC_S2_MAX_ELECTRONS + 1)
    p_el = n_el.astype(float) ** (-AC_S2_INDEX)
    p_el /= p_el.sum()
    electrons = rng.choice(n_el, size=n, p=p_el)
    mode = nestpy.S2CalculationMode.Full
    nestpy.RandomGen.rndm().set_seed(nest.next())
    area = np.array([abs(calc.GetS2(int(k), x, y, z, x, y, z, dt, v_drift, i, DRIFT_FIELD, mode, -1, [], [], g2_params)[5])
                     for i, k in enumerate(electrons)])
    return area[area >= S2_MIN_PE]


def simulate_accidentals(det, rng, nest, n_wanted):
    """Independent isolated S1 and isolated S2."""
    s1 = isolated_s1(rng, int(1.1 * n_wanted))[:n_wanted]
    parts, n_have = [], 0
    while n_have < n_wanted:
        parts.append(isolated_s2(det, rng, nest, n_wanted))
        n_have += len(parts[-1])
    s2 = np.concatenate(parts)[:n_wanted]
    return s1, s2


# ============================================================================
# Density, highest-density regions and contours
# ============================================================================
X_EDGES = np.arange(0.0, GRID_X_MAX + DX / 2, DX)
LOGY_LO = math.log10(S2_MIN_PE)
LOGY_EDGES = LOGY_LO + DLOGY * np.arange(int(round((GRID_LOGY_MAX - LOGY_LO) / DLOGY)) + 1)
X_CENTRES = 0.5 * (X_EDGES[1:] + X_EDGES[:-1])
LOGY_CENTRES = 0.5 * (LOGY_EDGES[1:] + LOGY_EDGES[:-1])


def histogram(cs1, cs2):
    h, _, _ = np.histogram2d(np.log10(cs2), cs1, bins=[LOGY_EDGES, X_EDGES])
    return h   # shape (n_logy, n_x)


def gaussian_smooth(h, sigma_bins, axis, mirror_low):
    """Gaussian filter along one axis, padded with zeros. With mirror_low the low
    edge is a threshold (a real, sharp edge) and the histogram is mirrored there."""
    half = int(math.ceil(4 * sigma_bins))
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma_bins) ** 2)
    k /= k.sum()
    h = np.moveaxis(h, axis, 0)
    zeros = np.zeros((half,) + h.shape[1:])
    padded = np.concatenate([h[:half][::-1] if mirror_low else zeros, h, zeros])
    out = np.zeros_like(h, dtype=float)
    n = h.shape[0]
    for i, w in enumerate(k):
        out += w * padded[i:i + n]
    return np.moveaxis(out, 0, axis)


def smooth(h):
    """The S1 side has no sharp edge (3-fold S1s start near 2 PE); the S2 side has."""
    return gaussian_smooth(gaussian_smooth(h, SMOOTH_X / DX, 1, False), SMOOTH_LOGY / DLOGY, 0, True)


def hdr_level(density, n_total, fraction):
    """Density value above which the cells hold `fraction` of the population."""
    v = np.sort(density.ravel())[::-1]
    c = np.cumsum(v)
    i = int(np.searchsorted(c, fraction * n_total))
    return float(v[min(i, len(v) - 1)])


def marching_squares(field, level):
    """Closed iso-lines of `field` (2-D array on a regular grid, surrounded by a
    ring of zeros) at `level`. Returns loops of (row, column) in grid units."""
    f = np.pad(field, 1)
    inside = f >= level
    links = {}

    def crossing(p, q):
        (i0, j0), (i1, j1) = p, q
        a, b = f[i0, j0], f[i1, j1]
        t = (level - a) / (b - a)
        return (i0 + t * (i1 - i0) - 1.0, j0 + t * (j1 - j0) - 1.0)

    points = {}
    rows, cols = np.nonzero(inside[:-1, :-1] != inside[1:, 1:])
    rows2, cols2 = np.nonzero(inside[:-1, 1:] != inside[1:, :-1])
    cells = sorted(set(zip(rows.tolist(), cols.tolist())) | set(zip(rows2.tolist(), cols2.tolist())))
    for i, j in cells:
        a, b, c, d = (i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)
        edges = [(a, b), (b, c), (d, c), (a, d)]
        cut = [e for e in edges if inside[e[0]] != inside[e[1]]]
        if len(cut) == 2:
            pairs = [(cut[0], cut[1])]
        elif len(cut) == 4:
            centre_in = 0.25 * (f[a] + f[b] + f[c] + f[d]) >= level
            if centre_in == bool(inside[a]):
                pairs = [(edges[0], edges[1]), (edges[2], edges[3])]
            else:
                pairs = [(edges[0], edges[3]), (edges[1], edges[2])]
        else:
            continue
        for e0, e1 in pairs:
            for e in (e0, e1):
                if e not in points:
                    points[e] = crossing(*e)
            links.setdefault(e0, []).append(e1)
            links.setdefault(e1, []).append(e0)

    loops, seen = [], set()
    for start in sorted(links):
        if start in seen:
            continue
        loop, prev, cur = [], None, start
        while cur not in seen:
            seen.add(cur)
            loop.append(points[cur])
            nxt = [e for e in links[cur] if e != prev]
            prev, cur = cur, (nxt[0] if nxt else start)
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def polygon_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def clip_to_box(poly, x0, x1, y0, y1):
    """Sutherland-Hodgman clipping of a polygon to an axis-aligned box."""
    def clip(points, inside, cut):
        out = []
        for k in range(len(points)):
            p, q = points[k - 1], points[k]
            if inside(q):
                if not inside(p):
                    out.append(cut(p, q))
                out.append(q)
            elif inside(p):
                out.append(cut(p, q))
        return out

    def cut_x(v):
        return lambda p, q: (v, p[1] + (q[1] - p[1]) * (v - p[0]) / (q[0] - p[0]))

    def cut_y(v):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (v - p[1]) / (q[1] - p[1]), v)

    pts = [tuple(p) for p in poly]
    for inside, cut in ((lambda p: p[0] >= x0, cut_x(x0)), (lambda p: p[0] <= x1, cut_x(x1)),
                        (lambda p: p[1] >= y0, cut_y(y0)), (lambda p: p[1] <= y1, cut_y(y1))):
        pts = clip(pts, inside, cut)
        if len(pts) < 3:
            return []
    return pts


def tidy_polygon(loop):
    """Grid loop -> smoothed, thinned, clipped and closed polygon in (cS1, cS2).
    Clipped at the cS2 threshold and at the edges of the plotted window only."""
    g = np.array(loop)
    x = X_CENTRES[0] + DX * g[:, 1]
    ly = LOGY_CENTRES[0] + DLOGY * g[:, 0]
    # work in units where the figure window is roughly square
    sx, sy = X_MAX - X_MIN, math.log10(Y_MAX / S2_MIN_PE)
    p = np.column_stack([x / sx, ly / sy])
    # resample at equal steps along the outline, smooth, thin out
    q = np.vstack([p, p[:1]])
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(q, axis=0).T))])
    n_fine = 400
    t = np.linspace(0.0, s[-1], n_fine, endpoint=False)
    fine = np.column_stack([np.interp(t, s, q[:, 0]), np.interp(t, s, q[:, 1])])
    kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0]) / 9.0
    smoothed = sum(w * np.roll(fine, k - 2, axis=0) for k, w in enumerate(kernel))
    thin = smoothed[::4]                                   # 100 vertices
    pts = clip_to_box(thin * [sx, sy], X_MIN, X_MAX, LOGY_LO, math.log10(Y_MAX))
    if len(pts) < 3:
        return None, 0.0
    arr = np.array(pts)
    area = polygon_area(arr / [sx, sy])
    out = [[round(float(a), 2), round(float(10 ** b), 1)] for a, b in pts[:MAX_VERTICES - 1]]
    out.append(out[0])
    return out, area


def contours(density, n_total):
    result = []
    for fraction in (0.5, 0.9):
        level = hdr_level(density, n_total, fraction)
        polys = [tidy_polygon(loop) for loop in marching_squares(density, level)]
        polys = [(p, a) for p, a in polys if p]
        biggest = max(a for _, a in polys)
        polys = [p for p, a in polys if a >= 0.03 * biggest]   # drop specks
        result.append({"level": fraction, "polygons": polys})
    return result


def sample_points(cs1, cs2):
    """First N_POINTS events falling in the figure window (events are independent)."""
    ok = (cs1 <= X_MAX) & (cs2 <= Y_MAX)
    return [[round(float(a), 2), round(float(b), 1)] for a, b in zip(cs1[ok][:N_POINTS], cs2[ok][:N_POINTS])]


def band(cs1, cs2, quantiles):
    """Quantiles of cS2 in 1 PE wide cS1 slices, lightly smoothed in log cS2."""
    edges = np.arange(2.0, X_MAX + 0.5, 1.0)
    centres = 0.5 * (edges[1:] + edges[:-1])
    idx = np.digitize(cs1, edges) - 1
    logy = np.log10(cs2)
    rows = np.array([np.quantile(logy[idx == i], quantiles) for i in range(len(centres))])
    padded = np.vstack([rows[:1], rows, rows[-1:]])
    rows = 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]
    return [[[round(float(x), 2), round(float(10 ** v), 1)] for x, v in zip(centres, rows[:, k])]
            for k in range(len(quantiles))]


def median_at(cs1, cs2, x):
    sel = np.abs(cs1 - x) < 0.5
    return float(np.median(cs2[sel]))


# ============================================================================
# Main
# ============================================================================
def build():
    streams = [np.random.Generator(np.random.PCG64(s)) for s in np.random.SeedSequence(RNG_STATE).spawn(7)]
    rng_ac, rng_light, rng_heavy, rng_b8, rng_er, rng_nr, rng_cal = streams
    nest = NestStream(RNG_STATE)
    det = build_detector()
    ext = det.extraction_parameters
    nr, beta = nestpy.interactions.NR, nestpy.interactions.beta

    # what NEST returns for the gains, in PE
    g2_nest = ext["g2"] * (1.0 + P_DPE)
    se_nest = ext["SE"] * (1.0 + P_DPE)
    gains = {}
    for e_cal in (40.0, 300.0):
        _, cs1, cs2, n_ph, n_e = run_nest(det, beta, np.full(20000, e_cal), nest.next())
        gains[e_cal] = (float(cs1.mean() / n_ph.mean()), float(cs2.mean() / n_e.mean()))

    sims, eff = {}, {}
    sims["ac"] = simulate_accidentals(det, rng_ac, nest, N_EVENTS)
    for key, sampler in (("wimp_light", wimp_sampler(6.0, 5.0)), ("wimp_heavy", wimp_sampler(50.0, 150.0)),
                         ("b8", b8_sampler)):
        rng = {"wimp_light": rng_light, "wimp_heavy": rng_heavy, "b8": rng_b8}[key]
        x, y, eff[key] = simulate_recoils(det, rng, nest, nr, sampler, N_EVENTS)
        sims[key] = (x, y)

    er_x, er_y, _ = simulate_recoils(det, rng_er, nest, beta, flat_sampler(0.0, 10.0), N_EVENTS, need_s2=False)
    nr_x, nr_y, _ = simulate_recoils(det, rng_nr, nest, nr, flat_sampler(E_MIN_KEV, 40.0), N_EVENTS, need_s2=False)

    signals = ("wimp_light", "wimp_heavy", "b8")
    raw = {k: histogram(*v) for k, v in sims.items()}
    dens = {k: smooth(h) for k, h in raw.items()}
    ac90 = dens["ac"] >= hdr_level(dens["ac"], N_EVENTS, 0.9)
    exact = {k: float(raw[k][ac90].sum()) / N_EVENTS for k in ("ac",) + signals}
    overlap = {k + "_inside_ac90": round(exact[k], 3) for k in signals}
    in_view = {k: round(float(np.mean((v[0] <= X_MAX) & (v[1] <= Y_MAX))), 2) for k, v in sims.items()}

    meta = {
        "ac": ("Accidental coincidences",
               "An isolated S1 paired at random with an isolated S2: both spectra fall steeply from their "
               "thresholds, so the pairs pile up in the low-cS1, low-cS2 corner. Assumed spectra."),
        "wimp_light": ("6 GeV/c² WIMP",
                       "Recoils of at most a few keV that pass the thresholds only by upward fluctuation; "
                       "⁸B solar neutrinos give nearly the same distribution."),
        "wimp_heavy": ("50 GeV/c² WIMP",
                       "Recoils of up to tens of keV that follow the nuclear-recoil band to large cS1, "
                       "mostly away from the accidental corner."),
        "b8": ("⁸B solar neutrinos (CEvNS)",
               "Coherent scattering of ⁸B solar neutrinos on xenon nuclei, with the recoil spectrum "
               "parametrised in NEST; a signal for neutrino physics and a background for light WIMPs."),
    }
    populations = []
    for key in ("ac", "wimp_light", "wimp_heavy", "b8"):
        populations.append({
            "id": key,
            "label": meta[key][0],
            "note": meta[key][1],
            "fraction_in_view": in_view[key],
            "contours": contours(dens[key], N_EVENTS),
            "points": sample_points(*sims[key]),
        })

    er_lo, er_med, er_hi = band(er_x, er_y, [0.0228, 0.5, 0.9772])
    (nr_med,) = band(nr_x, nr_y, [0.5])
    band_check = {"er": [round(median_at(er_x, er_y, v)) for v in (5.0, 10.0, 20.0)],
                  "nr": [round(median_at(nr_x, nr_y, v)) for v in (5.0, 10.0, 20.0)]}

    halo = wimprates.StandardHaloModel()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v_earth = wimprates.v_earth(None) / (nu.km / nu.s)
    halo_text = "v0 = %.0f km/s, v_esc = %.0f km/s, Earth speed %.1f km/s, local density %.1f GeV/c²/cm³" % (
        halo.v_0 / (nu.km / nu.s), halo.v_esc / (nu.km / nu.s), v_earth,
        halo.rho_dm / (nu.GeV / nu.c0 ** 2 / nu.cm ** 3))

    software = [
        {"name": "nestpy", "version": version("nestpy"), "url": "https://github.com/NESTCollaboration/nestpy"},
        {"name": "NEST", "version": NEST_SOURCE, "url": "https://github.com/NESTCollaboration/nest"},
        {"name": "wimprates", "version": version("wimprates"), "url": "https://github.com/JelleAalbers/wimprates"},
        {"name": "numpy", "version": version("numpy"), "url": "https://numpy.org"},
    ]

    parameters = [
        {"name": "Recoil spectra, WIMPs",
         "value": "spin-independent elastic scattering on xenon for 6 and 50 GeV/c², wimprates %s (Helm form factor)" % version("wimprates"),
         "source": REF_WIMPRATES},
        {"name": "Halo model", "value": halo_text + " (package defaults, which follow the recommended conventions)", "source": 3},
        {"name": "Recoil spectrum, ⁸B neutrinos",
         "value": "CEvNS recoil spectrum on xenon as parametrised in NEST (0-5 keV, its constants for the Winter et al. neutrino spectrum)",
         "source": REF_NEST},
        {"name": "Lowest recoil energy simulated", "value": "%.1f keV; NEST returns no quanta for nuclear recoils below about 0.2 keV" % E_MIN_KEV,
         "source": REF_NEST},
        {"name": "Yields and fluctuations", "value": "NEST nuclear-recoil model (WIMPs, ⁸B, band) and beta model (electronic recoils), default parameters, at 23 V/cm",
         "source": REF_NEST},
        {"name": "Drift field", "value": "23 V/cm", "source": 0},
        {"name": "g1", "value": "0.151 PE/photon, entered in NEST as %.4f detected photons per photon; the simulation returns %.3f PE/photon at 300 keV and %.3f at 40 keV (single-photoelectron acceptance)"
         % (G1_PE / (1.0 + P_DPE), gains[300.0][0], gains[40.0][0]), "source": 0},
        {"name": "g2", "value": "16.5 PE/electron published; NEST returns %.2f PE/electron for the settings below (%.2f in the simulation)" % (g2_nest, gains[300.0][1]),
         "source": 0},
        {"name": "Single-electron gain", "value": "31.15 PE published; NEST returns %.2f PE" % se_nest, "source": 2},
        {"name": "Electron extraction efficiency", "value": "%.2f (g2 divided by the single-electron gain); NEST returns %.3f" % (G2_PE / SE_GAIN_PE, ext["ExtEff"]),
         "source": "derived from 0 and 2"},
        {"name": "Gas-gap settings in NEST",
         "value": "gas gap %.0f mm, field in the gas %.2f kV/cm and light collection in the gas %.3f, tuned so that NEST returns the two numbers above; NEST default S2 Fano factor %.2f"
         % (ext["gasGap"], GAS_FIELD_KV_CM, G1_GAS, det.s2Fano), "source": "assumed"},
        {"name": "Liquid xenon", "value": "%.1f K, %.2f bar, density %.3f g/cm³ from NEST (published: 176.8 K, 1.89 bar; NEST treats that point as gas)"
         % (TEMPERATURE_K, PRESSURE_BAR, det.density_liquid), "source": 0},
        {"name": "Geometry", "value": "drift length 1486 mm, liquid level 5 mm above the gate, anode 8 mm above the gate; events at the centre, no electron loss, so corrected and raw areas coincide",
         "source": "0 and 1"},
        {"name": "Photosensors", "value": "%d PMTs; double-photoelectron probability %.1f and single-photoelectron resolution %.2f (typical R11410 values); channel threshold %.2f PE; single-photoelectron acceptance %.3f"
         % (N_PMT, P_DPE, SPE_RES, SPE_THR, SPE_EFF), "source": "0 and 1; double-photoelectron probability and resolution assumed"},
        {"name": "S1 requirement", "value": "3-fold coincidence with NEST's rule: at least 3 photons counted above the channel threshold, in different PMTs; no cut on the S1 area",
         "source": 0},
        {"name": "S2 threshold", "value": "cS2 of at least 120 PE", "source": 1},
        {"name": "Electronic-recoil band", "value": "flat spectrum, 0-10 keV, NEST beta model", "source": "assumed"},
        {"name": "Nuclear-recoil median", "value": "flat spectrum, %.1f-40 keV, NEST nuclear-recoil model" % E_MIN_KEV, "source": "assumed"},
        {"name": "Isolated-S1 spectrum (accidentals)",
         "value": "3 counted photons plus a geometric excess of mean 1.2; 3% flat tail from 3 to 40; areas from the same single- and double-photoelectron response",
         "source": "assumed"},
        {"name": "Isolated-S2 spectrum (accidentals)",
         "value": "power law n^-2 in extracted electrons, n = 2 to 400, each pulse built by NEST's S2 routine, cut at 120 PE. "
                  "The accidental background is flat across the three cS2 bins of the published ⁸B search, which were chosen to hold equal numbers of accidentals; "
                  "their edges (about 156 and 233 PE up to 500 PE in SR1, 166 and 248 PE in SR0) imply a spectrum close to cS2^-2 after all selections. "
                  "Used beyond 500 PE as an extrapolation",
         "source": "read from Fig. 2 of ref. 1; approximate"},
        {"name": "Simulated events", "value": "%d above thresholds per population; contours from a histogram smoothed by %.1f PE and %.2f dex" % (N_EVENTS, SMOOTH_X, SMOOTH_LOGY),
         "source": "assumed"},
    ]

    figure = {
        "id": "templates-cs1-cs2",
        "title": "Where accidental coincidences fall, compared with a WIMP signal",
        "caption": ("Regions holding 50% (filled) and 90% (outline) of each population that has a 3-fold S1 and a cS2 above "
                    "120 PE in a XENONnT-like detector, simulated with NEST. Accidental coincidences pile up in the low-cS1, "
                    "low-cS2 corner, on top of a 6 GeV/c² WIMP and of ⁸B solar neutrinos, while a 50 GeV/c² WIMP mostly lies "
                    "outside it along the nuclear-recoil band."),
        "disclaimer": ("Illustrative toy model: recoils simulated with public software and published detector numbers, accidental "
                       "coincidences from assumed isolated-S1 and isolated-S2 spectra; not data or a published template of any experiment."),
        "x": {"label": "cS1 [PE]", "min": 0, "max": 30, "scale": "linear", "ticks": [0, 5, 10, 15, 20, 25, 30]},
        "y": {"label": "cS2 [PE]", "min": 100, "max": 5000, "scale": "log", "ticks": [100, 200, 500, 1000, 2000, 5000]},
        "thresholds": [{"axis": "y", "value": 120, "label": "S2 threshold"}],
        "s1_requirement": "3-fold PMT coincidence, no cut on the S1 area",
        "populations": populations,
        "bands": [
            {"id": "er", "label": "Electronic recoils", "median": er_med, "lower": er_lo, "upper": er_hi},
            {"id": "nr", "label": "Nuclear-recoil median", "median": nr_med},
        ],
        "overlap": overlap,
        "model": {
            "summary": ("Monte Carlo of a XENONnT-like dual-phase xenon TPC built from public software. WIMP recoil spectra come from "
                        "wimprates (spin-independent, standard halo model) and the ⁸B neutrino recoil spectrum from NEST. NEST then "
                        "gives the light and charge yields, their fluctuations and the detector response for a detector description "
                        "filled with published XENONnT numbers (g1, g2, single-electron gain, drift field, 3-fold S1 coincidence), "
                        "with the 120 PE S2 threshold of the ⁸B search and no further acceptance or selection. An accidental "
                        "coincidence is an isolated S1 and an isolated S2 drawn independently from two assumed spectra that fall "
                        "steeply from their thresholds, reflecting what is published qualitatively (isolated S1s are pile-ups of a "
                        "few PMT hits, isolated S2s are few-electron signals); they are assumed forms, not measured spectra. Contours "
                        "are highest-density regions in (cS1, log cS2), cut at the S2 threshold and at the edges of the plotted "
                        "window; fraction_in_view gives the share of each population inside the window."),
            "parameters": parameters,
            "yields_path": "nestpy %s (%s)" % (version("nestpy"), NEST_SOURCE),
            "software": software,
            "references": REFERENCES,
        },
    }
    info = {"efficiency": eff, "overlap_exact": exact, "bands_at_5_10_20": band_check, "gains": gains,
            "nest": {"g2_pe": g2_nest, "se_pe": se_nest, "ext": ext, "density": det.density_liquid},
            "cs1_low_edge": {k: float(np.quantile(v[0], 0.01)) for k, v in sims.items()}}
    return figure, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="path of the JSON file to write")
    args = ap.parse_args()
    figure, info = build()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(figure, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote", args.out)
    for key, value in info.items():
        print(key, value)


if __name__ == "__main__":
    main()
