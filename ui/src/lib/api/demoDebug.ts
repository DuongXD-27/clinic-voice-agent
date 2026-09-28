/**
 * Header chẩn đoán `X-Demo-*` mà `POST /v1/calls/{id}/turn` trả khi request có `X-Demo-Debug: 1`
 * (xem `_debug_headers` trong calls.py). Không nằm trong OpenAPI nên type viết tay ở đây.
 * Header có cả trên response lỗi, nên đọc từ `Headers` của cả hai trường hợp.
 */

export interface ExtractedField {
  field: string;
  value: unknown;
  span: string | null;
  provenance: string | null;
}

export interface ExtractionFields {
  transcript: string;
  silent: boolean;
  fields: ExtractedField[];
}

export interface DemoDebug {
  extraction: { source: string; provenance: string; questionId: string | null } | null;
  /** Câu người gọi và các trường đã trích; null khi lượt không qua bước trích xuất. */
  fields: ExtractionFields | null;
  /** Lý do chuyển máy đã yêu cầu — không phải bằng chứng Clinic đã ghi. */
  transferReason: string | null;
  errorType: string | null;
  errorCode: string | null;
}

export const DEMO_DEBUG_HEADER = { "X-Demo-Debug": "1" } as const;

export function readDemoDebug(headers: Headers | null): DemoDebug {
  const get = (name: string) => headers?.get(name) ?? null;
  const source = get("X-Demo-Extraction-Source");
  return {
    extraction: source
      ? {
          source,
          provenance: get("X-Demo-Extraction-Provenance") ?? "NONE",
          questionId: get("X-Demo-Extraction-Question-Id"),
        }
      : null,
    fields: parseFields(get("X-Demo-Extraction-Fields")),
    transferReason: get("X-Demo-Transfer-Reason"),
    errorType: get("X-Demo-Error-Type"),
    errorCode: get("X-Demo-Error-Code"),
  };
}

/** Giá trị là JSON percent-encoded (header chỉ chứa latin-1). Sai dạng thì bỏ qua. */
export function parseFields(raw: string | null): ExtractionFields | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(decodeURIComponent(raw));
  } catch {
    return null;
  }
  if (!isRecord(data) || !Array.isArray(data.fields)) return null;
  const fields = data.fields.filter(isRecord).flatMap((item): ExtractedField[] =>
    typeof item.field === "string"
      ? [
          {
            field: item.field,
            value: item.value,
            span: typeof item.span === "string" ? item.span : null,
            provenance: typeof item.provenance === "string" ? item.provenance : null,
          },
        ]
      : [],
  );
  return {
    transcript: typeof data.transcript === "string" ? data.transcript : "",
    silent: data.silent === true,
    fields,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
