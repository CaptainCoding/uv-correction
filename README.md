# UV Correction

UV Correction is a lightweight GUI tool for inspecting and correcting UV coordinates in USD meshes.

The app is built with `matplotlib` widgets and lets you:

- load a USD file and inspect UV points per mesh
- overlay an optional texture image
- select specific meshes and transform UVs interactively
- enter exact numeric transform values
- preview changes live before applying
- flip the texture view on X and/or Y for alignment checks
- export corrected UVs to a new USD file

## Requirements

- Python 3.12+
- `uv` (package/environment manager)

## Installation

```bash
uv sync
```

## Usage

Run via module script file:

```bash
uv run uv_correction.py /path/to/file.usd --texture /path/to/texture.jpg
```

Or run via project entry point:

```bash
uv run uv-correction /path/to/file.usd --texture /path/to/texture.jpg
```

Accepted texture flags:

- `--texture`
- `-t`
- `-texture` (legacy shorthand)

## GUI Controls

- `Meshes`: checkbox list for mesh selection
- `Scale U`, `Scale V`, `Offset U`, `Offset V`: sliders for interactive tuning
- numeric boxes next to sliders: exact value input
- `Auf Auswahl anwenden`: permanently apply current transform to selected meshes
- `Auf ALLE anwenden`: apply transform to all meshes
- `Zuruecksetzen`: reset selected meshes to original UVs and reset controls
- `Texture X Flip`, `Texture Y Flip`: toggle texture preview orientation
- `Exportieren`: writes a corrected file next to the source as:
	- `<original_name>_corrected.usda`

## Notes

- Live preview is enabled by default for selected meshes.
- UV modifications are stored in memory until you export.
- The texture flip options affect only visualization, not UV data.