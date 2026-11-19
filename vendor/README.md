# Vendored geometry

`countries-50m.json` is the country geometry of [world-atlas](https://github.com/topojson/world-atlas) 2.0.2
(`https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json`), unmodified. It is TopoJSON built from
Natural Earth 1:50m cultural vectors.

- world-atlas: ISC licence, copyright Michael Bostock.
- Natural Earth data: public domain (naturalearthdata.com).

`build.py` thins this geometry at build time (small islands dropped, lines simplified) before inlining it in the page;
the file here stays as downloaded.
