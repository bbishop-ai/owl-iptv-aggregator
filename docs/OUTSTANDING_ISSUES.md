# Outstanding issues

- Owl does not publicly document whether it follows M3U `url-tvg`/`x-tvg-url`; separate XMLTV setup is therefore the supported path in these notes.
- GitHub Pages must be enabled once in repository settings. This is an account-level setting outside the repository contents.
- The first production channel count is inherently network- and region-dependent. After that run, raise the sanity floor from `1` to a useful last-known-good threshold.
- LAN multicast and live FOFA/ZoomEye discovery from walke2019 are inventoried but cannot run meaningfully or safely from a shared GitHub-hosted runner.
- Frozen-video detection uses a short sample. Deliberately static channels may be false positives; the result is conservative and is cached for a day.

