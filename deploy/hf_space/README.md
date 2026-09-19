---
title: Callbot Voice Demo
emoji: 📞
colorFrom: red
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# Callbot Voice Demo

Demo public: mic trình duyệt mở liên tục (WebRTC, VAD tự cắt câu) → ZipFormer STT
(chạy ngay trong container) → Core Agent thật qua HTTP → OpenAI TTS → phát tự động
trong trình duyệt. Deploy bằng Docker image này lên Google Cloud Run (`gcloud run
deploy --source .`), không phải Hugging Face Spaces (frontmatter `sdk: docker` chỉ
còn giữ cho tương thích, không dùng tới).

## Biến môi trường / Secrets cần cấu hình

- `OPENAI_API_KEY` — bắt buộc, dùng cho TTS.
- `ACCESS_PASSWORD` — tuỳ chọn, để trống thì ai có link cũng dùng được; điền vào để
  giới hạn chỉ người có mật khẩu mới vào được app.
- `CORE_BASE_URL` — tuỳ chọn, mặc định `https://vmec-callbot.tech`.
- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — **bắt buộc để mic hoạt động qua
  Cloud Run** (WebRTC cần TURN server khi chạy sau proxy/load balancer; thiếu 2
  biến này sẽ fallback về STUN-only của Google, thường KHÔNG kết nối được qua
  NAT thật). Lấy từ console.twilio.com (free trial đủ dùng, dùng
  `client.tokens.create()` để cấp ICE server ngắn hạn).
