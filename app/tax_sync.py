import io
import re
from datetime import date
from decimal import Decimal

import click
import requests
from bs4 import BeautifulSoup
import pdfplumber
from flask import Flask

from .extensions import db
from .models import TaxInssBracket, TaxIrrfBracket, TaxIrrfConfig


INSS_URL = "https://www.gov.br/inss/pt-br/direitos-e-deveres/inscricao-e-contribuicao/tabela-de-contribuicao-mensal"
IRRF_URL = "https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/tabelas/2026"
INSS_PDF_URL = "https://www.gov.br/previdencia/pt-br/assuntos/rpps/documentos/PortariaInterministerialMPSMF13de9dejaneirode2026.pdf"
INSS_NEWS_URL = "https://www.gov.br/inss/pt-br/assuntos/com-reajuste-de-3-9-teto-do-inss-chega-a-r-8-475-55-em-2026"


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


def fetch_inss_employee_brackets() -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    effective_from = date(2026, 1, 1)

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


def fetch_inss_employee_brackets_from_pdf() -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    effective_from = date(2026, 1, 1)
    r = requests.get(INSS_PDF_URL, timeout=60)
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


def fetch_inss_employee_brackets_from_news() -> tuple[date, list[tuple[Decimal | None, Decimal]]]:
    """Fallback mais robusto: notícia oficial do INSS costuma trazer as faixas e alíquotas em texto.

    Exemplo (jan/2026):
    • 7,5% para quem ganha até R$ 1.621,00;
    • 9% para quem ganha entre R$ 1.621,01 e R$ 2.902,84;
    • 12% para quem ganha entre R$ 2.902,85 e R$ 4.354,27;
    • 14% para quem ganha de R$ 4.354,28 até R$ 8.475,55.
    """

    effective_from = date(2026, 1, 1)
    r = requests.get(INSS_NEWS_URL, timeout=30)
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


def fetch_irrf_monthly_table() -> tuple[date, Decimal, list[tuple[Decimal | None, Decimal, Decimal]]]:
    r = requests.get(IRRF_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    effective_from = date(2026, 1, 1)

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

    return effective_from, dep_ded, rows


def register_commands(app: Flask) -> None:
    @app.cli.command("sync-taxes")
    @click.option("--apply", "apply_changes", is_flag=True)
    def sync_taxes(apply_changes: bool) -> None:
        inss_eff = None
        inss_rows: list[tuple[Decimal | None, Decimal]] = []
        irrf_eff = None
        dep_ded = None
        irrf_rows: list[tuple[Decimal | None, Decimal, Decimal]] = []

        inss_source = None
        irrf_source = None

        inss_error = None
        irrf_error = None

        try:
            inss_eff, inss_rows = fetch_inss_employee_brackets()
            if len(inss_rows) < 3:
                raise RuntimeError(f"Extração INSS retornou poucas faixas ({len(inss_rows)}).")
            inss_source = "html"
        except Exception as e:
            inss_error = str(e)
            try:
                inss_eff, inss_rows = fetch_inss_employee_brackets_from_news()
                inss_source = "news"
            except Exception as e2:
                try:
                    inss_eff, inss_rows = fetch_inss_employee_brackets_from_pdf()
                    inss_source = "pdf"
                except Exception as e3:
                    inss_error = f"{inss_error} | Fallback notícia falhou: {e2} | Fallback PDF falhou: {e3}"

        try:
            irrf_eff, dep_ded, irrf_rows = fetch_irrf_monthly_table()
            irrf_source = "html"
        except Exception as e:
            irrf_error = str(e)

        click.echo("INSS (empregado):")
        if inss_source:
            click.echo(f"Fonte utilizada: {inss_source}")
        click.echo(f"Fonte HTML: {INSS_URL}")
        click.echo(f"Fonte notícia (INSS): {INSS_NEWS_URL}")
        click.echo(f"Fonte PDF (Portaria): {INSS_PDF_URL}")
        if inss_rows and inss_eff:
            click.echo(f"Vigência sugerida: {inss_eff.isoformat()}")
            for up_to, rate in inss_rows:
                click.echo(f" - até={up_to if up_to is not None else '—'} | aliquota={rate}")
        else:
            click.echo(f"ERRO ao extrair INSS: {inss_error}")

        click.echo("")
        click.echo("IRRF (mensal):")
        if irrf_source:
            click.echo(f"Fonte utilizada: {irrf_source}")
        click.echo(IRRF_URL)
        if irrf_rows and irrf_eff and dep_ded is not None:
            click.echo(f"Vigência sugerida: {irrf_eff.isoformat()}")
            click.echo(f"Dedução por dependente: {dep_ded}")
            for up_to, rate, ded in irrf_rows:
                click.echo(f" - até={up_to if up_to is not None else '—'} | aliquota={rate} | deduzir={ded}")
        else:
            click.echo(f"ERRO ao extrair IRRF: {irrf_error}")

        if not apply_changes:
            click.echo("")
            click.echo("DRY-RUN: nada foi gravado. Para gravar, execute novamente com --apply.")
            return

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
        click.echo("OK: tabelas gravadas no banco.")
