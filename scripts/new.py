"""템플릿으로 새 문서를 만든다.

사용법:
    python scripts/new.py journal
    python scripts/new.py idea "아이디어 제목"
    python scripts/new.py experiment "실험 이름"
    python scripts/new.py blog|youtube|book "제목"
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
KINDS = ("journal", "idea", "experiment", "blog", "youtube", "book")


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.strip().lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-") or "untitled"


def next_idea_number() -> int:
    numbers = [int(p.name[:3]) for p in (ROOT / "ideas").glob("[0-9][0-9][0-9]-*.md")]
    return max(numbers, default=0) + 1


def target_path(kind: str, title: str, today: str) -> Path:
    slug = slugify(title)
    if kind == "journal":
        return ROOT / "journal" / f"{today}.md"
    if kind == "idea":
        return ROOT / "ideas" / f"{next_idea_number():03d}-{slug}.md"
    if kind == "experiment":
        return ROOT / "experiments" / f"{today}-{slug}" / "README.md"
    return ROOT / "content" / kind / f"{today}-{slug}.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="템플릿으로 새 문서 만들기")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("title", nargs="?", default="")
    args = parser.parse_args()

    if args.kind != "journal" and not args.title:
        parser.error(f"{args.kind}에는 제목이 필요합니다.")

    today = date.today().isoformat()
    path = target_path(args.kind, args.title, today)
    if path.exists():
        print(f"이미 있습니다: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1

    template = (TEMPLATES / f"{args.kind}.md").read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.format(title=args.title, date=today), encoding="utf-8")
    print(f"생성: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
