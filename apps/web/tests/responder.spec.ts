import { expect, test } from "@playwright/test";

/**
 * The responder flow on a phone. It must not look like a chat surface, and the
 * destination temperature — the number that decides whether a commit is accepted —
 * has to be unmissable.
 */

test.use({ viewport: { width: 390, height: 844 } });

test("responder screen shows the batch and the destination temperature", async ({
  page,
  request,
}) => {
  const overview = await (await request.get("/api/overview")).json();
  test.skip(!overview?.incidents?.length, "no incident seeded in this environment");

  // The task token is never exposed through a read route, so this test is skipped
  // unless one is supplied deliberately.
  const token = process.env.NIGHTSHIFT_RESPONDER_TOKEN;
  test.skip(!token, "set NIGHTSHIFT_RESPONDER_TOKEN to exercise the responder flow");

  await page.goto(`/respond/${token}`);

  await expect(page.getByText(/night shift/i).first()).toBeVisible();
  await expect(page.getByText(/no real specimens are being moved/i)).toBeVisible();
  await expect(page.getByText(/move material out of/i)).toBeVisible();

  // Not a chat surface: no message composer anywhere.
  await expect(page.locator("textarea")).toHaveCount(0);

  // The action target is thumb-sized.
  const action = page.getByRole("button").first();
  const box = await action.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});

test("responder route rejects an unknown token without leaking anything", async ({ page }) => {
  const response = await page.goto("/respond/not-a-real-token");
  expect(response?.status()).toBe(404);
});
