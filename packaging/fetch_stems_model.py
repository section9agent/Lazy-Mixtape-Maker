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

# All-In-One's eight small models (MIT), kept in Hugging Face's cache layout - without symbolic links, so they
# copy into the app cleanly - so the app finds them offline.
import shutil  # noqa: E402

from huggingface_hub import hf_hub_download  # noqa: E402

deep = ROOT / "packaging" / "deep-models"
FILES = ["harmonix-fold0-0vra4ys2.pth", "harmonix-fold1-3ozjhtsj.pth", "harmonix-fold2-gmgo0nsy.pth",
         "harmonix-fold3-i92b7m8p.pth", "harmonix-fold4-1bql5qo0.pth", "harmonix-fold5-x4z5zeef.pth",
         "harmonix-fold6-x7t226rq.pth", "harmonix-fold7-qwwskhg6.pth"]
for f in FILES:
    hf_hub_download(repo_id="taejunkim/allinone", filename=f, cache_dir=str(deep))
repo = deep / "models--taejunkim--allinone"
for link in list(repo.rglob("*")):
    if link.is_symlink():
        target = link.resolve()
        link.unlink()
        shutil.copyfile(target, link)
shutil.rmtree(repo / "blobs", ignore_errors=True)
for p in deep.rglob("*.lock"):
    p.unlink()
shutil.rmtree(deep / ".locks", ignore_errors=True)
got = sorted(p.name for p in repo.rglob("*.pth"))
print(got, sum(p.stat().st_size for p in repo.rglob("*") if p.is_file()) // 1000, "kB")
if len(got) != len(FILES):
    sys.exit("deep models missing")
