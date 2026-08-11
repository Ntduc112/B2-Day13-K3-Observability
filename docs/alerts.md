# Alert Rules và Incident Runbook

Tất cả các cảnh báo được thiết lập dựa trên triệu chứng tác động tới người dùng và mục tiêu SLO dịch vụ, tuân thủ nguyên tắc SRE.

---

## Alert 1

- Tên: HighLatencyP95
- Severity: Critical
- SLI/SLO liên quan: `latency_p95_ms` (Mục tiêu: P95 latency ≤ 3000ms cho 99.5% request trong cửa sổ 28 ngày)
- Điều kiện và thời gian duy trì: `p95_latency > 3000ms` duy trì liên tục trong 5 phút
- Ảnh hưởng tới người dùng: Người dùng phản hồi hệ thống phản hồi cực kỳ chậm, trải nghiệm chat bị ngắt quãng hoặc gây ra client-side timeout.
- Ba bước kiểm tra đầu tiên:
  1. Mở Dashboard theo dõi panel **Latency P95 by feature** để xác định sự cố xảy ra trên toàn hệ thống hay chỉ tập trung vào 1 feature cụ thể (ví dụ: `refund` hay `monitoring`).
  2. Mở Tracing (Langfuse) và sắp xếp trace theo thời gian phản hồi giảm dần. Kiểm tra cây waterfall span để xác định xem độ trễ bị delay ở bước nào (`rag_retrieve` hay `llm_generate`).
  3. Kiểm tra log file `data/logs.jsonl` lọc theo `event == "request_received"` và `event == "response_sent"` tương ứng với correlation ID của request bị chậm để tìm nguyên nhân mạng/I/O.
- Mitigation tạm thời:
  - Nếu độ trễ đến từ RAG vector retrieval: Bật cache fallback cho kết quả truy xuất domain corpus hoặc giảm RAG timeout xuống 500ms.
  - Nếu do LLM backend: Chuyển hướng traffic sang model backup có latency thấp hơn.
- Owner: SRE & Alerts Engineer (Role D)

---

## Alert 2

- Tên: HighErrorRate
- Severity: Critical
- SLI/SLO liên quan: `error_rate_pct` (Mục tiêu: HTTP Error Rate < 2.0% cho 99.0% cửa sổ request)
- Điều kiện và thời gian duy trì: `error_rate_pct > 2.0%` duy trì trong 3 phút
- Ảnh hưởng tới người dùng: Người dùng nhận được phản hồi lỗi 500 (Internal Server Error), ứng dụng mất khả năng phục vụ truy vấn.
- Ba bước kiểm tra đầu tiên:
  1. Mở Dashboard kiểm tra panel **Error rate and breakdown** để xem tỷ lệ lỗi hiện tại và phân loại lỗi (`error_breakdown`, ví dụ: `RuntimeError`, `HTTPException`, `ConnectionError`).
  2. Tra cứu log trong `data/logs.jsonl` tìm các log record chứa `event == "request_failed"` hoặc `level == "error"`. Lấy `correlation_id` của request lỗi.
  3. Dùng `correlation_id` tra cứu Trace tương ứng trên Langfuse để xem chi tiết exception stack trace và thông số input payload bị lỗi.
- Mitigation tạm thời:
  - Nếu nguyên nhân do Tool/Vector store fail (`tool_fail` / `Vector store timeout`): Kích hoạt fallback static answer cho RAG thay vì ném ra lỗi 500.
  - Xử lý ném ngoại lệ trong Exception Handler của FastAPI để trả về response 200 kèm degraded message thay vì vỡ UI.
- Owner: SRE & Alerts Engineer (Role D)

---

## Alert 3

- Tên: CostLimitExceeded
- Severity: Warning
- SLI/SLO liên quan: `daily_cost_usd` (Mục tiêu: Chi phí API tổng không quá $2.50/ngày)
- Điều kiện và thời gian duy trì: `total_cost_usd > 2.5` lũy kế trong 1 giờ
- Ảnh hưởng tới người dùng: Không ảnh hưởng trực tiếp tới UX, nhưng làm bùng nổ chi phí vận hành API (Cost Spike) gây vượt ngân sách dự án.
- Ba bước kiểm tra đầu tiên:
  1. Mở Dashboard xem panel **Cost over time** và **Input and output tokens** để xác định xu hướng chi phí tăng vọt.
  2. Tra cứu log `event == "response_sent"` sắp xếp theo `tokens_out` và `cost_usd` giảm dần để phát hiện các request tiêu tốn số lượng token bất thường (`cost_spike`).
  3. Kiểm tra thông số `prompt_version` và `prompt_label` trong trace metadata xem có mới thực hiện đổi prompt làm tăng số lượng token đầu ra hay không.
- Mitigation tạm thời:
  - Giới hạn `max_tokens` đầu ra của LLM generation xuống mức an toàn (ví dụ: max 200 tokens).
  - Thực hiện rollback `prompt_label` về phiên bản baseline ổn định và ít tốn kém hơn.
- Owner: SRE & Alerts Engineer (Role D)
