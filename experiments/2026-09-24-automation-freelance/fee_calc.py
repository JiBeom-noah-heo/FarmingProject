"""크몽 판매가 → 실수령액 계산기.

크몽 공식 수수료 정책 기준 (2026-09-25, 공식 계산 예시로 검증 — test_fee_calc.py):
- 서비스 이용료: 구간별 누진 — 70만원까지 16.4%, 70만~200만원 9.4%, 200만원 초과분 4.4%
- 결제망 이용료: 판매가의 3.3%
- 부가세: (서비스 이용료 + 결제망 이용료)의 10%

사용법:
    python fee_calc.py 50000 150000 300000
"""

import sys

BRACKETS = [(700_000, 0.164), (2_000_000, 0.094), (float("inf"), 0.044)]
PAYMENT_RATE = 0.033
VAT_RATE = 0.10


def service_fee(price: int) -> float:
    fee, lower = 0.0, 0
    for upper, rate in BRACKETS:
        if price <= lower:
            break
        fee += (min(price, upper) - lower) * rate
        lower = upper
    return fee


def net_payout(price: int) -> dict:
    service = service_fee(price)
    payment = price * PAYMENT_RATE
    vat = (service + payment) * VAT_RATE
    total_fee = service + payment + vat
    return {
        "판매가": price,
        "수수료 합계": round(total_fee),
        "실수령액": round(price - total_fee),
        "실수령 비율": f"{(price - total_fee) / price:.1%}",
    }


def main() -> None:
    prices = [int(p) for p in sys.argv[1:]] or [50_000, 150_000, 300_000, 1_000_000]
    for price in prices:
        r = net_payout(price)
        print(f"{r['판매가']:>10,}원 → 수수료 {r['수수료 합계']:>9,}원 / "
              f"실수령 {r['실수령액']:>10,}원 ({r['실수령 비율']})")


if __name__ == "__main__":
    main()
