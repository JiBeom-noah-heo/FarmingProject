"""설문·리뷰·문의 글을 Claude로 분류·요약해 엑셀 결과표와 요약 리포트를 만든다.

처리 순서:
    1. 분류 기준 정하기  — 직접 주거나(--categories), 샘플을 읽고 Claude가 제안
    2. 분류하기          — 20개씩 묶어 주분류·부분류·감성·한줄요약
    3. 집계하기          — 숫자는 코드(pandas)로 계산 (AI가 숫자를 지어내지 않게)
    4. 리포트 쓰기       — 집계표와 요약을 바탕으로 Claude가 리포트 작성

사용법:
    python classify.py sample_survey.csv --column 주관식응답 --score-column 만족도
    python classify.py reviews.xlsx --column 리뷰 --categories "배송,가격,품질"
    python classify.py data.csv --column 문의 --model claude-haiku-4-5   # 저렴하게

API 키는 환경 변수 ANTHROPIC_API_KEY 로 전달한다 (.env.example 참고).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic
import pandas as pd

DEFAULT_MODEL = "claude-opus-5"
BATCH_SIZE = 20
SENTIMENTS = ["긍정", "부정", "중립", "혼합"]
OTHER = "기타"
NONE = "없음"

# 비용 추정용 가격표 (USD per 1M 토큰: 입력, 출력) — 2026-09 기준
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

SYSTEM_PROMPT = """당신은 고객의 목소리(설문 주관식, 리뷰, 문의)를 분석하는 전문가입니다.
글쓴이의 의도를 존중해 정확하게 분류하고, 요약은 원문에 없는 내용을 더하지 않습니다.
모든 결과는 한국어로 작성합니다 (원문이 외국어여도 요약은 한국어)."""


# ---------------------------------------------------------------------------
# Claude 호출
# ---------------------------------------------------------------------------

class Claude:
    """Claude API 호출과 토큰 사용량 집계를 맡는다."""

    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.input_tokens = 0
        self.output_tokens = 0

    def ask(self, prompt: str, schema: dict | None = None, effort: str = "low") -> str:
        output_config = {}
        if schema:
            # 구조화된 출력: 응답이 항상 이 JSON 스키마를 따르도록 보장
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if not self.model.startswith("claude-haiku"):
            # 분류·요약은 low로 충분하다 (Haiku는 effort 설정을 지원하지 않음)
            output_config["effort"] = effort

        request = dict(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
        )
        if self.model == "claude-opus-5":
            # 안전 필터가 요청을 거절하면 서버가 다른 모델로 자동 재시도
            response = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request
            )
        else:
            response = self.client.messages.create(**request)

        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens

        if response.stop_reason == "refusal":
            raise RuntimeError("Claude가 이 요청을 처리하지 않았습니다 (refusal).")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("응답이 너무 길어 잘렸습니다. BATCH_SIZE를 줄여 보세요.")
        return next(b.text for b in response.content if b.type == "text")

    def ask_json(self, prompt: str, schema: dict, effort: str = "low") -> dict:
        return json.loads(self.ask(prompt, schema, effort))

    def cost_usd(self) -> float | None:
        if self.model not in PRICES:
            return None
        price_in, price_out = PRICES[self.model]
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


# ---------------------------------------------------------------------------
# 1. 분류 기준 정하기
# ---------------------------------------------------------------------------

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["categories"],
    "additionalProperties": False,
}


def propose_categories(claude: Claude, texts: list[str], sample_size: int = 150) -> list[dict]:
    sample = texts[:sample_size]
    prompt = (
        "아래는 고객 응답 샘플입니다. 전체 응답을 분류할 주제 카테고리를 5~8개 제안해 주세요.\n"
        "- 카테고리 이름은 2~6글자의 짧은 명사로 (예: 배송, 가격·혜택)\n"
        "- 서로 겹치지 않게, 실제 응답에 자주 나오는 주제 위주로\n"
        f"- '{OTHER}'는 자동으로 추가되므로 제안하지 마세요\n"
        "- description에는 어떤 응답이 이 카테고리에 속하는지 한 문장으로\n\n"
        + "\n".join(f"- {t}" for t in sample)
    )
    categories = claude.ask_json(prompt, CATEGORY_SCHEMA)["categories"]
    return [c for c in categories if c["name"] != OTHER]


# ---------------------------------------------------------------------------
# 2. 분류하기
# ---------------------------------------------------------------------------

def classify_schema(category_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "main_category": {"type": "string", "enum": category_names},
                        "sub_category": {"type": "string", "enum": category_names + [NONE]},
                        "sentiment": {"type": "string", "enum": SENTIMENTS},
                        "summary": {"type": "string"},
                    },
                    "required": ["id", "main_category", "sub_category", "sentiment", "summary"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def classify_batch(claude: Claude, items: list[dict], categories: list[dict]) -> dict[str, dict]:
    names = [c["name"] for c in categories]
    guide = "\n".join(f"- {c['name']}: {c['description']}" for c in categories)
    prompt = (
        f"아래 고객 응답 {len(items)}개를 각각 분류해 주세요.\n\n"
        f"## 카테고리\n{guide}\n\n"
        "## 규칙\n"
        "- main_category: 가장 중심이 되는 주제 하나\n"
        f"- sub_category: 두 번째 주제가 있으면 그 카테고리, 없으면 '{NONE}'\n"
        "- sentiment: 긍정 / 부정 / 중립 / 혼합(좋은 점과 아쉬운 점이 함께 있음)\n"
        "- summary: 응답의 핵심을 20자 안팎의 한 줄로\n"
        "- 모든 id에 대해 빠짐없이 결과를 주세요\n\n"
        "## 응답\n"
        + "\n".join(json.dumps(item, ensure_ascii=False) for item in items)
    )
    results = claude.ask_json(prompt, classify_schema(names))["results"]
    return {r["id"]: r for r in results}


def classify_all(claude: Claude, items: list[dict], categories: list[dict]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        print(f"  분류 중… {start + len(batch)}/{len(items)}")
        results.update(classify_batch(claude, batch, categories))

    missing = [item for item in items if item["id"] not in results]
    if missing:
        print(f"  누락된 {len(missing)}개 다시 분류")
        results.update(classify_batch(claude, missing, categories))
    return results


# ---------------------------------------------------------------------------
# 개인정보 가리기
# ---------------------------------------------------------------------------

PII_PATTERNS = [
    (re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"), "[전화번호]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[이메일]"),
]


def mask_pii(text: str) -> str:
    """전화번호·이메일을 가린다. 외부 AI로 보내기 전 최소한의 안전장치."""
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# 3. 집계하기
# ---------------------------------------------------------------------------

def summarize_by_category(df: pd.DataFrame, score_column: str | None) -> pd.DataFrame:
    classified = df[df["주분류"].notna() & ~df["주분류"].str.startswith("(")]
    table = pd.crosstab(classified["주분류"], classified["감성"])
    table = table.reindex(columns=SENTIMENTS, fill_value=0)
    table.insert(0, "응답수", table.sum(axis=1))
    table.insert(1, "비율", (table["응답수"] / table["응답수"].sum()).round(3))
    if score_column:
        scores = pd.to_numeric(classified[score_column], errors="coerce")
        table["평균" + score_column] = scores.groupby(classified["주분류"]).mean().round(2)
    return table.sort_values("응답수", ascending=False).reset_index()


# ---------------------------------------------------------------------------
# 4. 리포트 쓰기
# ---------------------------------------------------------------------------

def write_report(claude: Claude, df: pd.DataFrame, summary: pd.DataFrame, question: str) -> str:
    by_category = []
    for name, group in df.groupby("주분류"):
        if name.startswith("("):
            continue
        lines = [f"[{row['감성']}] {row['한줄요약']}" for _, row in group.head(40).iterrows()]
        by_category.append(f"### {name} ({len(group)}건)\n" + "\n".join(lines))

    prompt = (
        f"설문 문항: {question}\n\n"
        "아래 집계표와 카테고리별 응답 요약을 바탕으로 의사결정자가 읽을 분석 리포트를 마크다운으로 써 주세요.\n\n"
        "## 구성\n"
        "1. 한눈에 보기 (핵심 3줄)\n"
        "2. 개선이 가장 시급한 문제 Top 3 — 각각 근거가 되는 건수와 대표 응답 요약\n"
        "3. 고객이 좋아하는 점 — 지켜야 할 강점\n"
        "4. 카테고리별 주요 내용 (카테고리마다 2~3줄)\n"
        "5. 바로 해볼 수 있는 개선 제안 3가지\n\n"
        "## 규칙\n"
        "- 숫자는 아래 집계표에 있는 값만 사용하고, 새로 계산하거나 지어내지 마세요\n"
        "- 제목(#)은 쓰지 말고 ## 부터 시작하세요\n\n"
        f"## 집계표\n{summary.to_markdown(index=False)}\n\n"
        "## 카테고리별 응답 요약\n" + "\n\n".join(by_category)
    )
    return claude.ask(prompt, effort="medium")


# ---------------------------------------------------------------------------
# 입출력
# ---------------------------------------------------------------------------

def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def save_excel(path: Path, df: pd.DataFrame, summary: pd.DataFrame, categories: list[dict]) -> None:
    criteria = pd.DataFrame(categories).rename(columns={"name": "카테고리", "description": "설명"})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in [("분류결과", df), ("카테고리요약", summary), ("분류기준", criteria)]:
            frame.to_excel(writer, sheet_name=sheet, index=False)
            worksheet = writer.sheets[sheet]
            worksheet.freeze_panes = "A2"
            for column_cells in worksheet.columns:
                longest = max(len(str(c.value or "")) for c in column_cells)
                width = min(max(longest * 1.6, 8), 60)  # 한글은 폭이 넓어 1.6배
                worksheet.column_dimensions[column_cells[0].column_letter].width = width


def run(
    input_path: Path,
    column: str,
    out_dir: Path,
    categories: list[str] | None = None,
    score_column: str | None = None,
    question: str = "",
    model: str = DEFAULT_MODEL,
    client=None,
) -> tuple[Path, Path]:
    df = read_table(input_path)
    if column not in df.columns:
        raise SystemExit(f"'{column}' 열이 없습니다. 있는 열: {', '.join(df.columns)}")

    claude = Claude(model, client)
    df["_id"] = [f"row{i}" for i in range(len(df))]
    texts = df[column].fillna("").astype(str).str.strip()
    items = [
        {"id": row_id, "text": mask_pii(text)}
        for row_id, text in zip(df["_id"], texts) if text
    ]
    print(f"응답 {len(df)}개 중 내용이 있는 {len(items)}개를 분석합니다 (모델: {model})")

    print("1/4 분류 기준 정하기")
    if categories:
        category_list = [{"name": name, "description": ""} for name in categories]
    else:
        category_list = propose_categories(claude, [item["text"] for item in items])
    category_list.append({"name": OTHER, "description": "어느 카테고리에도 속하지 않는 응답"})
    print("  " + ", ".join(c["name"] for c in category_list))

    print("2/4 분류하기")
    results = classify_all(claude, items, category_list)

    def pick(row_id: str, text: str, key: str) -> str:
        if not text:
            return "(빈 응답)" if key == "main_category" else ""
        if row_id not in results:
            return "(분류 실패)" if key == "main_category" else ""
        return results[row_id][key]

    for key, label in [("main_category", "주분류"), ("sub_category", "부분류"),
                       ("sentiment", "감성"), ("summary", "한줄요약")]:
        df[label] = [pick(i, t, key) for i, t in zip(df["_id"], texts)]
    df = df.drop(columns="_id")

    print("3/4 집계하기")
    summary = summarize_by_category(df, score_column)

    print("4/4 리포트 쓰기")
    report_body = write_report(claude, df, summary, question or column)

    out_dir.mkdir(parents=True, exist_ok=True)
    excel_path = out_dir / f"{input_path.stem}_분류결과.xlsx"
    report_path = out_dir / f"{input_path.stem}_리포트.md"
    save_excel(excel_path, df, summary, category_list)

    cost = claude.cost_usd()
    cost_line = f"약 ${cost:.2f}" if cost is not None else "가격표에 없는 모델"
    report_path.write_text(
        f"# 고객 응답 분석 리포트: {input_path.name}\n\n"
        f"- 분석 대상: {len(items)}개 응답 (`{column}` 열)\n"
        f"- 분석 모델: {model}\n\n"
        f"## 카테고리별 집계\n\n{summary.to_markdown(index=False)}\n\n"
        f"{report_body}\n",
        encoding="utf-8",
    )

    print(f"\n완료: {excel_path}\n      {report_path}")
    print(f"토큰: 입력 {claude.input_tokens:,} / 출력 {claude.output_tokens:,} → API 비용 {cost_line}")
    return excel_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="고객 응답 AI 분류·요약")
    parser.add_argument("input", type=Path, help="CSV 또는 엑셀 파일")
    parser.add_argument("--column", required=True, help="분석할 글이 있는 열 이름")
    parser.add_argument("--categories", help="쉼표로 구분한 카테고리 (없으면 AI가 제안)")
    parser.add_argument("--score-column", help="카테고리별 평균을 낼 점수 열 (예: 만족도)")
    parser.add_argument("--question", default="", help="설문 문항 (리포트 맥락용)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    args = parser.parse_args()

    categories = [c.strip() for c in args.categories.split(",")] if args.categories else None
    try:
        run(args.input, args.column, args.out_dir, categories,
            args.score_column, args.question, args.model)
    except anthropic.AuthenticationError:
        sys.exit("API 키가 올바르지 않습니다. ANTHROPIC_API_KEY 환경 변수를 확인하세요.")


if __name__ == "__main__":
    main()
