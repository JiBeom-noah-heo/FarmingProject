from fee_calc import net_payout, service_fee


def test_official_kmong_example():
    # 크몽 공식 예시: 3,500,000원 판매 시 실수령 3,039,650원
    assert round(service_fee(3_500_000)) == 303_000
    assert net_payout(3_500_000)["실수령액"] == 3_039_650
