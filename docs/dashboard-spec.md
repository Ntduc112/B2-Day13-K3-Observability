# Thiết kế dashboard và metrics — Role C

Contract có thể kiểm tra bằng máy nằm tại [`config/dashboard.yaml`](../config/dashboard.yaml). Hướng dẫn dựng và kiểm tra runtime nằm tại [DASHBOARD_SETUP.md](DASHBOARD_SETUP.md). File này ghi lại thiết kế của nhóm: chọn công cụ gì, tính chỉ số ra sao, và những giới hạn cần biết khi đọc số.

## 1. Yêu cầu

Dashboard chính cần đủ 6 nhóm thông tin:

1. Latency P50/P95/P99.
2. Traffic: request count hoặc QPS.
3. Error rate và breakdown theo loại lỗi.
4. Cost theo thời gian.
5. Tổng token input/output.
6. Quality proxy.

Tiêu chuẩn trình bày: khoảng thời gian mặc định 1 giờ, tự refresh 15–30 giây, có threshold hoặc SLO line, ghi rõ đơn vị, chỉ giữ 6–8 panel ở lớp chính, screenshot phải nhìn được tên panel và khoảng thời gian.

## 2. Công cụ: HTML tĩnh sinh bằng stdlib

`scripts/build_dashboard.py` đọc `data/logs.jsonl` cùng `config/dashboard.yaml` và sinh ra một file HTML self-contained với biểu đồ SVG inline.

Lý do chọn thay vì Streamlit/Grafana: `requirements.txt` đang pin và không có thư viện vẽ biểu đồ nào; cách này không thêm dependency, chạy một lệnh là ra, và người chấm mở bằng browser mà không phải cài gì. Đổi lại là phải tự vẽ SVG, nên số lượng biểu đồ được giữ ở mức tối thiểu (xem mục 5).

```
config/dashboard.yaml ──┐
                        ├─► scripts/build_dashboard.py ──► build/dashboard.html
data/logs.jsonl ────────┘              │
                                       └─ dùng lại app.metrics.percentile
```

Tách ba tầng để test được độc lập:

| Hàm | Việc | Phụ thuộc |
|---|---|---|
| `load_records(path, now, window_minutes)` | đọc JSONL, bỏ dòng hỏng, lọc theo `ts` | filesystem |
| `compute_panels(records, config)` | trả về giá trị từng panel kèm trạng thái threshold | không I/O |
| `render_html(panels, meta)` | sinh HTML + SVG | không I/O |

`now` được truyền vào chứ không gọi trong hàm, để test cửa sổ thời gian không phụ thuộc đồng hồ thật.

## 3. Mapping dữ liệu

| Panel | Event/field | Phép tổng hợp | Đơn vị | Threshold |
|---|---|---|---|---|
| latency | `response_sent.latency_ms` | p50, p95, p99 | ms | p95 ≤ 3000 |
| traffic | `request_received` | count, request/phút | requests_per_minute | ≥ 1 |
| errors | `request_received`, `request_failed`, `error_type` | error_rate_pct, count_by_value | percent | ≤ 2 |
| cost | `response_sent.cost_usd` | sum theo phút, tổng | usd | tổng ≤ 2.5 |
| tokens | `response_sent.tokens_in/tokens_out` | sum theo từng field | tokens | ≤ 50000 |
| quality | `response_sent.quality_score` | mean | score_0_to_1 | ≥ 0.75 |
| **by_feature** | `response_sent.latency_ms` nhóm theo `feature` | p95 mỗi feature | ms | dùng lại ngưỡng của panel latency |

Threshold được đọc từ `config/dashboard.yaml` chứ không hard-code, nên role D chỉnh ngưỡng thì dashboard đổi theo mà không phải sửa code.

## 4. Panel thứ 7 — Latency P95 by feature

Contract quy định đúng 6 panel và `scripts/validate_dashboard.py` sẽ báo lỗi nếu YAML có số panel khác 6, nên panel này **không** được thêm vào `config/dashboard.yaml`; nó chỉ tồn tại trong HTML và được tính trực tiếp từ log.

