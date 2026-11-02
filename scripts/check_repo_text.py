"""全庫文字檢查。

用法：
    uv run --with opencc-python-reimplemented python scripts/check_repo_text.py

掃描 `git ls-files` 列出的每個文字檔，做兩項檢查，任一項有結果就 exit 1；
全部通過時印出 `OK` 並 exit 0。

文字檔判定：讀出位元組後，含 NUL 或無法以 UTF-8 解碼的檔案視為二進位檔
（圖片、字型等）並略過，不維護副檔名清單。

1. 名稱檢查：不分大小寫比對參考專案的名稱與作者帳號（樣式見 `_NAME_PATTERN`）。
   唯一允許的是 `LICENSE` 裡那一行原作者著作權聲明。樣式由片段組成，
   讓本檔不會命中自己。

2. 簡體字檢查：以 opencc 的 `s2t` 逐行轉換，結果與原文不同的行才進一步判定。
   `s2t` 會把一些繁體中文本來就在用的字換成另一個異體（例如 台→臺、
   衆→眾、裏→裡），這些不是違規。判定規則完全取自 OpenCC 自帶的字典，
   不另外維護任何字詞或行的清單：

   字元 c 為「僅簡體字」，若且唯若同時符合：
   a. c 是 `STCharacters`（簡→繁字表）的鍵，也就是 `s2t` 會改動它；
   b. c 不在自己的候選繁體字之中（例如「台」的候選含「台」，代表繁體也用）；
   c. c 不是 `TSCharacters`（繁→簡字表）的鍵（例如「衆」「裏」「爲」
      在 OpenCC 眼中是繁體字，只是另有異體）；
   d. c 不是 `TWVariantsRev`（臺灣用字→OpenCC 標準字）的鍵（例如「群」
      是臺灣標準字，OpenCC 標準卻寫「羣」）。

   一行在 `s2t` 下有變動、且含至少一個僅簡體字，才列為違規，並標出那些字。

   已知限制：OpenCC 列為繁簡共用的字（候選含自己，例如「台」「后」「价」
   「几」）單獨出現時不會被列出，因為逐字無法分辨是「平台」還是簡體用法；
   真正的簡體句子幾乎一定同時含有僅簡體字，整行仍會被抓到。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import opencc

_NAME_PATTERN = re.compile("|".join(["free" + "dom", "自" + "由", "mars" + "-tw"]), re.IGNORECASE)
_ALLOWED_NAME_LINES = {("LICENSE", "Copyright (c) 2026 " + "mars" + "-tw")}


def _load_dict(name: str) -> dict[str, list[str]]:
    path = Path(opencc.__file__).parent / "dictionary" / name
    table: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        key, _, values = raw.partition("\t")
        if key:
            table.setdefault(key, []).extend(values.split())
    return table


def _simplified_only_chars() -> set[str]:
    st = _load_dict("STCharacters.txt")
    traditional = _load_dict("TSCharacters.txt").keys() | _load_dict("TWVariantsRev.txt").keys()
    return {
        c
        for c, candidates in st.items()
        if len(c) == 1 and c not in candidates and c not in traditional
    }


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root, text=True).split("\0")
    converter = opencc.OpenCC("s2t")
    simplified_only = _simplified_only_chars()
    findings: list[str] = []

    for rel in filter(None, files):
        path = root / rel
        if not path.is_file():
            continue
        text = _read_text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _NAME_PATTERN.search(line) and (rel, line.strip()) not in _ALLOWED_NAME_LINES:
                findings.append(f"{rel}:{lineno}: [名稱] {line.strip()}")
            if converter.convert(line) != line:
                bad = sorted({c for c in line if c in simplified_only})
                if bad:
                    findings.append(f"{rel}:{lineno}: [簡體 {''.join(bad)}] {line.strip()}")

    if findings:
        print("\n".join(findings))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
