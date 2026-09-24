# FarmingProject — Claude 수익화 실험실

Claude(AI)를 활용해 **실제로 수익을 만드는 방법**을 탐색하고, 실험하고, 기록하는 프로젝트입니다.
육아휴직 기간 동안 진행하며, 모든 과정은 블로그·유튜브·책 콘텐츠로 재사용할 수 있게 남깁니다.

> "Farming" — 작은 씨앗(아이디어)을 심고, 가꾸고(실험), 수확(수익/콘텐츠)한다.

## 목표

1. Claude로 만들 수 있는 수익화 아이디어를 폭넓게 모으고 평가한다.
2. 가능성이 보이는 아이디어는 작게, 빠르게 실험한다 (주로 Python).
3. 과정과 결과(실패 포함)를 기록해 콘텐츠로 만든다.

## 폴더 구조

```
.
├── ideas/          # 수익화 아이디어 백로그 (아이디어 1개 = 파일 1개)
├── experiments/    # 실험별 폴더 (코드 + 결과 + 회고)
├── journal/        # 날짜별 진행 일지 → 콘텐츠 원재료
├── content/        # 발행용 콘텐츠 초안
│   ├── blog/
│   ├── youtube/
│   └── book/
├── templates/      # 아이디어/실험/일지/콘텐츠 템플릿
└── scripts/        # 보조 스크립트 (새 문서 생성 등)
```

## 작업 흐름

```
아이디어(ideas/) ──선정──▶ 실험(experiments/) ──결과──▶ 콘텐츠(content/)
        ▲                          │
        └──────── 일지(journal/) ◀─┘  매일/매 작업마다 기록
```

## 빠른 시작

템플릿으로 새 문서를 만듭니다 (Python 3.10+, 외부 패키지 불필요).

```bash
python scripts/new.py journal                     # 오늘 날짜 일지
python scripts/new.py idea "뉴스레터 자동 요약"      # 아이디어
python scripts/new.py experiment "newsletter-mvp"  # 실험 폴더
python scripts/new.py blog "클로드로 첫 수익 내기"    # 블로그 초안
python scripts/new.py youtube "수익화 실험 1편"      # 유튜브 스크립트
```

## 진행 현황

| 상태 | 아이디어 | 실험 | 수익 | 콘텐츠 |
|------|----------|------|------|--------|
| 첫 실험 설계 | 10 | 1 (설계) | ₩0 | 0 |

아이디어 목록은 [ideas/README.md](ideas/README.md)에서 관리합니다.
