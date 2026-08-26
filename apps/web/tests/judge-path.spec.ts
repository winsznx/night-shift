import { expect, test } from "@playwright/test";

/**
 * The judge path: landing → console → incident → proof → verify, plus the fleet and
 * drill surfaces. Every assertion here is something a judge would actually look for.
 */

test.describe("judge path", () => {
  test("landing page states the workflow and labels the environment", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /when the freezer fails/i }),
    ).toBeVisible();

    // The synthetic disclaimer must be on the first screen, not buried.
    await expect(page.getByText(/no real biobank samples were moved/i).first()).toBeVisible();

    // Primary calls to action exist and point somewhere real.
    await expect(page.getByRole("link", { name: /watch the rescue/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /explore failure drills/i })).toBeVisible();
  });

  test("landing has no dead controls", async ({ page }) => {
    await page.goto("/");
    const links = page.locator("a[href]");
    const count = await links.count();
    expect(count).toBeGreaterThan(5);
    for (let i = 0; i < count; i++) {
      const href = await links.nth(i).getAttribute("href");
      expect(href, "every link must resolve somewhere").toBeTruthy();
      expect(href).not.toBe("#");
    }
  });

  test("operations console shows estate state", async ({ page }) => {
    await page.goto("/app");
    await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
    await expect(page.getByText(/active incidents/i).first()).toBeVisible();
    await expect(page.getByText("F-17").first()).toBeVisible();
    // The notice is rendered twice, once per breakpoint, so assert that a *visible*
    // one exists rather than that the first in DOM order happens to be shown.
    await expect(
      page.getByText(/synthetic data/i).locator("visible=true").first(),
    ).toBeVisible();
  });

  test("fleet page shows the permission matrix with real gaps", async ({ page }) => {
    await page.goto("/app/fleet");
    await expect(page.getByRole("heading", { name: "Agent fleet" })).toBeVisible();
    await expect(page.getByText("Permission matrix").first()).toBeVisible();

    // Every operational agent appears.
    for (const agent of [
      "incident-commander",
      "signal-investigator",
      "impact-analyst",
      "capacity-broker",
      "dispatch-agent",
      "custody-agent",
    ]) {
      await expect(page.getByText(agent).first()).toBeVisible();
    }

    // The Commander row must show no write authority anywhere — that is the claim.
    const commanderRow = page.locator("tr", { hasText: "incident-commander" }).last();
    await expect(commanderRow).not.toContainText("write");
  });

  test("drills page reports measured results", async ({ page }) => {
    await page.goto("/app/drills");
    await expect(page.getByRole("heading", { name: /disaster drill range/i })).toBeVisible();
    await expect(page.getByText("D1").first()).toBeVisible();
    await expect(page.getByText("D18").first()).toBeVisible();
    await expect(page.getByText(/holdout corpus/i)).toBeVisible();
  });

  test("drill detail explains its expectations", async ({ page }) => {
    await page.goto("/app/drills/D5");
    await expect(page.getByText(/reservation response lost after commit/i).first()).toBeVisible();
    await expect(page.getByText("no_duplicate_effect").first()).toBeVisible();
    await expect(page.getByText("fault_actually_fired").first()).toBeVisible();
  });

  test("verify page explains every result state", async ({ page }) => {
    await page.goto("/verify");
    await expect(page.getByRole("heading", { name: /check the evidence/i })).toBeVisible();
    await expect(page.getByText("PASS").first()).toBeVisible();
    await expect(page.getByText("MISMATCH").first()).toBeVisible();
    await expect(page.getByText("PARTIAL").first()).toBeVisible();
    await expect(page.getByText(/what the verifier cannot tell you/i)).toBeVisible();
  });

  test("evidence page shows the claim ledger", async ({ page }) => {
    await page.goto("/app/evidence");
    await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await expect(page.getByText(/claim ledger/i).first()).toBeVisible();
  });
});