Lý do cần: incident của challenge chỉ đánh vào một feature. Không có panel này thì phải grep log tay mới khoanh được vùng; có nó thì triệu chứng lộ ra ngay ở lớp Metrics, đúng luồng Metrics → Traces → Logs. Ngưỡng dùng chung với panel latency vì cùng đại lượng.

## 5. Hình thức hiển thị

Chỉ hai panel cần chuỗi thời gian là `traffic` (count theo phút) và `cost` (sum theo phút); cả hai dùng chung một helper `sparkline()`. Bốn panel còn lại cộng panel thứ 7 hiển thị dạng số lớn kèm đường ngưỡng và badge OK/BREACH.

Header của trang in rõ: time range, thời điểm sinh file, tổng số record trong cửa sổ — để ảnh chụp evidence tự chứng minh được nó đọc dữ liệu nào.

`--watch` bật `<meta http-equiv="refresh" content="30">` và sinh lại file mỗi 30 giây, khớp `refresh_seconds` của contract. File được ghi ra file tạm rồi `os.replace()` để browser không đọc trúng file đang viết dở.

## 6. `error_rate_pct` trong `app/metrics.py`

```
errors_total   = sum(ERRORS.values())
attempts       = TRAFFIC + errors_total
error_rate_pct = 0.0 nếu attempts == 0, ngược lại round(errors_total / attempts * 100, 2)
```

Mẫu số là **số lần thử**, không phải `TRAFFIC`. `TRAFFIC` chỉ tăng ở cuối `LabAgent.run()` khi request thành công, nên nếu lấy `errors / TRAFFIC` thì kịch bản `tool_fail` (hỏng 100%) sẽ chia cho 0. `TRAFFIC + errors_total` khớp đúng ngữ nghĩa mẫu số của contract, vì `request_received` được ghi log cho mọi lần thử kể cả lần sau đó fail.

## 7. Định nghĩa percentile

`app/metrics.py` dùng **nearest-rank**: percentile thứ p là phần tử ở vị trí `ceil(p/100 × n)` trong dãy đã sắp xếp (1-indexed), trả về `0.0` khi dãy rỗng.

Bản starter dùng `round(p/100 × n + 0.5) - 1`, tức nearest-rank cộng thêm nửa bậc, nên lệch cao một bậc ở nhiều kích thước mẫu — với n=100 thì P99 luôn bằng đúng giá trị lớn nhất, nghĩa là panel P99 đo outlier đơn lẻ chứ không đo tail. Hàm đã được sửa về nearest-rank chuẩn kèm test ghi rõ định nghĩa.

## 8. Hai giới hạn cần biết khi đọc số

**`/metrics` và dashboard không cùng cửa sổ đo.** `snapshot()` cộng dồn toàn bộ vòng đời tiến trình và reset về 0 mỗi lần restart uvicorn; dashboard đọc 60 phút gần nhất từ `logs.jsonl`, file này sống sót qua restart. Hai con số lệch nhau là đúng, không phải bug — lệch rõ nhất ngay sau khi restart để bật incident.

**Global exception handler đếm rộng hơn `/chat`.** Handler trong `app/main.py` ghi `request_failed` và gọi `record_error()` cho mọi route, trong khi `request_received` chỉ được ghi trong `/chat`. Nếu có lỗi ở route khác thì `count(request_failed) / count(request_received)` về lý thuyết vượt 100%. Trong phạm vi lab không xảy ra vì tải chỉ đi qua `/chat`.

## 9. Cách chạy và kiểm tra

```bash
python scripts/validate_dashboard.py      # kiểm tra contract, phải báo 6/6 panel
python scripts/load_test.py --concurrency 5
python scripts/build_dashboard.py         # sinh build/dashboard.html
python scripts/build_dashboard.py --watch # thêm auto-refresh 30s khi demo
```

Kiểm tra runtime theo [DASHBOARD_SETUP.md](DASHBOARD_SETUP.md): chụp baseline, bật `python scripts/inject_incident.py --scenario rag_slow`, chạy lại cùng input, xác nhận panel latency và panel thứ 7 đổi theo đúng hướng, rồi tắt incident.

`build/` nằm trong `.gitignore`; khi chốt bằng chứng thì copy sang `submission/evidence/` để commit.
