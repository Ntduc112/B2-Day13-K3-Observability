from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_percentile_uses_nearest_rank() -> None:
    # Nearest-rank: giá trị ở vị trí ceil(p/100 * n), đếm từ 1.
    # Với n=10, P50 là phần tử thứ 5 chứ không phải thứ 6.
    assert percentile(list(range(1, 11)), 50) == 5.0


def test_percentile_p99_is_not_always_the_maximum() -> None:
    # Với n=100, P99 phải là phần tử thứ 99. Nếu nó luôn bằng max thì
    # panel P99 đang đo outlier đơn lẻ chứ không đo tail.
    assert percentile(list(range(1, 101)), 99) == 99.0
