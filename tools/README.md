# tools

`make_template_figure.py` produces the data behind the Home figure
"Where accidental coincidences fall, compared with a WIMP signal"
(`data/intro_figure.json`). It is **not needed to build the site**: `build.py`
only reads the JSON file. Run it only to regenerate or change the figure.

It is a small Monte Carlo built from public software:

- [wimprates](https://github.com/JelleAalbers/wimprates) for the WIMP recoil spectra;
- [NEST](https://github.com/NESTCollaboration/nest) through its Python bindings
  [nestpy](https://github.com/NESTCollaboration/nestpy) for the light and charge
  yields, their fluctuations and the detector response, and for the ⁸B
  neutrino recoil spectrum;
- numpy for everything else (histograms, contours).

The accidental-coincidence population is drawn from assumed isolated-S1 and
isolated-S2 spectra; all numbers and their sources are listed in the script and
written to `model.parameters` in the output.

## Running it

Use a virtual environment so that nothing is installed system-wide:

```
python3 -m venv venv-figure
venv-figure/bin/pip install -r tools/requirements.txt
venv-figure/bin/python tools/make_template_figure.py --out data/intro_figure.json
```

A run takes a few minutes. The random generators (numpy's and NEST's own) start
from fixed states, so the pinned versions reproduce the file byte for byte.
nestpy ships binary wheels for common platforms; elsewhere pip builds it from
source, which needs CMake and a C++17 compiler.

Note that NEST is distributed under its own licence terms and nestpy's package
metadata carries the GPL-3.0 text; this script only calls them and bundles
neither.
