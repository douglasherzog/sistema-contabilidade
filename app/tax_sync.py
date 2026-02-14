import io
import re
from datetime import date, timedelta
from decimal import Decimal

import click
import requests
from bs4 import BeautifulSoup
import pdfplumber
from flask import Flask

from .extensions import db
from .models import (
    EmployeeLeave,
    EmployeeTermination,
    EmployeeThirteenth,
    EmployeeVacation,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)


INSS_URL = "https://www.gov.br/inss/pt-br/direitos-e-deveres/inscricao-e-contribuicao/tabela-de-contribuicao-mensal"
IRRF_URL_TEMPLATE = "https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/tabelas/{year}"

# Fallback sources are year-specific and may change URL slug every year.
# Keep known official URLs here. HTML parsing is the primary path.
INSS_PDF_URLS: dict[int, str] = {
    2026: "https://www.gov.br/previdencia/pt-br/assuntos/rpps/documentos/PortariaInterministerialMPSMF13de9dejaneirode2026.pdf",
}
INSS_NEWS_URLS: dict[int, str] = {
    2026: "https://www.gov.br/inss/pt-br/assuntos/com-reajuste-de-3-9-teto-do-inss-chega-a-r-8-475-55-em-2026",
}


def _to_decimal_ptbr(s: str) -> Decimal:
    s = (s or "").strip()
    s = s.replace("R$", "").replace("\u00a0", " ").strip()
    s = s.replace(".", "").replace(",", ".")
    return Decimal(s)


def _extract_money_values(text: str) -> list[Decimal]:
    vals = []
    for m in re.finditer(r"R\$\s*([0-9\.]+,[0-9]{2})", text or ""):
        vals.append(_to_decimal_ptbr(m.group(1)))
    return vals


