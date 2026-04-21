import { test, expect } from "@playwright/test";

const STORAGE_KEY = "userCustomers:guest";

// 테스트 전 localStorage를 초기화하는 헬퍼
async function clearOwnedCustomers(page: import("@playwright/test").Page) {
  await page.evaluate((key) => localStorage.removeItem(key), STORAGE_KEY);
}

async function setOwnedCustomers(
  page: import("@playwright/test").Page,
  ids: string[],
) {
  await page.evaluate(
    ([key, value]) => localStorage.setItem(key, JSON.stringify(value)),
    [STORAGE_KEY, ids] as [string, string[]],
  );
}

test.describe("내 담당 고객사 필터", () => {
  test.describe("담당 고객사 미설정 상태", () => {
    test("대시보드에서 OwnedEmptyState가 표시된다", async ({ page }) => {
      await page.goto("/dashboard");
      await clearOwnedCustomers(page);
      await page.reload();

      await expect(
        page.getByTestId("owned-empty-state"),
      ).toBeVisible();
    });

    test("리소스 페이지에서 OwnedEmptyState가 표시된다", async ({ page }) => {
      await page.goto("/resources");
      await clearOwnedCustomers(page);
      await page.reload();

      await expect(
        page.getByTestId("owned-empty-state"),
      ).toBeVisible();
    });

    test("알람 페이지에서 OwnedEmptyState가 표시된다", async ({ page }) => {
      await page.goto("/alarms");
      await clearOwnedCustomers(page);
      await page.reload();

      await expect(
        page.getByTestId("owned-empty-state"),
      ).toBeVisible();
    });

    test("GlobalFilterBar Customer 드롭다운이 disabled되고 빈 값(placeholder)을 가진다", async ({
      page,
    }) => {
      await page.goto("/dashboard");
      await clearOwnedCustomers(page);
      await page.reload();

      const select = page.getByLabel("Customer filter");
      await expect(select).toBeDisabled();
      // <option value="">담당 고객사 없음</option>이 선택된 상태 = value가 ""
      await expect(select).toHaveValue("");
    });
  });

  test.describe("담당 고객사 설정 후 필터링", () => {
    test("고객사 페이지에서 체크박스로 담당 고객사를 설정하면 드롭다운에 반영된다", async ({
      page,
    }) => {
      await page.goto("/customers");
      await clearOwnedCustomers(page);
      await page.reload();

      // 첫 번째 고객사의 담당 체크박스 클릭
      const firstCheckbox = page.getByRole("checkbox", { name: "담당" }).first();
      await firstCheckbox.check();

      // GlobalFilterBar에 해당 고객사가 나타나는지 확인
      const select = page.getByLabel("Customer filter");
      await expect(select).not.toBeDisabled();
    });

    test("담당 고객사 설정 후 대시보드가 OwnedEmptyState 대신 콘텐츠를 표시한다", async ({
      page,
    }) => {
      // cust-001(Acme Corp) 담당으로 설정 후 대시보드 접근
      await page.goto("/dashboard");
      await setOwnedCustomers(page, ["cust-001"]);
      await page.reload();

      await expect(page.getByTestId("owned-empty-state")).not.toBeVisible();
      // 통계 카드가 표시되어야 함
      await expect(page.getByText("Active Alarms")).toBeVisible();
    });

    test("GlobalFilterBar에 담당 고객사만 드롭다운 옵션으로 표시된다", async ({
      page,
    }) => {
      await page.goto("/dashboard");
      await setOwnedCustomers(page, ["cust-001"]);
      await page.reload();

      const customerSelect = page.getByLabel("Customer filter");
      // API 로딩 완료 후 옵션이 2개 이상(placeholder + 고객사)이 될 때까지 대기
      await expect(customerSelect.locator("option").nth(1)).toBeAttached();

      const optionTexts = await customerSelect.locator("option").allTextContents();
      // Acme Corp(cust-001) 은 포함, Globex Inc(cust-002) 는 미포함
      expect(optionTexts).toContain("Acme Corp");
      expect(optionTexts).not.toContain("Globex Inc");
    });
  });

  test.describe("URL 방어 (비담당 customer_id 자동 제거)", () => {
    test("URL에 비담당 customer_id가 있으면 자동으로 제거된다", async ({
      page,
    }) => {
      await page.goto("/dashboard");
      await setOwnedCustomers(page, ["cust-001"]);

      // 비담당 customer_id를 URL에 직접 설정
      await page.goto("/dashboard?customer_id=cust-002");

      // URL에서 customer_id가 제거되어야 함
      await expect(page).not.toHaveURL(/customer_id=cust-002/);
    });
  });

  test.describe("고객사 페이지 담당 체크박스 UI", () => {
    test("고객사 목록에 '담당' 컬럼이 존재한다", async ({ page }) => {
      await page.goto("/customers");
      await setOwnedCustomers(page, ["cust-001"]);
      await page.reload();

      await expect(page.getByRole("columnheader", { name: "담당" })).toBeVisible();
    });

    test("담당으로 설정된 고객사의 체크박스는 checked 상태다", async ({
      page,
    }) => {
      await page.goto("/customers");
      await setOwnedCustomers(page, ["cust-001"]);
      await page.reload();

      // 첫 번째 고객사(cust-001, Acme Corp)는 체크되어 있어야 함
      const checkboxes = page.getByRole("checkbox", { name: "담당" });
      await expect(checkboxes.first()).toBeChecked();
    });

    test("미설정 시 담당 없음 안내 배너가 표시된다", async ({ page }) => {
      await page.goto("/customers");
      await clearOwnedCustomers(page);
      await page.reload();

      // 실제 배너 문구: "담당 고객사를 선택하면 다른 화면에서 해당 고객사만 표시됩니다"
      await expect(
        page.getByText(/담당 고객사를 선택하면/),
      ).toBeVisible();
    });
  });
});
