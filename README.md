# VTHacks14

Spatial intelligence dashboard and interactive 3D modeling workspace built for VTHacks 14.

## Run locally

No build step or package install is required. From the repository root, run:

```bash
python3 -m http.server 8080 --directory dist
```

Then open <http://localhost:8080>.

## Project structure

```text
.
├── dist/
│   ├── index.html   # Application markup
│   ├── styles.css   # Interface styling
│   └── app.js       # Dashboard and 3D interactions
├── .openai/
│   └── hosting.json # Static hosting configuration
└── README.md
```

The deployable static site lives in `dist/`, matching the hosting configuration.
