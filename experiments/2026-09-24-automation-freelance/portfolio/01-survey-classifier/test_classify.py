"""classify.py 테스트 — 실제 API 대신 가짜 클라이언트로 전체 흐름을 확인한다."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from classify import mask_pii, run

SAMPLE = Path(__file__).with_name("sample_survey.csv")


class FakeMessages:
    """Claude 응답 흉내: 요청 내용을 보고 카테고리 제안 / 분류 / 리포트를 돌려준다."""

    def __init__(self, drop_first_id: bool = False):
        self.calls = []
        self.drop_first_id = drop_first_id

    def create(self, **request):
        self.calls.append(request)
        prompt = request["messages"][0]["content"]
        if "카테고리를 5~8개 제안" in prompt:
            text = json.dumps({"categories": [
                {"name": "배송", "description": "배송 속도·상태"},
                {"name": "고객센터", "description": "상담·교환·환불"},
            ]}, ensure_ascii=False)
        elif "각각 분류해 주세요" in prompt:
            ids = re.findall(r'"id": "(row\d+)"', prompt)
            if self.drop_first_id and len(self.calls) == 2:
                ids = ids[1:]  # 한 개를 빠뜨려 재시도 동작 확인
            text = json.dumps({"results": [
                {"id": i, "main_category": "배송", "sub_category": "없음",
                 "sentiment": "부정" if int(i[3:]) % 2 else "긍정", "summary": "요약"}
                for i in ids
            ]}, ensure_ascii=False)
        else:
            text = "## 한눈에 보기\n- 테스트 리포트"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


def fake_client(**kwargs):
    messages = FakeMessages(**kwargs)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages)), messages


def test_end_to_end(tmp_path):
    client, messages = fake_client()
    excel, report = run(SAMPLE, "주관식응답", tmp_path, score_column="만족도", client=client)

    result = pd.read_excel(excel, sheet_name="분류결과")
    assert len(result) == 100
    assert set(result["주분류"]) == {"배송"}
    assert set(result["감성"]) == {"긍정", "부정"}

    summary = pd.read_excel(excel, sheet_name="카테고리요약")
    assert summary.loc[0, "응답수"] == 100
    assert "평균만족도" in summary.columns

    criteria = pd.read_excel(excel, sheet_name="분류기준")
    assert list(criteria["카테고리"]) == ["배송", "고객센터", "기타"]

    # 카테고리 제안 1번 + 분류 5번(100개 / 20개) + 리포트 1번
    assert len(messages.calls) == 7
    # Opus 5는 거절 시 자동 재시도(fallbacks)를 켠다
    assert all(call["fallbacks"] == "default" for call in messages.calls)
    assert "테스트 리포트" in report.read_text(encoding="utf-8")


def test_given_categories_skip_proposal(tmp_path):
    client, messages = fake_client()
    run(SAMPLE, "주관식응답", tmp_path, categories=["배송", "가격"],
        model="claude-haiku-4-5", client=client)
    assert not any("카테고리를 5~8개 제안" in c["messages"][0]["content"] for c in messages.calls)
    # Haiku에는 effort·fallbacks를 보내지 않는다
    assert all("effort" not in c["output_config"] and "fallbacks" not in c for c in messages.calls)


def test_missing_results_are_retried(tmp_path):
    client, messages = fake_client(drop_first_id=True)
    excel, _ = run(SAMPLE, "주관식응답", tmp_path, client=client)
    result = pd.read_excel(excel, sheet_name="분류결과")
    assert "(분류 실패)" not in set(result["주분류"])
    assert len(messages.calls) == 8  # 재시도 1번 추가


def test_empty_rows_are_not_sent(tmp_path):
    data = tmp_path / "data.csv"
    pd.DataFrame({"글": ["배송 빨라요", "", None]}).to_csv(data, index=False, encoding="utf-8-sig")
    client, messages = fake_client()
    excel, _ = run(data, "글", tmp_path, client=client)
    result = pd.read_excel(excel, sheet_name="분류결과")
    assert list(result["주분류"]) == ["배송", "(빈 응답)", "(빈 응답)"]


def test_mask_pii():
    text = "연락 주세요 010-1234-5678, mom.kim@example.com"
    assert mask_pii(text) == "연락 주세요 [전화번호], [이메일]"