def fetch_inss_employee_brackets(year: int) -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    effective_from = date(int(year), 1, 1)

    # First attempt: HTML table
    r = requests.get(INSS_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    tables = soup.find_all("table")
    if not tables:
        tables = []

    chosen = None
    for t in tables:
        head = " ".join(th.get_text(" ", strip=True) for th in t.find_all("th"))
        if ("Salário" in head or "Salario" in head) and ("Alíquota" in head or "Aliquota" in head):
            chosen = t
            break
    if chosen is None and tables:
        chosen = tables[0]

    rows: list[tuple[Decimal | None, Decimal]] = []
    if chosen is not None:
        for tr in chosen.find_all("tr"):
            cols = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"]) if td.get_text(strip=True)]
            if len(cols) < 2:
                continue

            salary_col = cols[0]
            rate_col = cols[-1]

            # Skip header rows
            if (
                ("Alíquota" in salary_col)
                or ("Aliquota" in salary_col)
                or ("Alíquota" in rate_col)
                or ("Aliquota" in rate_col)
            ):
                continue

            mrate = re.search(r"([0-9]{1,2},[0-9]+)\s*%", rate_col)
            if not mrate:
                continue
            rate = _to_decimal_ptbr(mrate.group(1)) / Decimal("100")

            money = _extract_money_values(salary_col)
            if not money:
                continue
            up_to = money[-1]
            if re.search(r"acima|a partir", salary_col, re.IGNORECASE):
                up_to = None

            rows.append((up_to, rate))

    if not rows:
        raise RuntimeError("Não consegui extrair as faixas do INSS (empregado) automaticamente.")

    # Guard-rail: empregado/CLT costuma ter múltiplas faixas (ex.: 4). Se vier só 1,
    # significa que pegamos a tabela errada ou a página mudou. Não é seguro aplicar.
    if len(rows) < 3:
        raise RuntimeError(
            f"Extração INSS retornou poucas faixas ({len(rows)}). Abortando para evitar gravar dados incompletos."
        )

    return effective_from, rows


def fetch_inss_employee_brackets_from_pdf(year: int, pdf_url: str) -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    effective_from = date(int(year), 1, 1)
    r = requests.get(pdf_url, timeout=60)
    r.raise_for_status()

    rows: list[tuple[Decimal | None, Decimal]] = []

    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for page in pdf.pages[:10]:
            text = page.extract_text() or ""
            for line in text.splitlines():
                if "R$" not in line or "%" not in line:
                    continue
                # Try to capture something like: "Até R$ 1.621,00 7,5%" or "De R$ ... até R$ ... 9%"
                money = _extract_money_values(line)
                mrate = re.search(r"([0-9]{1,2},[0-9]+)\s*%", line)
                if not money or not mrate:
                    continue
                up_to = money[-1]
                if re.search(r"acima|a partir", line, re.IGNORECASE):
                    up_to = None
                rate = _to_decimal_ptbr(mrate.group(1)) / Decimal("100")
                rows.append((up_to, rate))

    # Deduplicate and sort
    uniq: dict[str, tuple[Decimal | None, Decimal]] = {}
    for up_to, rate in rows:
        key = f"{up_to}-{rate}"
        uniq[key] = (up_to, rate)
    cleaned = list(uniq.values())
    cleaned.sort(key=lambda x: (Decimal("999999999") if x[0] is None else x[0]))

    if len(cleaned) < 3:
        raise RuntimeError(f"Extração INSS via PDF também retornou poucas faixas ({len(cleaned)}).")
    return effective_from, cleaned


def fetch_inss_employee_brackets_from_news(year: int, news_url: str) -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    """Fallback mais robusto: notícia oficial do INSS costuma trazer as faixas e alíquotas em texto.

    Exemplo (jan/2026):
    • 7,5% para quem ganha até R$ 1.621,00;
    • 9% para quem ganha entre R$ 1.621,01 e R$ 2.902,84;
    • 12% para quem ganha entre R$ 2.902,85 e R$ 4.354,27;
    • 14% para quem ganha de R$ 4.354,28 até R$ 8.475,55.
    """

    effective_from = date(int(year), 1, 1)
    r = requests.get(news_url, timeout=30)
    r.raise_for_status()

    # Keep punctuation so we can parse decimals.
    text = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)

    rows: list[tuple[Decimal | None, Decimal]] = []

    # Split by bullet marker used in gov.br news (often "•").
    parts = [p.strip() for p in text.split("•") if p.strip()]
    for p in parts:
        # Accept: 7,5% or 9% etc.
        mrate = re.search(r"^(?P<rate>[0-9]{1,2}(?:,[0-9]+)?)%", p)
        if not mrate:
            continue
        rate_raw = mrate.group("rate")
        if "," not in rate_raw:
            rate_raw = rate_raw + ",0"
        rate = _to_decimal_ptbr(rate_raw) / Decimal("100")

        money = _extract_money_values(p)
        if not money:
            continue
        # In phrases like "entre R$ A e R$ B" or "de R$ A até R$ B",
        # the last value is the upper bound.
        up_to = money[-1]
        rows.append((up_to, rate))

    if not rows:
        raise RuntimeError("Não encontrei faixas do INSS na notícia oficial (regex não casou).")

    # Deduplicate and sort
    uniq: dict[str, tuple[Decimal | None, Decimal]] = {}
    for up_to, rate in rows:
        uniq[f"{up_to}-{rate}"] = (up_to, rate)
    cleaned = list(uniq.values())
    cleaned.sort(key=lambda x: (Decimal("999999999") if x[0] is None else x[0]))

    if len(cleaned) < 3:
        raise RuntimeError(f"Extração INSS via notícia retornou poucas faixas ({len(cleaned)}).")
    return effective_from, cleaned


