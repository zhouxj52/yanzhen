"""Fetch a pinned MIT TodoMVC example; adapt only module loading for local serving."""
from pathlib import Path
import hashlib
import json
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "ff43b02e59dfa604386bb382034b2cd07c2bcd8a"
BASE = f"https://raw.githubusercontent.com/tastejs/todomvc/{REVISION}/"


def main():
    destination = ROOT / "yanzhen" / "web" / "todomvc"
    destination.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "third_party" / "todomvc"
    upstream.mkdir(parents=True, exist_ok=True)
    pending = ["app.js", "index.html", "app.css"]
    hashes = {}
    while pending:
        name = pending.pop()
        if name in hashes:
            continue
        data = urllib.request.urlopen(BASE + "examples/javascript-es6/src/" + name, timeout=25).read()
        (upstream / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
        source = data.decode()
        for dependency in re.findall(r'from\s+["\']\./([^"\']+)["\']', source):
            pending.append(dependency if "." in dependency else dependency + ".js")
        if name.endswith(".js"):
            source = re.sub(r'(from\s+["\']\./[^"\']+?)(["\'])', lambda m: m[1] + ("" if m[1].endswith(".js") else ".js") + m[2], source)
            source = re.sub(r'import\s+["\'][^"\']+\.css["\'];?', "", source)
            source = re.sub(r'/\* HOT MODULE SPECIFIC \*/.*?window.addEventListener', "window.addEventListener", source, flags=re.S)
        if name == "index.html":
            source = source.replace('<script src="./base.js"></script>', '<link rel="stylesheet" href="./app.css"><script type="module" src="./app.js"></script>')
        (destination / name).write_text(source, encoding="utf-8")
    license_bytes = urllib.request.urlopen(BASE + "license.md", timeout=25).read()
    (upstream / "LICENSE").write_bytes(license_bytes)
    (destination / "LICENSE").write_bytes(license_bytes)
    (upstream / "SOURCE.json").write_text(json.dumps({"repository":"https://github.com/tastejs/todomvc","revision":REVISION,"path":"examples/javascript-es6/src","sha256":hashes,"modifications":"Served copy: explicit .js imports, remove webpack-only HMR and CSS imports; local presentation CSS. Store/model/controller/view logic retained."},indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
