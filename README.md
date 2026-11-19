# Isolated S1/S2 R&D Map

A world map of the R&D setups and running experiments that study where isolated S1 and isolated S2 signals come from, the two ingredients of the accidental-coincidence background in liquid xenon and liquid argon TPCs. The site has five views: Home (a short introduction to the background), Map (the setups, as a map or a list), Sources (where in a dual-phase TPC each candidate source arises), Publications (every paper, thesis and talk cited) and About.

Live site: https://acmap.rarephysics.com

## Disclosure

Compiled with AI research agents from public papers, preprints, theses and talks. Not reviewed by the collaborations or groups described. "Sources opened" means an agent opened the link and it resolved to the stated work; it does not mean a person checked the content. "Abstract-level check" means the entry was found and checked at abstract or landing-page level only.

Corrections and missing setups are welcome: open an issue or a pull request.

## How the repository is organised

| Path | What it is |
|---|---|
| `data/setups.json` | The setups and experiments shown on the map and in the list |
| `data/sources.json` | The detector view: candidate sources of isolated S1/S2, the categories that group them, the regions of the drawing, the pairing text, references, and the credit for the overview talk |
| `data/intro.json` | The introduction on the Home view: title, lede, three key facts, sections, glossary and its references |
| `data/meta.json` | The mechanism key A–I, the list of other known setups not yet documented, the names of past detectors left out |
| `src/template.html` | The whole page (markup, styles, script) with two placeholders for the data and the map geometry |
| `vendor/countries-50m.json` | World geometry (world-atlas 2.0.2, from Natural Earth); see `vendor/README.md` |
| `build.py` | Validates the data and writes `site/index.html`; Python 3 standard library only |
| `Dockerfile`, `nginx.conf` | Builds the site and serves it with nginx on port 8080 as a non-root user |
| `docker-stack.yml` | Docker Swarm stack behind Traefik |

The built page is a single file. At view time it loads three pinned scripts (d3 7.9.0 and topojson-client 3.0.2 from cdnjs, d3-geo-projection 4.0.0 from jsDelivr, each with a subresource-integrity hash) and the IBM Plex Sans stylesheet from Google Fonts. It sets no cookies and has no analytics.

## Build locally

```
python3 build.py
```

Then open `site/index.html` in a browser. `python3 build.py --date 2026-11-19` sets the build date shown on the page; the default is today.

The build stops with a non-zero exit code if the data fails validation (duplicate ids, a source pointing to a setup that does not exist, a measurement `ref` outside its reference list, missing required fields, coordinates out of range) or if a text field contains working-note wording that should not be published.

## Run with Docker

```
docker build -t donnabla/ac-rnd-map .
docker run --rm -p 8080:8080 donnabla/ac-rnd-map
```

The site is then at http://localhost:8080 and `http://localhost:8080/healthz` returns 200.

## Deploy the stack

On a Swarm manager with Traefik attached to an external overlay network named `public`:

```
docker stack deploy -c docker-stack.yml acmap
```

The stack routes `acmap.rarephysics.com` to the container on port 8080, with TLS from the `letsencrypt` certificate resolver and a permanent redirect from HTTP to HTTPS.

## Contribute a correction or a new setup

Edit `data/setups.json`, run `python3 build.py`, check the page, and open a pull request. If you would rather not edit JSON, open an issue with the setup name, institute, location and links to the public work.

Fields of one setup:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Lower-case letters, digits and hyphens; unique; used in the page link `#<id>` |
| `name` | yes | Full name shown in the panel |
| `short_name` | no | Short label for the map and the matrix |
| `kind` | yes | `lab` (shown as "R&D setup") or `in-situ` (shown as "Experiment") |
| `target` | yes | `xenon`, `argon`, `both` or `materials` |
| `phase` | yes | `running`, `construction`, `completed` or `unknown`; for an experiment, the state of the detector |
| `phase_inferred` | no | `true` when the phase was derived from the active years |
| `study_status` | no | For experiments: the state of this particular study |
| `provenance` | yes | `opened` ("Sources opened"), `abstract` ("Abstract-level check") or `unchecked` |
| `confidence` | no | `high`, `medium` or `low`: how fully the sources support the description |
| `institute`, `collaboration` | no | Host institute and collaboration |
| `people` | no | PI or group leader (R&D setups only; one name, or one per site) |
| `city`, `country`, `country_code` | no | Location; `country_code` is ISO 3166 alpha-2 |
| `lat`, `lon` | no | Coordinates of the laboratory or detector, both or neither |
| `location_note` | no | One sentence on what the pin marks |
| `medium` | no | Free text, for example `Xe`, `Ar`, `vacuum` |
| `years_active`, `first_year` | no | Free text range, and the first year as a number |
| `description`, `key_results` | no | Plain text |
| `measurements` | no | List of `{what, result, year, ref}`; `ref` is the 0-based index into `references`, or `null` |
| `tags` | no | Mechanism tags, letters `A` to `I` (key in `data/meta.json`) |
| `tags_inferred` | no | `true` when the tags were inferred by keyword from `mechanisms` |
| `mechanisms` | no | List of free-text mechanisms |
| `caveats` | no | List of sentences |
| `references` | no | List of `{title, authors, year, venue, url, type, verified}`; `type` is `paper`, `arXiv`, `thesis`, `talk`, `poster` or `web`; `url` may be `null`; `verified` is `true` when the link was opened and resolved to the stated work |

A source in `data/sources.json` has `id`, `name`, `signal` (`S1`, `S2`, `both`), `medium` (`xenon`, `argon`, `both`), `region` and `extra_regions` (ids from the `regions` list), `evidence` (`established`, `supported`, `hypothesised`), optional `importance`, the text fields `mechanism`, `chain`, `timescale`, `correlated_with`, `mitigation`, `key_numbers` (`{text, ref}`), `setups` (ids from `data/setups.json`), `past_setups` (plain names) and `references`.

The `categories` list in the same file groups the sources for the figure: each has `id`, `signal` (`S1` or `S2`), `name`, `summary` and `sources` (source ids). Every source lists its category ids in `categories`, and the two must agree; the build checks this.

The introduction in `data/intro.json` has `title`, `lede`, `key_facts` (exactly three `{value, label, ref}`), `sections` (`{id, heading, paragraphs, formula, refs}` with the ids `what`, `rate`, `why`, `xenon`, `argon`, `handling`, `open`), `glossary` (`{term, definition}`) and `references`. A citation is written `[n]` in the text, where n counts from 1 in `references`; `ref` and `refs` are 0-based indices. The build checks that every citation resolves. If the file is missing, the Home view says the introduction is pending.

The Publications view is not stored: the build merges the references of all setups, sources and the introduction and removes duplicates by link (or by title and year when there is no link).

## Credits

- Detector view: after the overview by M. Wada, "Accidental Coincidence Backgrounds in Double-Phase TPC Dark Matter Detectors", LIDINE 2026, and the LIDINE 2026 round table on lone S1 and S2 signals and accidental coincidences. The drawing is schematic and redrawn.
- Map geometry: Natural Earth, via world-atlas.
- Libraries: d3, topojson-client, d3-geo-projection. Typeface: IBM Plex Sans.

## Licences

- Code: MIT, see `LICENSE`.
- Content (the files in `data/` and the text and drawing in `src/template.html`): CC BY 4.0, see `LICENSE-CONTENT`.
- `vendor/countries-50m.json`: ISC (world-atlas), built from public-domain Natural Earth data.
