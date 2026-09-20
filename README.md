# Chess Set Creator Add-On for Blender 3D

A custom Blender 3D chess set creator that can generate **15,552 different chess set combinations** using different piece styles, materials, colors, and board appearances.

The main project is the **Fantasy Chess Set Generator v0.4.69** Blender extension. It creates complete themed chess sets, applies coordinated materials and colors, prepares render/showcase scenes, and supports exporting generated geometry.

A companion **Blender Colab Renderer** notebook is included for rendering finished `.blend` scenes with Cycles on a Google Colab NVIDIA GPU.

## What this repository contains

| File | Purpose |
| --- | --- |
| `fantasy_chess_generator-0.4.69.zip` | Installable Blender extension containing the chess-set creator source and manifest. |
| `blender_colab_renderer.ipynb` | Optional Google Colab workflow for GPU-rendering saved Blender scenes. |

## Features

- **15,552 possible chess set combinations**
- Complete board plus White and Black piece-set generation
- Multiple fantasy piece styles
- Material and color customization for both sides
- Configurable board appearance
- Render-scene setup
- Full-set showcase animation setup
- Individual-piece showcase setup
- STL, glTF, and GLB export
- Adjustable board dimensions and piece scale/resolution
- Optional Google Colab GPU rendering workflow

## Requirements

- **Blender 4.2.0 or newer** for the chess set creator extension
- The extension manifest declares **GPL-3.0-or-later**
- Google Colab is optional and only needed for the included GPU-rendering notebook

## Install the Blender add-on

1. Download `fantasy_chess_generator-0.4.69.zip` from this repository.
2. Open Blender.
3. Go to **Edit → Preferences → Get Extensions**.
4. Choose **Install from Disk**.
5. Select `fantasy_chess_generator-0.4.69.zip`.
6. Enable the extension if Blender does not enable it automatically.
7. If an older build of the same add-on is installed, disable or remove it to avoid duplicate registration.

The extension requests Blender's `files` permission because its export and video-render workflows write user-requested output files.

## Create a chess set

Open Blender's 3D Viewport sidebar with **N**, then choose the **Fantasy Chess** tab.

The add-on is organized into a workflow:

1. **Create** — choose a chess-set style and create the board, White set, and Black set.
2. **Materials** — choose materials/colors for White and Black pieces plus the board, then apply them.
3. **Chess Set Render Scene** — add a camera/light setup and optional high-quality still-render settings.
4. **Full Set Showcase** — create a showcase animation and video render settings.
5. **Individual Piece Showcase** — choose a piece, side, and background and create an individual-piece showcase.
6. **Export** — export selected mesh objects as STL, glTF, or GLB.
7. **Clear** — remove generated boards, piece sets, render scenes, or showcase objects.
8. **Board Settings** — adjust board geometry, square size, base height, tile height/gap, and border width.
9. **Piece Settings** — adjust piece scale and radial mesh resolution.

### Included styles and materials

This version includes the following piece styles:

- **Elves**
- **Samurai**
- **Dog & Cat**

Piece material families include:

- **Wood**
- **Glass**
- **Metal**
- **Stone**

Together with the available styles, side colors/material choices, and board appearances, the creator supports **15,552 distinct chess-set combinations**.

## Typical Blender workflow

1. Create the board and both piece sets.
2. Choose White and Black materials/colors.
3. Choose a board material/appearance.
4. Apply the materials.
5. Add a render scene or showcase setup.
6. Save the completed `.blend` file.
7. Render locally or use the optional Colab notebook.

## Optional: render with Google Colab

The included `blender_colab_renderer.ipynb` notebook is configured for Blender **5.2.0** and Cycles GPU rendering.

### Basic use

1. Open the notebook in Google Colab.
2. Choose **Runtime → Change runtime type → GPU**.
3. Put the `.blend` file you want to render in Google Drive.
4. Edit the notebook's basic configuration:

```python
BLEND_PATH = "/content/drive/MyDrive/Blender/chess.blend"
OUTPUT_DIR = "/content/drive/MyDrive/Blender/renders"
```

5. Select still or animation rendering and your desired output settings.
6. Choose a quality preset.
7. Use **Runtime → Run all**.

### Quality presets

| Preset | Cycles samples | Intended use |
| --- | ---: | --- |
| `FAST` | 256 | Quick previews and test stills |
| `MEDIUM` | 1024 | Balanced final still quality |
| `HIGH` | 4096 | Cleaner final stills at higher render cost |

The notebook supports PNG stills, PNG animation sequences, and MP4/H.264 video output.

For long Colab jobs, PNG sequences are generally more resilient because already-rendered frames can be skipped after an interrupted session.

## Project purpose

This repository exists to maintain and distribute the **Chess Set Creator Add-On for Blender 3D**: a customizable procedural chess-set generator capable of producing **15,552 combinations** across its available styles, materials, colors, and board configurations.
