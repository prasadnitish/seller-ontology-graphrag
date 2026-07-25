import { expect, test } from "@playwright/test";

test("edits semantics, preserves accessible work areas, and invalidates approval", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Incident Dependency Graph" })).toBeVisible();
  await expect(page.getByText("APPROVED", { exact: true })).toBeVisible();
  await expect(page.locator(".ontology-node")).toHaveCount(5);

  await page.getByRole("button", { name: "Mappings" }).click();
  await expect(page.getByText("0 unresolved")).toBeVisible();
  await expect(page.getByText("mapped", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Ontology" }).click();
  await page.getByRole("button", { name: "+ Add node" }).click();
  await expect(page.locator('input[value="NewEntity6"]')).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();

  await expect(page.getByText("DRAFT", { exact: true })).toBeVisible();
  await expect(page.getByText("Draft saved atomically")).toBeVisible();

  await page.getByRole("button", { name: "Validation" }).click();
  await expect(page.getByText("Ready for approval")).toBeVisible();
});

test("canvas and controls remain usable at a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Sources" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ontology map" })).toBeVisible();
  await expect(page.getByText("Drag changes layout only")).toBeVisible();
});
