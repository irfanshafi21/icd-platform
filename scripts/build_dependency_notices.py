"""Generate notices from the installed runtime, not guessed dependency versions."""
import importlib.metadata
import json
from pathlib import Path


def inventory():
    packages = []
    for dist in importlib.metadata.distributions():
        notices = []
        for file in dist.files or []:
            name = str(file).lower()
            if ".dist-info/" in name and any(part in file.name.lower() for part in ("license", "copying", "notice")):
                path = Path(dist.locate_file(file))
                if path.is_file():
                    notices.append({"name": file.name, "text": path.read_text(encoding="utf-8", errors="replace")})
        packages.append({"name": dist.metadata.get("Name"), "version": dist.version,
                         "license": dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See upstream project",
                         "notices": notices})
    return {"scope": "Installed Python distributions. Bundled fonts, images and JavaScript assets require separate review.",
            "packages": sorted(packages, key=lambda p: str(p["name"]).lower())}


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "web" / "third-party-notices.json"
    output.write_text(json.dumps(inventory(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("Dependency notices generated")
