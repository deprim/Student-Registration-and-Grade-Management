"""Check demo workflows, responsive layouts, and optional axe accessibility rules."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("BROWSER_BASE_URL", "http://127.0.0.1:8000")
OUTPUT = Path("test-results")
OUTPUT.mkdir(exist_ok=True)
AXE_SCRIPT = os.getenv("BROWSER_AXE_SCRIPT")
WIDTHS = [1440, 1024, 768, 375]


def inspect_page(page, name, width, errors, expected_status=200, path=None):
    if path:
        response = page.goto(BASE_URL + path)
        assert response.status == expected_status, (path, response.status)
    page.evaluate("document.fonts.ready")
    assert page.locator("html").get_attribute("lang").startswith("en")
    assert page.locator("main h1").count() == 1, name
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (
        name,
        width,
    )
    assert not errors, errors
    if AXE_SCRIPT:
        page.add_script_tag(path=AXE_SCRIPT)
        result = page.evaluate(
            """async () => (await axe.run(document, {runOnly: {
                type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']
            }})).violations.map(v => ({id: v.id, impact: v.impact,
                nodes: v.nodes.map(n => ({target:n.target, issue:n.failureSummary}))}))"""
        )
        assert not result, (name, width, json.dumps(result, indent=2))
    page.screenshot(path=str(OUTPUT / f"{name}-{width}.png"), full_page=True)


def check_pages():
    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("BROWSER_EXECUTABLE"):
            options["executable_path"] = os.environ["BROWSER_EXECUTABLE"]
        browser = playwright.chromium.launch(**options)
        for width in WIDTHS:
            context = browser.new_context(viewport={"width": width, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for name, path in [
                ("login", "/accounts/login/"),
                ("register", "/accounts/register/"),
                ("password-reset", "/accounts/password/reset/"),
                ("password-reset-done", "/accounts/password/reset/done/"),
                ("password-reset-invalid", "/accounts/password/reset/invalid/invalid/"),
                ("password-reset-complete", "/accounts/password/reset/complete/"),
            ]:
                inspect_page(page, name, width, errors, path=path)
            inspect_page(page, "not-found", width, errors, 404, "/missing-page/")
            page.goto(BASE_URL + "/accounts/login/")
            page.locator('[name="username"]').fill("nobody@example.com")
            page.locator('[name="password"]').fill("InvalidPassword!2026")
            page.get_by_role("button", name="Sign in to your workspace").click()
            assert page.locator(".alert-danger").is_visible()
            inspect_page(page, "login-error", width, errors)
            print(f"Passed: public and error pages, {width}px", flush=True)
            context.close()

        for role, password in [
            ("admin", "DemoAdmin!2026"),
            ("teacher", "DemoTeacher!2026"),
            ("student", "DemoStudent!2026"),
            ("pending1", "DemoStudent!2026"),
            ("rejected", "DemoStudent!2026"),
        ]:
            for width in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{BASE_URL}/accounts/login/")
                page.locator('input[name="username"]').fill(f"{role}@campus.example")
                page.locator('input[name="password"]').fill(password)
                page.get_by_role("button", name="Sign in to your workspace").click()
                prefix = "management" if role == "admin" else role
                limited = role in ["pending1", "rejected"]
                home = "/accounts/status/" if limited else f"/{prefix}/"
                page.wait_for_url(BASE_URL + home)
                pages = [home, "/accounts/profile/", "/accounts/password/change/"]
                if role == "admin":
                    pages += [
                        "/management/users/",
                        "/management/users/new/",
                        "/management/offerings/",
                        "/management/offerings/new/",
                        "/management/courses/",
                        "/management/courses/new/",
                        "/management/semesters/",
                        "/management/semesters/new/",
                        "/management/audit/",
                        "/admin/",
                        "/admin/accounts/user/",
                        "/admin/grading/grade/",
                    ]
                elif role == "teacher":
                    pages += ["/teacher/offerings/"]
                elif role == "student":
                    pages += [
                        "/student/catalog/",
                        "/student/catalog/?q=no-matching-course",
                        "/student/courses/",
                        "/student/transcript/",
                    ]
                for index, path in enumerate(pages):
                    name = f"{role}-{index}-{path.split('?')[0].strip('/').replace('/', '-')}"
                    inspect_page(page, name, width, errors, path=path)
                if role in ["teacher", "student"]:
                    path = "/teacher/offerings/" if role == "teacher" else "/student/courses/"
                    page.goto(BASE_URL + path)
                    links = page.locator(".course-open").evaluate_all(
                        "links => links.map(a => a.pathname)"
                    )
                    for index, link in enumerate(links):
                        inspect_page(page, f"{role}-course-{index}", width, errors, path=link)
                        if role == "teacher":
                            assert page.get_by_role(
                                "heading", name="Student gradebook"
                            ).is_visible()
                    if role == "teacher" and links:
                        page.goto(BASE_URL + links[0])
                        create = page.get_by_role("link", name="Add assessment")
                        if create.count():
                            create.click()
                            inspect_page(page, "assessment-form", width, errors)
                if width < 992:
                    page.goto(BASE_URL + home)
                    page.get_by_role("button", name="Open navigation").click()
                    page.locator("#sidebar.show").wait_for()
                    page.keyboard.press("Escape")
                    page.locator("#sidebar").wait_for(state="hidden")
                print(
                    f"Passed: {role}, {width}px, {len(pages)} primary pages and course details",
                    flush=True,
                )
                context.close()
        browser.close()


if __name__ == "__main__":
    check_pages()
