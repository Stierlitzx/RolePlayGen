# Backlog

What is planned, in progress or rejected. Items here must come from the code (TODO comments), the docs, or an explicit user request — never invented. When work starts, move the item to "In progress" and add a `planned` row to `FEATURES.md`; when it is done, remove it here and switch the row to `done`.

## In progress

_Nothing right now._

## Planned

- **FaceDetailer/ADetailer for wide scenes.** Known SDXL limitation: faces of distant characters smear in wide shots. The fix is a FaceDetailer/ADetailer node added to `comfy_workflows/*.json` (user-side, no backend change — the node needs no inputs from the app). Watch the extra VRAM on an 8 GB card. Mentioned in `README.md` and the archived content-rating spec's definition of done.

## Rejected

_Nothing rejected so far. When a feature is dropped on purpose, list it here with the reason and set its `FEATURES.md` row to `rejected`._
