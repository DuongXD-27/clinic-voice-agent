import { expect, test, type Page } from "@playwright/test";

/**
 * Hai kịch bản không phụ thuộc ngày chạy và không giẫm dữ liệu của nhau:
 * - outbound xác nhận: đi hết xác minh danh tính, đọc lịch, ghi CONFIRMED vào clinic;
 * - inbound im lặng 3 lượt: chuyển máy, theo contract không ghi gì vào clinic.
 * (Đặt lịch phụ thuộc khung giờ trong 14 ngày tới nên không dùng cho E2E.)
 */

const API_KEY = process.env.E2E_API_KEY ?? "";

/** Mở /call khi chưa đăng nhập: về trang đăng nhập, nhập key rồi quay lại đúng /call. */
async function openCallPage(page: Page) {
  await page.goto("/call");
  await expect(page).toHaveURL(/\/login\?next=%2Fcall$/);
  // exact: getByLabel của Playwright khớp chuỗi con, sẽ trúng cả nút "Hiện API key".
  await page.getByLabel("API key", { exact: true }).fill(API_KEY);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Cuộc gọi từng lượt (Text/Audio)" }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/call$/);
}

async function startCall(page: Page) {
  await page.getByRole("button", { name: "Bắt đầu cuộc gọi" }).click();
  await expect(page.getByText("Cuộc gọi đã mở.")).toBeVisible();
}

/** Khung hội thoại (câu bot còn xuất hiện ở panel debug nên luôn tìm trong khung này). */
function chat(page: Page) {
  return page.getByLabel("Hội thoại");
}

/** Câu chào (cả hai chiều gọi) phải hỏi họ tên để xác minh. */
async function expectIdentityGreeting(page: Page) {
  await expect(
    chat(page)
      .getByText(/họ (?:và )?tên/)
      .first(),
  ).toBeVisible();
}

/** Giá trị một ô trong thanh trạng thái (dt = nhãn, dd ngay sau = giá trị). */
function metric(page: Page, label: string) {
  return page.locator("dt", { hasText: label }).locator("xpath=following-sibling::dd[1]");
}

test("outbound: xác minh danh tính rồi xác nhận lịch → CONFIRMED", async ({ page }) => {
  await openCallPage(page);
  const appointment = page.getByLabel("Appointment ID");
  await expect(appointment).toHaveValue("apt_00417");
  await expect(
    appointment.locator("option:checked"),
    "apt_00417 phải đang SCHEDULED — restart bot (sim) hoặc Reset clinic (mock) rồi chạy lại",
  ).toContainText("SCHEDULED");

  await startCall(page);
  await expectIdentityGreeting(page);

  const input = page.getByLabel("Lời người gọi");
  await input.fill("Tôi là Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978");
  await input.press("Enter");
  await expect(chat(page).getByText(/đến khám được không/)).toBeVisible();
  // Bảng trích xuất của lượt 1 có họ tên và ngày sinh.
  await expect(page.getByRole("cell", { name: "Họ tên" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ngày sinh" })).toBeVisible();

  await input.fill("Có, tôi đến được");
  await input.press("Enter");
  await expect(page.getByText("Cuộc gọi đã kết thúc: CONFIRMED.")).toBeVisible();
  await expect(metric(page, "Outcome")).toHaveText("CONFIRMED");
  await expect(input).toBeDisabled();
});

test("inbound: im lặng 3 lượt → TRANSFERRED", async ({ page }) => {
  await openCallPage(page);
  await page.getByRole("radio", { name: "Inbound · khách gọi" }).check({ force: true });
  await page.getByLabel("Số người gọi").selectOption("0912345600");

  await startCall(page);
  await expectIdentityGreeting(page);

  const silence = page.getByRole("button", { name: "Im lặng 2 giây" });
  for (let turn = 1; turn <= 3; turn += 1) {
    await silence.click();
    await expect(chat(page).getByText("(im lặng 2 giây)")).toHaveCount(turn);
  }

  await expect(page.getByText("Cuộc gọi đã kết thúc: TRANSFERRED.")).toBeVisible();
  await expect(metric(page, "Outcome")).toHaveText("TRANSFERRED");
});
