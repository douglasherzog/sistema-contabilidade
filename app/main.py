from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, render_template, request, url_for
from flask_login import login_required, current_user

from .extensions import db
from .models import (
    CompetenceClose,
    EmployeeVacation,
    GuideDocument,
    PayrollRun,
    RevenueNote,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)


main_bp = Blueprint("main", __name__)


def _competence_start(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _latest_inss_effective(effective_date: date):
    return (
        db.session.query(TaxInssBracket.effective_from)
        .filter(TaxInssBracket.effective_from <= effective_date)
        .order_by(TaxInssBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )


def _latest_irrf_effective(effective_date: date):
    return (
        db.session.query(TaxIrrfBracket.effective_from)
        .filter(TaxIrrfBracket.effective_from <= effective_date)
        .order_by(TaxIrrfBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )


@main_bp.get("/")
@login_required
def index():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    if year < 2000:
        year = now.year
    if month < 1 or month > 12:
        month = now.month

    comp = _competence_start(year, month)
    run = PayrollRun.query.filter_by(year=year, month=month).first()
    revenue_count = RevenueNote.query.filter_by(year=year, month=month).count()

    inss_eff = _latest_inss_effective(comp)
    irrf_eff = _latest_irrf_effective(comp)
    irrf_cfg = (
        TaxIrrfConfig.query.filter(TaxIrrfConfig.effective_from <= comp)
        .order_by(TaxIrrfConfig.effective_from.desc())
        .first()
    )

    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }

    # Vacations summary for the month
    vac_rows = EmployeeVacation.query.filter_by(year=year, month=month).all()
    vac_count = len(vac_rows)
    vac_total = sum([Decimal(str(r.gross_total or 0)) for r in vac_rows], Decimal("0")).quantize(Decimal("0.01"))

    closed = CompetenceClose.query.filter_by(year=year, month=month).first()

    status = {
        "competence": {
            "year": year,
            "month": month,
            "closed": bool(closed),
        },
        "revenue": {
            "ok": revenue_count > 0,
            "count": revenue_count,
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
        },
        "payroll": {
            "ok": bool(run),
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
        },
        "taxes": {
            "ok": bool(inss_eff) and bool(irrf_eff) and bool(irrf_cfg),
            "inss_eff": inss_eff,
            "irrf_eff": irrf_eff,
            "action_url": url_for("payroll.tax_config"),
        },
        "guides": {
            "ok": all(bool(docs.get(k)) for k in ("darf", "das", "fgts")),
            "docs": docs,
            "action_url": url_for("payroll.close_home", year=year, month=month),
        },
        "vacations": {
            "ok": True,  # Always OK since no vacations is valid state
            "count": vac_count,
            "total_gross": vac_total,
            "action_url": url_for("payroll.employees"),
        },
        "close": {
            "ok": bool(closed),
            "action_url": url_for("payroll.close_home", year=year, month=month),
        },
    }

    next_step = None
    if not status["revenue"]["ok"]:
        next_step = {
            "title": "Registrar receitas do mês",
            "help": "Comece registrando as notas/receitas. Isso ajuda relatórios e o cálculo do Fator R.",
            "url": status["revenue"]["action_url"],
            "label": "Abrir Receitas",
        }
    elif not status["payroll"]["ok"]:
        next_step = {
            "title": "Criar/abrir a folha do mês",
            "help": "Crie a folha para lançar horas extras, gerar holerites e conferir totais.",
            "url": status["payroll"]["action_url"],
            "label": "Abrir Folha",
        }
    elif not status["taxes"]["ok"]:
        next_step = {
            "title": "Configurar tabelas de INSS/IRRF",
            "help": "Sem tabelas, o sistema não consegue estimar descontos. Configure para conferência.",
            "url": status["taxes"]["action_url"],
            "label": "Config INSS/IRRF",
        }
    elif not status["guides"]["ok"]:
        next_step = {
            "title": "Registrar/anexar guias do mês",
            "help": "Centralize DAS/FGTS/DARF para conferir antes de pagar.",
            "url": status["guides"]["action_url"],
            "label": "Abrir Fechamento",
        }
    elif not status["close"]["ok"]:
        next_step = {
            "title": "Marcar competência como fechada",
            "help": "Quando estiver tudo conferido, marque como fechada para organização (com aviso).",
            "url": status["close"]["action_url"],
            "label": "Abrir Fechamento",
        }
    else:
        next_step = {
            "title": "Tudo certo",
            "help": "A competência parece completa. Se precisar, revise as guias e confira os valores.",
            "url": status["close"]["action_url"],
            "label": "Revisar Fechamento",
        }

    return render_template(
        "index.html",
        user=current_user,
        year=year,
        month=month,
        status=status,
        next_step=next_step,
    )
