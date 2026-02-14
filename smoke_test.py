import io
import os
import random
import re
import string
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from http.cookiejar import CookieJar

from decimal import Decimal, ROUND_HALF_EVEN


BASE = os.environ.get("BASE_URL", "http://localhost:8008").rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _rand_email() -> str:
    tail = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    return f"smoke_{tail}@example.com"


def _request(
    opener: urllib.request.OpenerDirector,
    method: str,
    path: str,
    data: dict | None = None,
    headers: dict | None = None,
) -> urllib.response.addinfourl:
    url = f"{BASE}{path}"
    body = None
    hdrs = headers or {}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=hdrs)
    try:
        return opener.open(req, timeout=20)
    except urllib.error.HTTPError as e:
        # When redirects are disabled (NoRedirect), urllib raises HTTPError for 30x.
        # The HTTPError object is a valid response-like object and includes headers.
        if int(getattr(e, "code", 0) or 0) in (301, 302, 303, 307, 308):
            return e
        raise


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----smoke" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(24))
    bio = io.BytesIO()

    def w(s: str):
        bio.write(s.encode("utf-8"))

    for k, v in fields.items():
        w(f"--{boundary}\r\n")
        w(f"Content-Disposition: form-data; name=\"{k}\"\r\n\r\n")
        w(str(v))
        w("\r\n")

    for k, f in files.items():
        filename = f.get("filename") or "file.pdf"
        content_type = f.get("content_type") or "application/pdf"
        content = f.get("content") or b""
        w(f"--{boundary}\r\n")
        w(
            f"Content-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        )
        bio.write(content)
        w("\r\n")

    w(f"--{boundary}--\r\n")
    return bio.getvalue(), boundary


def _run_cmd(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{out}")
    return out


def main() -> int:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener_noredir = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect())

    email = _rand_email()
    password = "smoke123"

    # Use a future/random competence to avoid clashing with existing runs in the DB
    test_year = random.randint(2090, 2199)
    test_month = random.randint(1, 12)

    print("[1] Register")
    _request(opener, "POST", "/auth/register", {"email": email, "password": password})

    print("[2] Login")
    _request(opener, "POST", "/auth/login", {"email": email, "password": password})

    # Optional: validate tax sync routine (requires docker + network)
    if os.environ.get("SMOKE_SKIP_DOCKER_SYNC") not in ("1", "true", "yes"):
        print("[2.1] Validate sync-taxes dry-run (docker)")
        out = _run_cmd(["docker", "compose", "exec", "web", "flask", "sync-taxes"])
        if "INSS (empregado):" not in out or "IRRF (mensal):" not in out:
            raise RuntimeError("sync-taxes output missing expected headers")

        # Structural validation: require at least a few bracket rows for each table.
        # docker compose exec output can include line wraps/CRs depending on TTY.
        # Split sections and count simple markers (more robust than matching full lines).
        try:
            inss_section = out.split("INSS (empregado):", 1)[1].split("IRRF (mensal):", 1)[0]
            irrf_section = out.split("IRRF (mensal):", 1)[1]
        except Exception:
            raise RuntimeError("sync-taxes output could not be split into INSS/IRRF sections")

        inss_count = len(re.findall(r"aliquota\s*=", inss_section, re.IGNORECASE))
        irrf_count = len(re.findall(r"deduzir\s*=", irrf_section, re.IGNORECASE))
        if inss_count < 3:
            raise RuntimeError(f"sync-taxes output seems to have too few INSS rows: {inss_count}")
        if irrf_count < 3:
            raise RuntimeError(f"sync-taxes output seems to have too few IRRF rows: {irrf_count}")

        # Dedução por dependente should be present (value may vary by year).
        if not re.search(r"dependente:\s*[0-9]+[\.,][0-9]{2}", out, re.IGNORECASE):
            raise RuntimeError("sync-taxes output missing dependent deduction line")

        # Optional numeric markers (2026-specific). If present, great; if absent, do not fail.
        # This keeps the smoke test more resilient to formatting/content changes upstream.

        print("[2.2] Validate sync-taxes --apply (docker)")
        out2 = _run_cmd(["docker", "compose", "exec", "web", "flask", "sync-taxes", "--apply"])
        if "OK: tabelas gravadas no banco." not in out2:
            raise RuntimeError("sync-taxes --apply did not confirm DB write")

    print("[3] Create employees")
    r1 = _request(opener_noredir, "POST", "/payroll/employees", {"full_name": "Deise", "cpf": "", "hired_at": ""})
    loc1 = r1.headers.get("Location") or ""
    m1 = re.search(r"/payroll/employees/(\d+)", loc1)
    if not m1:
        raise RuntimeError(f"Could not parse Deise employee id from redirect: {loc1}")
    deise_id = int(m1.group(1))

    r2 = _request(opener_noredir, "POST", "/payroll/employees", {"full_name": "Juvenaldo", "cpf": "", "hired_at": ""})
    loc2 = r2.headers.get("Location") or ""
    m2 = re.search(r"/payroll/employees/(\d+)", loc2)
    if not m2:
        raise RuntimeError(f"Could not parse Juvenaldo employee id from redirect: {loc2}")
    juvenaldo_id = int(m2.group(1))

    print("[4] Add salaries")
    for eid in (deise_id, juvenaldo_id):
        _request(
            opener,
            "POST",
            f"/payroll/employees/{eid}/salary",
            {"effective_from": "2026-01-01", "base_salary": "1685,00"},
        )

    print("[5] Create payroll run")
    r3 = _request(
        opener_noredir,
        "POST",
        "/payroll/",
        {"year": str(test_year), "month": str(test_month)},
    )
    loc3 = r3.headers.get("Location") or ""
    m3 = re.search(r"/payroll/(\d+)", loc3)
    if not m3:
        raise RuntimeError(f"Could not parse payroll run id from redirect: {loc3}")
    run_id = int(m3.group(1))

    print("[6] Save overtime")
    payload = {
        "overtime_hour_rate": "12,45",
        f"overtime_hours_{deise_id}": "10,50",
        f"overtime_hours_{juvenaldo_id}": "0,00",
    }
    _request(opener, "POST", f"/payroll/{run_id}", payload)

    print("[7] Validate calculated values")
    page = _request(opener, "GET", f"/payroll/{run_id}").read().decode("utf-8", errors="replace")

    base = Decimal("1685.00")
    hours = Decimal("10.50")
    rate = Decimal("12.45")
    overtime = (hours * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    total = (base + overtime).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    expected_total_value = f"{total:.2f}"
    input_name = f"overtime_hours_{deise_id}"

    # Find the table row that contains the Deise input, then extract the gross total from the same row.
    # Use a tempered dot so we don't accidentally span across multiple <tr> blocks.
    row_re = re.compile(
        rf"<tr>(?:(?!</tr>).)*name=\"{re.escape(input_name)}\"(?:(?!</tr>).)*</tr>",
        re.IGNORECASE | re.DOTALL,
    )
    mrow = row_re.search(page)
    if not mrow:
        i = page.find("Deise")
        excerpt = page[i : i + 800] if i >= 0 else page[:800]
        raise RuntimeError(f"Could not find payroll row for input '{input_name}'. Excerpt:\n{excerpt}")

    row_html = mrow.group(0)
    val_re = re.compile(rf"name=\"{re.escape(input_name)}\"[^>]*value=\"([^\"]+)\"", re.IGNORECASE)
    mval = val_re.search(row_html)
    if not mval:
        raise RuntimeError(f"Could not extract overtime hours input value for '{input_name}'.")
    got_hours = mval.group(1)
    if got_hours != "10.50":
        raise RuntimeError(
            f"Overtime hours not persisted for '{input_name}' (expected value=10.50, got {got_hours})."
        )

    total_re = re.compile(r"<strong>\s*R\$\s*([0-9]+\.[0-9]{2})\s*</strong>", re.IGNORECASE)
    totals = total_re.findall(row_html)
    if not totals:
        raise RuntimeError(f"Could not extract gross total from payroll row for '{input_name}'.")

    # Last strong in the row is the gross total
    got_total_value = totals[-1]
    if got_total_value != expected_total_value:
        raise RuntimeError(
            f"Gross total mismatch for '{input_name}': expected {expected_total_value}, got {got_total_value}. Row:\n{row_html}"
        )

    print("[7.1] Validate holerite page")
    hol = _request(opener, "GET", f"/payroll/{run_id}/holerite/{deise_id}").read().decode("utf-8", errors="replace")
    if "Holerite / Recibo de Pagamento" not in hol:
        raise RuntimeError("Holerite page title not found")
    if "Deise" not in hol:
        raise RuntimeError("Employee name not found in holerite")
    if f"R$ {expected_total_value}" not in hol:
        raise RuntimeError("Expected gross total not found in holerite")

    # If taxes are configured, holerite should not show "não configurado" for INSS.
    if "INSS (estimado)" in hol and "não configurado" in hol:
        raise RuntimeError("Holerite still shows taxes as not configured")

    print("[7.3] Register vacation and validate receipt")
    _request(
        opener,
        "POST",
        f"/payroll/employees/{deise_id}/vacations",
        {
            "year": str(test_year),
            "month": str(test_month),
            "start_date": f"{test_year}-{test_month:02d}-15",
            "pay_date": f"{test_year}-{test_month:02d}-13",
            "days": "15",
            "sell_days": "5",
        },
    )
    vac_page = _request(
        opener,
        "GET",
        f"/payroll/employees/{deise_id}/vacations?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "Férias" not in vac_page:
        raise RuntimeError("Vacations page title not found")
    if "15" not in vac_page or "5" not in vac_page:
        raise RuntimeError("Vacation days or sell_days not found in vacations page")
    # Extract vacation id from the receipt link
    vac_id_match = re.search(r"/vacations/(\d+)/receipt", vac_page)
    if not vac_id_match:
        raise RuntimeError("Could not find vacation receipt link")
    vac_id = int(vac_id_match.group(1))
    rec_page = _request(opener, "GET", f"/payroll/vacations/{vac_id}/receipt").read().decode("utf-8", errors="replace")
    if "Recibo de férias" not in rec_page:
        raise RuntimeError("Vacation receipt page title not found")
    if "Deise" not in rec_page:
        raise RuntimeError("Employee name not found in vacation receipt")
    if "1/3 constitucional" not in rec_page:
        raise RuntimeError("Vacation receipt missing 1/3 constitucional line")

    print("[7.4] Validate vacations appear in closing summary")
    close_page_vac = _request(
        opener,
        "GET",
        f"/payroll/close?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "Férias no mês" not in close_page_vac:
        raise RuntimeError("Close page missing vacations section")
    # The template renders: <strong>1</strong> registro(s)
    vac_count_re = re.search(r"<strong>\s*1\s*</strong>\s*registro", close_page_vac, re.IGNORECASE)
    if not vac_count_re:
        raise RuntimeError("Close page missing vacation count")

    print("[7.5] Register 13th salary and validate receipt")
    _request(
        opener,
        "POST",
        f"/payroll/employees/{deise_id}/thirteenth",
        {
            "reference_year": str(test_year),
            "payment_year": str(test_year),
            "payment_month": str(test_month),
            "pay_date": f"{test_year}-{test_month:02d}-15",
            "months_worked": "12",
            "payment_type": "2nd_installment",
        },
    )
    thirteenth_page = _request(
        opener,
        "GET",
        f"/payroll/employees/{deise_id}/thirteenth?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "13º Salário" not in thirteenth_page:
        raise RuntimeError("13th page title not found")
    if "2ª parcela" not in thirteenth_page:
        raise RuntimeError("13th payment type not found in page")
    # Extract 13th id from the receipt link
    thirteenth_id_match = re.search(r"/thirteenth/(\d+)/receipt", thirteenth_page)
    if not thirteenth_id_match:
        raise RuntimeError("Could not find 13th receipt link")
    thirteenth_id = int(thirteenth_id_match.group(1))
    thirteenth_rec_page = _request(opener, "GET", f"/payroll/thirteenth/{thirteenth_id}/receipt").read().decode("utf-8", errors="replace")
    if "Recibo 13º" not in thirteenth_rec_page:
        raise RuntimeError("13th receipt page title not found")
    if "Deise" not in thirteenth_rec_page:
        raise RuntimeError("Employee name not found in 13th receipt")
    if "CLT" not in thirteenth_rec_page:
        raise RuntimeError("CLT reference not found in 13th receipt")

    print("[7.6] Validate 13th appears in closing summary")
    close_page_13th = _request(
        opener,
        "GET",
        f"/payroll/close?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "13º no mês" not in close_page_13th:
        raise RuntimeError("Close page missing 13th section")
    thirteenth_count_re = re.search(r"<strong>\s*1\s*</strong>\s*registro", close_page_13th, re.IGNORECASE)
    if not thirteenth_count_re:
        raise RuntimeError("Close page missing 13th count")

    print("[7.7] Register one revenue note")
    _request(
        opener,
        "POST",
        "/payroll/revenue",
        {
            "year": str(test_year),
            "month": str(test_month),
            "issued_at": "",
            "customer_name": "Cliente teste",
            "description": "Nota teste",
            "amount": "150,00",
        },
    )
    rev_page = _request(
        opener,
        "GET",
        f"/payroll/revenue?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "Receitas / Notas" not in rev_page:
        raise RuntimeError("Revenue page title not found")
    if "R$ 150.00" not in rev_page:
        raise RuntimeError("Expected revenue amount not found in revenue page")

    print("[8] Upload sample DAS guide PDF")
    sample_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    mp_body, boundary = _multipart(
        {
            "year": str(test_year),
            "month": str(test_month),
            "doc_type": "das",
            "amount": "123,45",
            "due_date": "2026-03-20",
            "paid_at": "",
        },
        {"file": {"filename": "das.pdf", "content_type": "application/pdf", "content": sample_pdf}},
    )
    url = f"{BASE}/payroll/close/upload"
    req = urllib.request.Request(
        url,
        data=mp_body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    opener.open(req, timeout=20)

    print("[9] Validate guide link appears")
    close_page = _request(
        opener,
        "GET",
        f"/payroll/close?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    expected_guide = f"/media/guides/{test_year}-{test_month:02d}_das.pdf"
    if expected_guide not in close_page:
        raise RuntimeError("Expected DAS guide link not found in close page")

    if "Receitas / notas do mês" not in close_page:
        raise RuntimeError("Close page did not show revenue checklist item")

    if "Resumo do mês" not in close_page or "Total bruto" not in close_page:
        raise RuntimeError("Close page did not show the monthly summary block")

    print("[10] Mark competence as closed (warn-only)")
    _request(opener, "POST", "/payroll/close/mark", {"year": str(test_year), "month": str(test_month)})
    close_page2 = _request(
        opener,
        "GET",
        f"/payroll/close?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "Competência marcada como FECHADA" not in close_page2:
        raise RuntimeError("Close page did not show competence as closed")
    if "Reabrir competência" not in close_page2:
        raise RuntimeError("Close page missing reopen action when closed")

    print("[11] Reopen competence")
    _request(opener, "POST", "/payroll/close/reopen", {"year": str(test_year), "month": str(test_month)})
    close_page3 = _request(
        opener,
        "GET",
        f"/payroll/close?year={test_year}&month={test_month}",
    ).read().decode("utf-8", errors="replace")
    if "Competência em aberto" not in close_page3:
        raise RuntimeError("Close page did not show competence reopened")
    if "Marcar como fechada" not in close_page3:
        raise RuntimeError("Close page missing mark action when reopened")

    print("OK: smoke test passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"FAIL: {e}")
        raise
