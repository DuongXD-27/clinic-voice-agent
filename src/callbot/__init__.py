"""Clinicalbot — một core, hai transport (hợp đồng §1.3.2).

- engine/     — Session, Information Extraction, Policy, Verifier, Dialogue, tools (clinic mock)
- speech/     — STT/TTS, audio 8 kHz
- tracing/    — trace JSONL mỗi lượt
- transports/ — HTTP cho harness; phone leg tuần 6. Chỉ đổi request/response, không chứa logic hội thoại.
"""
