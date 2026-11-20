#!/bin/sh
# Builds the GitHub Pages site into _site/:
#   docs/*           the web remote, as is
#   robot/*.py       the robot code from src/, for the 🔧 Flash page
#   robot/index.json [{path, size, sha256}] for each file (see index_dir below)
# and stamps the build id (default: short commit SHA) into sw.js so installed copies update.
#   scripts/build_site.sh && python3 -m http.server -d _site
# To ship another folder of files (e.g. sketches/ for #3): copy it in and call index_dir on it.
set -eu
cd "$(dirname "$0")/.."
OUT=_site
BUILD=${BUILD:-$(git rev-parse --short=7 HEAD 2>/dev/null || echo dev)}

# index_dir DIR: writes DIR/index.json listing every file under DIR (relative paths, sorted).
index_dir() {
  python3 - "$1" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
files = []
for d, dirs, names in os.walk(root):
    dirs[:] = sorted(x for x in dirs if not x.startswith((".", "__")))
    for n in sorted(names):
        if n == "index.json" or n.startswith("."):
            continue
        p = os.path.join(d, n)
        data = open(p, "rb").read()
        files.append({"path": os.path.relpath(p, root).replace(os.sep, "/"),
                      "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
with open(os.path.join(root, "index.json"), "w") as f:
    json.dump({"files": files}, f, indent=1)
    f.write("\n")
print(f"{root}/index.json: {len(files)} files")
PY
}

rm -rf "$OUT"
cp -R docs "$OUT"
mkdir -p "$OUT/robot"
cp src/*.py "$OUT/robot/"
index_dir "$OUT/robot"

python3 - "$OUT/sw.js" "$BUILD" <<'PY'
import sys
path, build = sys.argv[1:]
s = open(path).read()
assert "__BUILD__" in s, "no __BUILD__ placeholder in sw.js"
open(path, "w").write(s.replace("__BUILD__", build))
PY
echo "built $OUT ($BUILD)"
