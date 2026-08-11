# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: Nhóm 5 (K3 Observability Team)
- Repository URL: https://github.com/Ntduc112/B2-Day13-K3-Observability
- Commit SHA cuối: `412502aa0c0a62b9a05179174b9fb49065c26acf`
- Thành viên và vai trò:
  - Thành viên A (API & Middleware): CP1 Middleware, gán Correlation ID, bổ sung Exception Handler mở rộng.
  - Thành viên B (Security Engineer): CP1 PII Scrubbing, xây dựng regex patterns và kiểm chứng log bảo mật.
  - Thành viên C (Metrics & Dashboard): CP1/CP2 đo đếm `error_rate_pct`, nearest-rank percentile, thiết kế spec Dashboard 6 nhóm chỉ số.
  - Thành viên D (SRE & Alerts Engineer): CP2 Thiết lập SLO, viết Alert rules và Alert Runbook xử lý sự cố.
  - Thành viên E (QA & Chief Investigator): Chạy load test, bọc trace sub-component RAG/LLM, dẫn dắt điều tra Challenge CP3 và hoàn thiện báo cáo nhóm.

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: **100/100** (`+ [PASSED] Basic JSON schema`, `+ [PASSED] Correlation ID propagation`, `+ [PASSED] Log enrichment`, `+ [PASSED] PII scrubbing`).
- Tổng số traces: **20+ traces** với đầy đủ metadata enrichment (`user_id_hash`, `session_id`, `feature`, `model`, `env`, `prompt_name`, `prompt_label`, `prompt_version`).
- Số PII leak còn lại: **0** (Kiểm chứng khử thành công cả 6 dạng PII: Email, Credit Card, CCCD, Số điện thoại Việt Nam, Hộ chiếu, Địa chỉ).
- Link/đường dẫn dashboard: [evidence/dashboard-challenge.html](evidence/dashboard-challenge.html)

## 3. Logging và tracing

- Evidence correlation ID: Header `x-request-id` và trường `correlation_id` (dạng `req-xxxxxxxx`) gắn xuyên suốt từ `CorrelationIdMiddleware` -> `structlog` contextvars -> `request.state` -> HTTP Response Headers & Log file JSONL.
- Evidence PII redaction: Các thông tin nhạy cảm trong input/output đều qua `scrub_value()` và tự động thay thế bằng tag `[REDACTED_<TYPE>]` (ví dụ: `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]`).
- Evidence trace waterfall: Cấu trúc phân nhánh 3 tầng do Thành viên E thực hiện gồm Parent Trace `run` (`LabAgent.run`), Child Span `rag_retrieve` (`retrieve` trong `app/mock_rag.py`), và Child Generation `llm_generate` (`generate` trong `app/mock_llm.py`).
- Giải thích một span đáng chú ý: In span `rag_retrieve`, khi bị tác động bởi incident `rag_slow`, hàm `retrieve()` bị delay 2.5s (`time.sleep(2.5)`), chiếm 94% tổng thời gian phản hồi của request `LabAgent.run` (~2.65s).

## 4. Prompt versioning

- Prompt name: `day13-chat`
- Version/label baseline: `v1` (`label: production`, `version: local-v1` / Langfuse prompt v1)
- Version/label candidate: `v2` (`label: staging` / `candidate`)
- Trace ID của mỗi version:
  - Baseline v1 Trace ID: `trace-prompt-v1-prod-001`
  - Candidate v2 Trace ID: `trace-prompt-v2-cand-002`
- Bằng chứng đổi label hoặc rollback: Thay đổi cấu hình môi trường `LANGFUSE_PROMPT_LABEL=production` (hoặc `staging`), `resolve_prompt()` tự động fetch phiên bản tương ứng từ Langfuse Prompt Management API kèm cơ chế fallback local an toàn khi ngắt kết nối.

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: **HỢP LỆ: 6/6 panel có trong dashboard contract.**
- Evidence dashboard: [evidence/dashboard-challenge.html](evidence/dashboard-challenge.html)
- SLO đã chọn và lý do:
  - `latency_p95_ms` (Objective ≤ 3000ms, Target 99.5%): Giữ độ trễ phản hồi của AI Agent trong ngưỡng trải nghiệm người dùng tối ưu.
  - `error_rate_pct` (Objective ≤ 2.0%, Target 99.0%): Đảm bảo tính khả dụng và độ tin cậy của API.
  - `daily_cost_usd` (Objective ≤ $2.50, Target 100%): Kiểm soát ngân sách tiêu thụ API của LLM models.
  - `quality_score_avg` (Objective ≥ 0.75, Target 95.0%): Đảm bảo chất lượng câu trả lời từ RAG & LLM.
- Alert rules và runbook: Cấu hình 3 quy tắc cảnh báo tại [config/alert_rules.yaml](../config/alert_rules.yaml) và viết Incident Runbook hướng dẫn xử lý sự cố chi tiết tại [docs/alerts.md](../docs/alerts.md).

## 6. Điều tra challenge

- Challenge ID: `day13-k3-observability-v1`
- Triệu chứng từ metrics: Panel **Latency percentiles** đo được P95 tăng từ ~1.2s lên ~2.65s. Đặc biệt panel nâng cao **Latency P95 by feature** cho thấy sự gia tăng độ trễ chỉ xuất hiện duy nhất ở feature `refund` (~2.65s), trong khi `monitoring` và `policy` giữ nguyên ở mức ~1.1s.
- Trace ID liên quan: `trace-challenge-refund-s01`
- Log line/correlation ID liên quan: `correlation_id`: `req-f2b8e476`, event: `response_sent`, `feature`: `refund`, `latency_ms`: 2650.
- Root cause: Sự cố `rag_slow` được bật trong `app/mock_rag.py` gây ra độ trễ nhân tạo 2.5s khi thực hiện truy xuất tài liệu vector corpus đối với các câu hỏi liên quan tới feature `refund`.
- Fix action: Cài đặt caching kết quả vector retrieval đối với các truy vấn domain `refund`, thiết lập timeout 500ms cho RAG service kèm fallback câu trả lời mặc định.
- Preventive measure: Bổ sung Alert rule giám sát P95 Latency theo từng Feature (Feature-level Latency Alert) và áp dụng Circuit Breaker cho RAG retrieval component.

## 7. Đóng góp cá nhân

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Thành viên A | Xây dựng Correlation ID Middleware & Unhandled Exception Handler | `412502a` | Quản lý context variables trong FastAPI/structlog và duy trì trace context. |
| Thành viên B | Triển khai PII Scrubbing đệ quy & Regex 6 dạng thông tin nhạy cảm | `412502a` | Nắm vững kỹ thuật khử PII đệ quy trên dữ liệu cấu trúc. |
| Thành viên C | Cài đặt `error_rate_pct`, nearest-rank percentile & HTML/SVG Dashboard Spec | `412502a` | Thiết kế Dashboard Observability và tính mẫu số error rate chuẩn. |
| Thành viên D | Định nghĩa SLO/SLI, Alert rules & Viết Incident Runbook | `412502a` | Xây dựng quy tắc cảnh báo SRE dựa trên triệu chứng tác động tới người dùng và viết Runbook. |
| Thành viên E | Script Load test, bọc Sub-span RAG/LLM, Điều tra Challenge & Viết Báo cáo nhóm | `412502a` | Thành thạo quy trình điều tra sự cố theo luồng Metrics → Traces → Logs và bọc trace sub-span. |
