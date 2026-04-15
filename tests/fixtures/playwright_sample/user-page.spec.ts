import { test, expect } from "@playwright/test";

test("navigates to detail page", async ({ page }) => {
    await page.goto("/users");
    await page.click("[data-testid=row-1]");
    await expect(page).toHaveURL("/detail?id=1");
});

test("shows validation error on form page", async ({ page }) => {
    await page.goto("/users/new");
    await page.fill("#email", "bad-mail");
    await page.focus("#password");
    await expect(page.locator("[role=alert]")).toContainText("入力エラー");
});