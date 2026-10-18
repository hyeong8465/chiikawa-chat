"""재생목록의 본편 자막을 data/raw/에 수집. 사용: uv run python scripts/fetch_subs.py [--only N]"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from scripts.vtt import parse
except ImportError:  # 직접 실행 시
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.vtt import parse

PLAYLIST = "https://www.youtube.com/playlist?list=PLsmaUhkCwW3q5q46uc9So2b4D-pZqVZOV"
RAW = Path("data/raw")


def select_episodes(entries: list[tuple[str, str]]) -> list[tuple[int, str, str]]:
    """(id, title) → (화수, id, title). 본편만, 화수 중복은 첫 항목."""
    seen: dict[int, tuple[int, str, str]] = {}
    for vid, title in entries:
        m = re.search(r"(\d+)화", title)
        if not title.startswith("[전편공개]") or not m:
            continue
        ep = int(m.group(1))
        if ep in seen:
            print(f"경고: {ep}화 중복, 건너뜀: {vid} {title}")
            continue
        seen[ep] = (ep, vid, title)
    return sorted(seen.values())


def _ytdlp(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["yt-dlp", *args], capture_output=True, text=True)


def list_entries() -> list[tuple[str, str]]:
    r = _ytdlp("--flat-playlist", "--print", "%(id)s\t%(title)s", PLAYLIST)
    if r.returncode != 0:
        sys.exit(f"재생목록 조회 실패: {r.stderr.strip()}")
    return [tuple(l.split("\t", 1)) for l in r.stdout.splitlines() if "\t" in l]


def build_index(episodes: list[tuple[int, str, str]], raw_dir: Path) -> list[dict]:
    """.txt가 있는 화만 화수순으로."""
    return [
        {"episode": ep, "title": title, "url": f"https://www.youtube.com/watch?v={vid}"}
        for ep, vid, title in sorted(episodes)
        if (raw_dir / f"{ep:03d}.txt").exists()
    ]


def download_vtt(ep: int, vid: str) -> Path | None:
    for old in (RAW / f"{ep:03d}.ko.vtt", RAW / f"{ep:03d}.vtt"):
        old.unlink(missing_ok=True)  # 이전 실패분 제거
    r = _ytdlp(
        "--skip-download", "--write-auto-subs", "--sub-langs", "ko", "--sub-format", "vtt",
        "--sleep-requests", "1", "--sleep-subtitles", "2",
        "-o", str(RAW / f"{ep:03d}"), f"https://www.youtube.com/watch?v={vid}",
    )
    src = RAW / f"{ep:03d}.ko.vtt"
    if r.returncode != 0 or not src.exists():
        return None
    dst = RAW / f"{ep:03d}.vtt"
    src.replace(dst)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="이 화수만 받기")
    only = ap.parse_args().only

    if not shutil.which("yt-dlp"):
        sys.exit("yt-dlp가 없음. 설치 필요: brew install yt-dlp")
    RAW.mkdir(parents=True, exist_ok=True)

    episodes = select_episodes(list_entries())
    targets = episodes if only is None else [e for e in episodes if e[0] == only]
    got = skipped = failed = 0
    for ep, vid, title in targets:
        txt = RAW / f"{ep:03d}.txt"
        if txt.exists():
            skipped += 1
            continue
        vtt = download_vtt(ep, vid)
        lines = parse(vtt.read_text(encoding="utf-8")) if vtt else []
        if not lines:
            print(f"경고: {ep}화 자막 받기 실패")
            failed += 1
            continue
        txt.write_text("\n".join(lines), encoding="utf-8")
        got += 1
        print(f"{ep}화 완료 ({len(lines)}줄)")

    index = build_index(episodes, RAW)
    (RAW / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"받음 {got} / 건너뜀 {skipped} / 실패 {failed}")


if __name__ == "__main__":
    main()