test.describe("incident detail", () => {
  test("shows reconciliation, invariants, and separated timeline", async ({ page, request }) => {
    const overview = await (await request.get("/api/overview")).json();
    test.skip(!overview?.incidents?.length, "no incident seeded in this environment");
    const id = overview.incidents[0].incident_id;

    await page.goto(`/app/incidents/${id}`);
    await expect(page.getByRole("heading", { name: id })).toBeVisible();

    // The headline numbers a responder needs first.
    await expect(page.getByText(/impacted/i).first()).toBeVisible();
    await expect(page.getByText(/unresolved/i).first()).toBeVisible();

    // The safety kernel panel lists all thirteen invariants.
    await expect(page.getByRole("heading", { name: "Safety kernel" })).toBeVisible();
    for (const n of ["N1", "N5", "N6", "N13"]) {
      await expect(page.getByText(n, { exact: true }).first()).toBeVisible();
    }

    // Agent decisions and deterministic receipts are both present and distinguished.
    await expect(page.getByRole("heading", { name: "Deterministic receipts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  });

  test("proof page verifies live and links the verifier command", async ({ page, request }) => {
    const evidence = await (await request.get("/api/evidence")).json();
    test.skip(!evidence?.manifests?.length, "no manifest published in this environment");
    const id = evidence.manifests[0].incident_id;

    await page.goto(`/proof/${id}`);
    await expect(page.getByRole("heading", { name: id })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verification checks" })).toBeVisible();
    await expect(page.getByText(/python -m nightshift\.verify/).first()).toBeVisible();

    // Synthetic provenance is stated on the public proof surface.
    await expect(page.getByText("synthetic data").first()).toBeVisible();
  });
});

test.describe("failure and refusal states are visible", () => {
  test("capacity page explains why a freezer with room is unusable", async ({ page }) => {
    await page.goto("/app/capacity");
    await expect(page.getByRole("heading", { name: "Capacity" })).toBeVisible();
    await expect(page.getByText(/ineligible|eligible/i).first()).toBeVisible();
  });

  test("freezers page explains free space is not availability", async ({ page }) => {
    await page.goto("/app/freezers");
    await expect(page.getByText(/free space is not availability/i)).toBeVisible();
  });
});

test.describe("hero console tour", () => {
  test("walks from the estate through to signed evidence", async ({ page }, testInfo) => {
    await page.goto("/");
    // The rail is the desktop affordance; below lg the tour exposes a stepper instead.
    const desktop = testInfo.project.name === "desktop";
    const controls = desktop
      ? page.locator('nav[aria-label="Command console preview"] button')
      : page.locator('[aria-label="Overview"], [aria-label="Evidence"]');
    await controls.first().scrollIntoViewIfNeeded();

    // More than one stop, or the hero is back to being a single posed screenshot.
    expect(await controls.count()).toBeGreaterThan(1);

    // Clicking a stop shows that surface, so the tour is navigable and not decoration.
    const evidence = page.getByRole("button", { name: "Evidence" }).first();
    if (await evidence.count()) {
      await evidence.click();
      await expect(evidence).toHaveAttribute("aria-current", "true");
      await expect(page.getByText(/signed incident manifests/i).first()).toBeVisible();
    }
  });

  test("the rail fills the frame so the rounded corner is never broken", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "the rail only renders at lg and above");
    await page.goto("/");
    const rail = page.locator('nav[aria-label="Command console preview"]');
    await rail.scrollIntoViewIfNeeded();
    const aside = page.locator("aside").filter({ has: rail });
    const frame = page.locator("div.rounded-\\[16px\\]").first();

    const asideBox = await aside.boundingBox();
    const frameBox = await frame.boundingBox();
    // The tinted rail column must reach the bottom of the frame. When a short panel was
    // active it stopped early and left a square-cornered white gap inside the rounding.
    expect(
      Math.abs(asideBox!.y + asideBox!.height - (frameBox!.y + frameBox!.height)),
    ).toBeLessThan(2);
  });
});
