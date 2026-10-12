import { describe, expect, it } from "vitest";

import { parseFields, readDemoDebug } from "./demoDebug";

/** Giống `_extraction_fields` của backend: quote(json.dumps(..., ensure_ascii=False), safe=""). */
function encodeFields(payload: unknown): string {
  return encodeURIComponent(JSON.stringify(payload));
}

describe("readDemoDebug", () => {
  it("đọc đủ header chẩn đoán", () => {
    const headers = new Headers({
      "X-Demo-Extraction-Source": "RULE",
      "X-Demo-Extraction-Provenance": "EXACT",
      "X-Demo-Extraction-Question-Id": "ASK_DOB",
      "X-Demo-Transfer-Reason": "IDENTITY_FAILED",
      "X-Demo-Error-Type": "CLINIC",
      "X-Demo-Error-Code": "SLOT_TAKEN",
      "X-Demo-Extraction-Fields": encodeFields({
        transcript: "Tôi là Nguyễn Văn A",
        silent: false,
        fields: [
          { field: "full_name", value: "Nguyễn Văn A", span: "Nguyễn Văn A", provenance: "EXACT" },
        ],
      }),
    });

    expect(readDemoDebug(headers)).toEqual({
      extraction: { source: "RULE", provenance: "EXACT", questionId: "ASK_DOB" },
      fields: {
        transcript: "Tôi là Nguyễn Văn A",
        silent: false,
        fields: [
          { field: "full_name", value: "Nguyễn Văn A", span: "Nguyễn Văn A", provenance: "EXACT" },
        ],
        model: null,
      },
      transferReason: "IDENTITY_FAILED",
      errorType: "CLINIC",
      errorCode: "SLOT_TAKEN",
    });
  });

  it("trả toàn null khi không có header (không bật debug hoặc lỗi mạng)", () => {
    expect(readDemoDebug(null)).toEqual({
      extraction: null,
      fields: null,
      transferReason: null,
      errorType: null,
      errorCode: null,
    });
  });

  it("provenance mặc định NONE khi chỉ có source", () => {
    const debug = readDemoDebug(new Headers({ "X-Demo-Extraction-Source": "NONE" }));

    expect(debug.extraction).toEqual({ source: "NONE", provenance: "NONE", questionId: null });
  });
});

describe("parseFields", () => {
  it.each([
    ["chuỗi không phải percent-encoding hợp lệ", "%E0%A4%A"],
    ["không phải JSON", encodeURIComponent("không phải json")],
    ["thiếu mảng fields", encodeFields({ transcript: "x" })],
  ])("bỏ qua %s", (_name, raw) => {
    expect(parseFields(raw)).toBeNull();
  });

  it("bỏ phần tử sai dạng, giữ phần tử đúng", () => {
    const parsed = parseFields(
      encodeFields({
        transcript: "có",
        silent: false,
        fields: [
          { value: 1 },
          "rác",
          { field: "agreement", value: "AGREE", span: 3, provenance: "EXACT" },
        ],
      }),
    );

    expect(parsed?.fields).toEqual([
      { field: "agreement", value: "AGREE", span: null, provenance: "EXACT" },
    ]);
  });

  it("đọc model đã đọc lượt, kể cả provider dự phòng", () => {
    const parsed = parseFields(
      encodeFields({
        transcript: "thôi hủy giúp tôi",
        silent: false,
        fields: [],
        model: { provider: "openai", name: "gpt-6-luna", status: "OK", backup_for: "typesafe" },
      }),
    );

    expect(parsed?.model).toEqual({
      provider: "openai",
      name: "gpt-6-luna",
      status: "OK",
      backupFor: "typesafe",
    });
  });

  it.each([
    ["không có model (chỉ luật)", null],
    ["thiếu tên model", { provider: "typesafe", status: "OK" }],
  ])("model null khi %s", (_name, model) => {
    expect(parseFields(encodeFields({ transcript: "x", fields: [], model }))?.model).toBeNull();
  });
});