def fetch_irrf_monthly_table(year: int) -> tuple[date, Decimal, list[tuple[Decimal | None, Decimal, Decimal]], str]:
    irrf_url = IRRF_URL_TEMPLATE.format(year=int(year))
    r = requests.get(irrf_url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    effective_from = date(int(year), 1, 1)

    txt = soup.get_text(" ", strip=True)
    mdep = re.search(r"Dedu[cç]ão mensal por dependente:\s*R\$\s*([0-9\.]+,[0-9]{2})", txt)
    if not mdep:
        raise RuntimeError("Não encontrei a dedução mensal por dependente na página da Receita.")
    dep_ded = _to_decimal_ptbr(mdep.group(1))

    tables = soup.find_all("table")
    if not tables:
        raise RuntimeError("Não encontrei tabelas HTML na página da Receita.")

    chosen = None
    for t in tables:
        head = " ".join(th.get_text(" ", strip=True) for th in t.find_all("th"))
        if ("Parcela" in head and "deduz" in head.lower()) or ("Base" in head and "Alíquota" in head):
            chosen = t
            break

    if chosen is None:
        raise RuntimeError("Não encontrei a tabela progressiva mensal (faixas) na página da Receita.")

    rows: list[tuple[Decimal | None, Decimal, Decimal]] = []
    for tr in chosen.find_all("tr"):
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"]) if td.get_text(strip=True)]
        if len(cols) < 3:
            continue
        line = " ".join(cols)
        if "Alíquota" in line or "Aliquota" in line:
            continue

        money = _extract_money_values(line)
        if not money:
            continue

        # First monetary value in the row is typically the upper bound of the bracket.
        up_to: Decimal | None = money[0]
        if re.search(r"acima|a partir", line, re.IGNORECASE):
            up_to = None

        mrate = re.search(r"([0-9]{1,2},[0-9]+)\s*%", line)
        if not mrate:
            continue
        rate = (_to_decimal_ptbr(mrate.group(1)) / Decimal("100"))

        ded = money[-1] if len(money) >= 2 else Decimal("0")
        rows.append((up_to, rate, ded))

    # Some pages omit the 0% bracket in HTML; if the first bracket we parsed is 7.5%,
    # we keep it as-is (still valid for our MVP). We avoid inventing missing rows.

    if not rows:
        raise RuntimeError("Não consegui extrair as faixas do IRRF automaticamente.")

    # Guard-rail: tabela mensal costuma ter várias faixas.
    if len(rows) < 3:
        raise RuntimeError(
            f"Extração IRRF retornou poucas faixas ({len(rows)}). Abortando para evitar gravar dados incompletos."
        )

    return effective_from, dep_ded, rows, irrf_url


def run_tax_sync(target_year: int, apply_changes: bool = False) -> dict:
    if target_year < 2000 or target_year > 9999:
        raise ValueError("Ano inválido para sync-taxes.")

    inss_eff = None
    inss_rows: list[tuple[Decimal | None, Decimal]] = []
    irrf_eff = None
    dep_ded = None
    irrf_rows: list[tuple[Decimal | None, Decimal, Decimal]] = []
    irrf_url = IRRF_URL_TEMPLATE.format(year=int(target_year))

    inss_source = None
    irrf_source = None

    inss_error = None
    irrf_error = None

    try:
        inss_eff, inss_rows = fetch_inss_employee_brackets(target_year)
        if len(inss_rows) < 3:
            raise RuntimeError(f"Extração INSS retornou poucas faixas ({len(inss_rows)}).")
        inss_source = "html"
    except Exception as e:
        inss_error = str(e)
        news_url = INSS_NEWS_URLS.get(int(target_year))
        pdf_url = INSS_PDF_URLS.get(int(target_year))
        e2 = None
        e3 = None
        if news_url:
            try:
                inss_eff, inss_rows = fetch_inss_employee_brackets_from_news(target_year, news_url)
                inss_source = "news"
            except Exception as ex_news:
                e2 = ex_news
        if (not inss_rows) and pdf_url:
            try:
                inss_eff, inss_rows = fetch_inss_employee_brackets_from_pdf(target_year, pdf_url)
                inss_source = "pdf"
            except Exception as ex_pdf:
                e3 = ex_pdf
        if not inss_rows:
            notes = []
            if e2 is not None:
                notes.append(f"Fallback notícia falhou: {e2}")
            if e3 is not None:
                notes.append(f"Fallback PDF falhou: {e3}")
            if not news_url:
                notes.append("Sem URL de notícia mapeada para este ano")
            if not pdf_url:
                notes.append("Sem URL de portaria PDF mapeada para este ano")
            inss_error = f"{inss_error} | {' | '.join(notes)}"

    try:
        irrf_eff, dep_ded, irrf_rows, irrf_url = fetch_irrf_monthly_table(target_year)
        irrf_source = "html"
    except Exception as e:
        irrf_error = str(e)

    report_lines: list[str] = []
    report_lines.append("INSS (empregado):")
    report_lines.append(f"Ano alvo: {target_year}")
    if inss_source:
        report_lines.append(f"Fonte utilizada: {inss_source}")
    report_lines.append(f"Fonte HTML: {INSS_URL}")
    report_lines.append(f"Fonte notícia (INSS): {INSS_NEWS_URLS.get(int(target_year), 'não mapeada')}")
    report_lines.append(f"Fonte PDF (Portaria): {INSS_PDF_URLS.get(int(target_year), 'não mapeada')}")
    if inss_rows and inss_eff:
        report_lines.append(f"Vigência sugerida: {inss_eff.isoformat()}")
        for up_to, rate in inss_rows:
            report_lines.append(f" - até={up_to if up_to is not None else '—'} | aliquota={rate}")
    else:
        report_lines.append(f"ERRO ao extrair INSS: {inss_error}")

    report_lines.append("")
    report_lines.append("IRRF (mensal):")
    if irrf_source:
        report_lines.append(f"Fonte utilizada: {irrf_source}")
    report_lines.append(irrf_url)
    if irrf_rows and irrf_eff and dep_ded is not None:
        report_lines.append(f"Vigência sugerida: {irrf_eff.isoformat()}")
        report_lines.append(f"Dedução por dependente: {dep_ded}")
        for up_to, rate, ded in irrf_rows:
            report_lines.append(f" - até={up_to if up_to is not None else '—'} | aliquota={rate} | deduzir={ded}")
    else:
        report_lines.append(f"ERRO ao extrair IRRF: {irrf_error}")

    if not apply_changes:
        report_lines.append("")
        report_lines.append("DRY-RUN: nada foi gravado. Para gravar, execute novamente com --apply.")

    applied = False
    if apply_changes:
        if not (inss_rows and inss_eff and irrf_rows and irrf_eff and dep_ded is not None):
            raise RuntimeError("Não é seguro aplicar: alguma tabela não foi extraída corretamente.")

        TaxInssBracket.query.filter_by(effective_from=inss_eff).delete()
        for up_to, rate in inss_rows:
            db.session.add(TaxInssBracket(effective_from=inss_eff, up_to=up_to, rate=rate))

        cfg = TaxIrrfConfig.query.filter_by(effective_from=irrf_eff).first()
        if not cfg:
            cfg = TaxIrrfConfig(effective_from=irrf_eff, dependent_deduction=dep_ded)
            db.session.add(cfg)
        else:
            cfg.dependent_deduction = dep_ded

        TaxIrrfBracket.query.filter_by(effective_from=irrf_eff).delete()
        for up_to, rate, ded in irrf_rows:
            db.session.add(TaxIrrfBracket(effective_from=irrf_eff, up_to=up_to, rate=rate, deduction=ded))

        db.session.commit()
        applied = True
        report_lines.append("OK: tabelas gravadas no banco.")

    return {
        "target_year": target_year,
        "inss_eff": inss_eff,
        "inss_rows": inss_rows,
        "inss_source": inss_source,
        "inss_error": inss_error,
        "irrf_eff": irrf_eff,
        "irrf_rows": irrf_rows,
        "dep_ded": dep_ded,
        "irrf_source": irrf_source,
        "irrf_error": irrf_error,
        "irrf_url": irrf_url,
        "applied": applied,
        "report_lines": report_lines,
    }


def run_compliance_check(target_year: int, apply_tax_sync: bool = False) -> dict:
    """Run compliance checks and optionally auto-apply fiscal table sync."""
    if target_year < 2000 or target_year > 9999:
        raise ValueError("Ano inválido para compliance-check.")

    issues: list[str] = []
    infos: list[str] = []

    # 1) Tabelas fiscais oficiais (INSS/IRRF)
    expected_eff = date(int(target_year), 1, 1)
    db_inss_count = TaxInssBracket.query.filter_by(effective_from=expected_eff).count()
    db_irrf_count = TaxIrrfBracket.query.filter_by(effective_from=expected_eff).count()
    db_irrf_cfg = TaxIrrfConfig.query.filter_by(effective_from=expected_eff).first()

    need_tax_sync = db_inss_count < 3 or db_irrf_count < 3 or db_irrf_cfg is None
    sync_report_lines: list[str] = []
    if need_tax_sync:
        if apply_tax_sync:
            infos.append("Aplicando sync-taxes automático...")
            sync_result = run_tax_sync(target_year=target_year, apply_changes=True)
            sync_report_lines = list(sync_result.get("report_lines") or [])

            # Re-check after applying
            db_inss_count = TaxInssBracket.query.filter_by(effective_from=expected_eff).count()
            db_irrf_count = TaxIrrfBracket.query.filter_by(effective_from=expected_eff).count()
            db_irrf_cfg = TaxIrrfConfig.query.filter_by(effective_from=expected_eff).first()
            if db_inss_count >= 3 and db_irrf_count >= 3 and db_irrf_cfg is not None:
                infos.append("sync-taxes aplicado automaticamente e tabelas atualizadas.")
            else:
                issues.append(
                    f"Tabelas fiscais continuam incompletas após sync para {target_year}: INSS={db_inss_count} faixas, IRRF={db_irrf_count} faixas, cfg={'ok' if db_irrf_cfg else 'ausente'}."
                )
        else:
            issues.append(
                f"Tabelas fiscais incompletas para {target_year}: INSS={db_inss_count} faixas, IRRF={db_irrf_count} faixas, cfg={'ok' if db_irrf_cfg else 'ausente'}."
            )
    else:
        infos.append(f"Tabelas INSS/IRRF para {target_year} parecem completas.")

    # 2) CLT - 13º prazos
    nov_30 = date(int(target_year), 11, 30)
    dec_20 = date(int(target_year), 12, 20)

    first_installments = EmployeeThirteenth.query.filter_by(reference_year=target_year, payment_type="1st_installment").all()
    for r in first_installments:
        if int(r.payment_month) != 11:
            issues.append(f"13º 1ª parcela fora de novembro (id={r.id}, funcionário={r.employee_id}).")
        if r.pay_date and r.pay_date > nov_30:
            issues.append(f"13º 1ª parcela paga após 30/11 (id={r.id}, data={r.pay_date.isoformat()}).")

    second_installments = EmployeeThirteenth.query.filter_by(reference_year=target_year, payment_type="2nd_installment").all()
    for r in second_installments:
        if int(r.payment_month) != 12:
            issues.append(f"13º 2ª parcela fora de dezembro (id={r.id}, funcionário={r.employee_id}).")
        if r.pay_date and r.pay_date > dec_20:
            issues.append(f"13º 2ª parcela paga após 20/12 (id={r.id}, data={r.pay_date.isoformat()}).")

    # 3) CLT - férias (pagamento até 2 dias antes do início)
    vacations = EmployeeVacation.query.filter_by(year=target_year).all()
    for v in vacations:
        if v.pay_date and v.start_date and v.pay_date > (v.start_date - timedelta(days=2)):
            issues.append(
                f"Férias com pagamento fora do prazo legal (id={v.id}, funcionário={v.employee_id}, início={v.start_date.isoformat()}, pagamento={v.pay_date.isoformat()})."
            )

    # 4) Rescisões - consistência básica
    terminations = EmployeeTermination.query.filter_by(year=target_year).all()
    for t in terminations:
        if t.employee and t.employee.active:
            issues.append(
                f"Rescisão registrada mas funcionário permanece ativo (termination_id={t.id}, employee_id={t.employee_id})."
            )

        expected_fgts_rate = Decimal("0")
        if t.termination_type == "without_cause":
            expected_fgts_rate = Decimal("0.40")
            if t.notice_type == "none":
                issues.append(
                    f"Rescisão sem justa causa sem aviso prévio definido (termination_id={t.id})."
                )
        elif t.termination_type == "agreement":
            expected_fgts_rate = Decimal("0.20")
            if t.notice_type == "none":
                issues.append(
                    f"Rescisão por acordo sem aviso prévio definido (termination_id={t.id})."
                )

        fgts_balance = Decimal(str(t.fgts_balance_est or 0))
        fgts_rate = Decimal(str(t.fgts_fine_rate or 0))
        fgts_fine = Decimal(str(t.fgts_fine_est or 0))
        if expected_fgts_rate > 0 and fgts_balance > 0:
            if fgts_rate <= 0:
                issues.append(
                    f"Rescisão sem alíquota de multa FGTS configurada (termination_id={t.id})."
                )
            elif abs(fgts_rate - expected_fgts_rate) > Decimal("0.0001"):
                issues.append(
                    f"Rescisão com alíquota FGTS divergente (termination_id={t.id}, esperada={expected_fgts_rate}, informada={fgts_rate})."
                )
            expected_fine = (fgts_balance * expected_fgts_rate).quantize(Decimal("0.01"))
            if abs(fgts_fine - expected_fine) > Decimal("0.05"):
                issues.append(
                    f"Rescisão com multa FGTS divergente (termination_id={t.id}, esperada={expected_fine}, informada={fgts_fine})."
                )

    # 5) Afastamentos - consistência e regra simplificada INSS (>15 dias médicos)
    leaves = EmployeeLeave.query.filter_by(year=target_year).all()
    for lv in leaves:
        if lv.end_date < lv.start_date:
            issues.append(
                f"Afastamento com período inválido (leave_id={lv.id}, início={lv.start_date.isoformat()}, fim={lv.end_date.isoformat()})."
            )
            continue
        duration_days = (lv.end_date - lv.start_date).days + 1
        if lv.leave_type == "medical" and duration_days > 15 and lv.paid_by == "company":
            issues.append(
                f"Afastamento médico >15 dias sem INSS/misto (leave_id={lv.id}, funcionário={lv.employee_id}, dias={duration_days})."
            )

    report_lines: list[str] = [f"Compliance check - ano {target_year}"]
    if infos:
        report_lines.append("")
        report_lines.append("Informações:")
        for i in infos:
            report_lines.append(f" - {i}")

    if issues:
        report_lines.append("")
        report_lines.append("Não conformidades / alertas:")
        for it in issues:
            report_lines.append(f" - {it}")
    else:
        report_lines.append("")
        report_lines.append("OK: nenhuma não conformidade detectada nas regras verificadas.")

    return {
        "target_year": target_year,
        "infos": infos,
        "issues": issues,
        "ok": len(issues) == 0,
        "sync_report_lines": sync_report_lines,
        "report_lines": report_lines,
    }


def register_commands(app: Flask) -> None:
    @app.cli.command("sync-taxes")
    @click.option("--apply", "apply_changes", is_flag=True)
    @click.option("--year", "target_year", type=int, default=date.today().year, show_default=True)
    def sync_taxes(apply_changes: bool, target_year: int) -> None:
        try:
            result = run_tax_sync(target_year=target_year, apply_changes=apply_changes)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        for line in result["report_lines"]:
            click.echo(line)

    @app.cli.command("compliance-check")
    @click.option("--year", "target_year", type=int, default=date.today().year, show_default=True)
    @click.option("--apply-tax-sync", is_flag=True, help="Atualiza tabelas INSS/IRRF automaticamente se houver divergência.")
    def compliance_check(target_year: int, apply_tax_sync: bool) -> None:
        """Verifica conformidade legal mínima (CLT + tabelas fiscais oficiais)."""
        try:
            result = run_compliance_check(target_year=target_year, apply_tax_sync=apply_tax_sync)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        if result.get("sync_report_lines"):
            for line in result["sync_report_lines"]:
                click.echo(line)

        for line in result["report_lines"]:
            click.echo(line)

        if not result.get("ok"):
            raise click.ClickException(f"Foram encontrados {len(result.get('issues') or [])} alerta(s) de conformidade.")
