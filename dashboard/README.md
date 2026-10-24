# GitHub Stats Dashboard

A responsive React dashboard for the live GitHub stats generated for this profile.

## Run locally

```sh
npm install
npm run dev
```

To create and preview a production build:

```sh
npm run build
npm run preview
```

`public/stats.json` is refreshed by `profile/scripts/generate_stats.py` in the
daily GitHub Actions workflow. The dashboard reads that generated file at
runtime, so no GitHub token or API credentials are exposed in the browser.
