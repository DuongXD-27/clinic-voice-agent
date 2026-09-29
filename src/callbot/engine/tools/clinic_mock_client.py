"""HTTP client tới clinic mock (§4.2) — cài đặt `ports.ClinicAPI` bằng httpx, dùng chung cho mọi transport.

Mọi request đi qua `_request`: đo latency, ghi `ApiCallRecord`, đọc envelope lỗi của mock
({"error": {"code", "message", "request_id"}}) và raise `ClinicAPIError`. `httpx` không lộ ra ngoài file này.
"""

import logging
import uuid
from time import perf_counter
from typing import Any, Optional

import httpx

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.ports import PAGE_LIMIT, Page, as_page
from callbot.engine.tools.telemetry import ApiCallRecord, record_api_call

logger = logging.getLogger(__name__)

API_KEY_PREFIX = "sk_"
# Mã theo status khi body không có envelope (ví dụ proxy trả HTML)
_CODE_BY_STATUS = {
    400: "INVALID_REQUEST",
    401: "BAD_KEY",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "INVALID_REQUEST",
    429: "RATE_LIMITED",
    503: "UPSTREAM",
}


class ClinicMockClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 2.0,
        connect_timeout: float = 1.0,
    ) -> None:
        # Mock chỉ nhận key `sk_...`; sai prefix thì mọi request 401 — báo ngay lúc khởi tạo
        if api_key and not api_key.startswith(API_KEY_PREFIX):
            raise ValueError(f"CLINIC_MOCK_API_KEY phải bắt đầu bằng {API_KEY_PREFIX!r}")
        if not api_key:
            logger.warning("Không có CLINIC_MOCK_API_KEY: mọi request tới mock sẽ bị 401")
        base = base_url.rstrip("/")
        if not base.endswith("/v1"):
            logger.warning(
                "CLINIC_MOCK_BASE_URL %r không kết thúc bằng /v1 — mock sẽ trả 404", base
            )
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # read/write theo ngân sách 8 s một lượt (S-03): 2 s để còn chỗ gửi lại một lần sau timeout
        # trong ngân sách ghi của Gateway (T-12 Q-1); mock thật trả trong vài chục ms. connect ngắn
        # để lỗi mạng lộ sớm
        self._client = httpx.Client(
            base_url=base,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClinicMockClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- Đọc -----------------------------------------------------------------

    def find_patient_by_phone(
        self, phone: str, cursor: Optional[str] = None, limit: int = PAGE_LIMIT
    ) -> Page:
        return as_page(
            self._request(
                "find_patient_by_phone",
                "GET",
                "/patients",
                params=_page_params({"phone": phone}, cursor, limit),
            )
        )

    def get_slots(
        self,
        clinic_id: str,
        from_: str,
        to: str,
        cursor: Optional[str] = None,
        limit: int = PAGE_LIMIT,
    ) -> Page:
        return as_page(
            self._request(
                "get_slots",
                "GET",
                "/slots",
                params=_page_params(
                    {"clinic_id": clinic_id, "from": from_, "to": to}, cursor, limit
                ),
            )
        )

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        return self._request("get_appointment", "GET", f"/appointments/{appointment_id}")

    # --- Ghi -----------------------------------------------------------------

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        return self._request(
            "create_appointment",
            "POST",
            "/appointments",
            json={"patient_id": patient_id, "slot_id": slot_id},
            headers=self._write_headers(idempotency_key),
        )

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        return self._request(
            "confirm_appointment",
            "POST",
            f"/appointments/{appointment_id}/confirm",
            headers=self._write_headers(idempotency_key, version),
        )

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        # `confirmed` = người gọi đã xác nhận hủy lần hai (SF-05); Gateway chỉ đặt True khi đủ bằng chứng
        return self._request(
            "cancel_appointment",
            "POST",
            f"/appointments/{appointment_id}/cancel",
            json={"cancel_reason": cancel_reason, "confirmed": confirmed},
            headers=self._write_headers(idempotency_key, version),
        )

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request(
            "transfer_appointment",
            "POST",
            f"/appointments/{appointment_id}/transfer",
            json={"transfer_reason": transfer_reason},
            headers=self._write_headers(idempotency_key, version),
        )

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request(
            "reschedule_appointment",
            "POST",
            f"/appointments/{appointment_id}/reschedule",
            json={"new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            headers=self._write_headers(idempotency_key, version),
        )

    def mark_unreachable(
        self,
        appointment_id: str,
        unreachable_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        # §4.2.5: body chỉ có unreachable_reason; mock tự tăng attempt_count, gửi kèm sẽ bị 400
        return self._request(
            "mark_unreachable",
            "POST",
            f"/appointments/{appointment_id}/unreachable",
            json={"unreachable_reason": unreachable_reason},
            headers=self._write_headers(idempotency_key, version),
        )

    # --- Gửi request ---------------------------------------------------------------

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        started = perf_counter()

        def emit(status: Optional[int], code: Optional[str], request_id: Optional[str], outcome):
            record_api_call(
                ApiCallRecord(
                    operation=operation,
                    method=method,
                    path=path,
                    status=status,
                    code=code,
                    request_id=request_id,
                    latency_ms=int((perf_counter() - started) * 1000),
                    outcome=outcome,
                )
            )

        try:
            response = self._client.request(method, path, params=params, json=json, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Chưa mở được kết nối: request chắc chắn chưa tới mock
            emit(None, "CONNECT_ERROR", None, "rejected")
            raise ClinicAPIError(None, "CONNECT_ERROR", str(exc), outcome_known=True) from exc
        except httpx.TimeoutException as exc:
            emit(None, "TIMEOUT", None, "unknown")
            raise ClinicAPIError(None, "TIMEOUT", str(exc), outcome_known=False) from exc
        except httpx.HTTPError as exc:
            # Đứt kết nối giữa chừng, lỗi giao thức: không biết mock đã áp dụng chưa
            emit(None, "TRANSPORT_ERROR", None, "unknown")
            raise ClinicAPIError(None, "TRANSPORT_ERROR", str(exc), outcome_known=False) from exc

        request_id = response.headers.get("x-request-id")
        if response.is_success:
            try:
                body = _json_body(response)
            except ClinicAPIError as exc:
                # Trace phải khớp cách Gateway hiểu: 2xx không đọc được là chưa rõ, không phải "ok"
                emit(response.status_code, exc.code, request_id, "unknown")
                raise
            emit(response.status_code, None, request_id, "ok")
            return body

        code, message, request_id = _parse_error(response, request_id)
        outcome_known = response.status_code < 500
        emit(response.status_code, code, request_id, "rejected" if outcome_known else "unknown")
        raise ClinicAPIError(response.status_code, code, message, request_id, outcome_known)

    @staticmethod
    def _write_headers(
        idempotency_key: Optional[str], version: Optional[int] = None
    ) -> dict[str, str]:
        # §4.2.3: Idempotency-Key MUST — Gateway luôn truyền; uuid chỉ là lưới an toàn cho gọi trực tiếp
        headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}
        if version is not None:
            headers["If-Match"] = str(version)
        return headers


def _page_params(base: dict[str, Any], cursor: Optional[str], limit: int) -> dict[str, Any]:
    params = dict(base, limit=limit)
    if cursor:
        params["cursor"] = cursor
    return params


def _json_body(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        # 2xx nghĩa là mock (hoặc proxy trước nó) đã nhận request: với lệnh ghi thì chưa rõ kết quả
        raise ClinicAPIError(
            response.status_code, "BAD_RESPONSE", "Body không phải JSON", outcome_known=False
        ) from exc


def _parse_error(
    response: httpx.Response, request_id: Optional[str]
) -> tuple[str, str, Optional[str]]:
    """Envelope của mock: {"error": {"code", "message", "request_id"}}; thiếu thì suy theo status."""
    fallback = _CODE_BY_STATUS.get(response.status_code, "HTTP_ERROR")
    try:
        body = response.json()
    except ValueError:
        return fallback, response.text[:200], request_id
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return fallback, str(body)[:200], request_id
    return (
        str(error.get("code") or fallback),
        str(error.get("message") or ""),
        error.get("request_id") or request_id,
    )
