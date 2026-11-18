"""Download the stem model into packaging/stems-models for the "with stems" build (run by build.yml)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lazy_mixtape_maker.stems_worker import ensure_ffmpeg  # noqa: E402

models = ROOT / "packaging" / "stems-models"
models.mkdir(parents=True, exist_ok=True)
ensure_ffmpeg(str(ROOT / "build" / "stems-bin"))
from audio_separator.separator import Separator  # noqa: E402

Separator(model_file_dir=str(models), output_dir=str(ROOT / "build")).load_model("htdemucs.yaml")
print(sorted(os.listdir(models)))
if not (models / "htdemucs.yaml").exists():
    sys.exit("model missing")
