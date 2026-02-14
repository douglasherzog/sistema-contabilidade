from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename

from .extensions import db
from .models import (
    CompetenceClose,
    Employee,
    EmployeeDependent,
    EmployeeLeave,
    EmployeeSalary,
    EmployeeTermination,
    EmployeeThirteenth,
    EmployeeVacation,
    GuideDocument,
    RevenueNote,
    PayrollLine,
    PayrollRun,
    TaxInssBracket,
    TaxIrrfBracket,
    TaxIrrfConfig,
)
from .tax_sync import run_compliance_check, run_tax_sync


payroll_bp = Blueprint("payroll", __name__, url_prefix="/payroll")


TUTORIALS: dict[str, dict] = {
    "painel": {
        "title": "Painel do mês (Início)",
        "goal": "Entender o que fazer primeiro na competência e quais pendências existem.",
        "first_step": "Confira o card 'Próximo passo sugerido' e clique no botão indicado.",
        "fields": [
            {"name": "Ano", "explain": "Competência que você quer revisar (ex.: 2026)."},
            {"name": "Mês", "explain": "Mês da competência (1 a 12)."},
        ],
        "steps": [
            "Abra a competência correta no topo da tela.",
            "Siga a ordem sugerida pelo sistema: Receitas -> Folha -> Tabelas -> Fechamento.",
            "Use os cards de Férias/13º/Rescisões/Afastamentos para registrar eventos do mês.",
        ],
    },
    "modo_guiado": {
        "title": "Modo Guiado do Mês",
        "goal": "Executar a competência na ordem correta, sem esquecer etapas.",
        "first_step": "Abra o mês/ano e siga o 'Próximo passo' indicado pelo sistema.",
        "fields": [
            {"name": "Ano e mês", "explain": "Competência que você quer concluir."},
            {"name": "Checklist por etapa", "explain": "Mostra o que já foi feito e o que está pendente."},
            {"name": "Próximo passo", "explain": "Botão direto para a próxima tela recomendada."},
        ],
        "steps": [
            "Cadastre/atualize funcionários e dados base.",
            "Registre receitas do mês.",
            "Abra e salve a folha mensal.",
            "Confira tabelas INSS/IRRF.",
            "Anexe guias (DARF/DAS/FGTS).",
            "Só então marque competência como fechada.",
        ],
    },
    "funcionarios": {
        "title": "Funcionários",
        "goal": "Cadastrar e organizar funcionários que entram na folha.",
        "first_step": "Cadastre o funcionário antes de tentar lançar folha, férias ou 13º.",
        "fields": [
            {"name": "Nome", "explain": "Nome completo do funcionário."},
            {"name": "CPF", "explain": "Opcional, mas recomendado para conferência."},
            {"name": "Admissão", "explain": "Data de contratação (dd/mm/aaaa)."},
        ],
        "steps": [
            "Clique em 'Cadastrar funcionário'.",
            "Abra o funcionário e cadastre salário por vigência.",
            "Cadastre dependentes para cálculo de IRRF.",
        ],
    },
    "funcionario": {
        "title": "Detalhe do funcionário",
        "goal": "Centralizar dados do funcionário e acessar módulos trabalhistas.",
        "first_step": "Cadastre salário vigente antes de registrar eventos (férias/13º/rescisão).",
        "fields": [
            {"name": "Vigência do salário", "explain": "Data a partir da qual o salário base vale."},
            {"name": "Salário base", "explain": "Valor mensal bruto do funcionário."},
            {"name": "Dependentes", "explain": "Usado para dedução de IRRF."},
        ],
        "steps": [
            "Atualize salário sempre que houver reajuste.",
            "Use os botões de Férias, 13º, Rescisão e Afastamentos para registros legais.",
        ],
    },
    "folha_home": {
        "title": "Folha (abertura da competência)",
        "goal": "Criar ou abrir a folha mensal.",
        "first_step": "Selecione ano/mês e clique em 'Abrir folha'.",
        "fields": [
            {"name": "Ano e Mês", "explain": "Competência da folha."},
        ],
        "steps": [
            "Se já existir folha, o sistema abre para edição.",
            "Se não existir, cria automaticamente com funcionários ativos.",
        ],
    },
    "folha_edicao": {
        "title": "Folha (edição)",
        "goal": "Lançar horas extras e gerar holerites.",
        "first_step": "Preencha jornada semanal e adicional; depois informe as horas extras por funcionário.",
        "fields": [
            {"name": "Jornada semanal", "explain": "Carga horária contratual da competência (ex.: 44,00)."},
            {"name": "Adicional hora extra", "explain": "Percentual aplicado sobre a hora normal (ex.: 50,00)."},
            {"name": "Horas extras por funcionário", "explain": "Quantidade no mês (aceita decimal)."},
        ],
        "steps": [
            "Informe jornada semanal e adicional no topo da tela.",
            "Preencha as horas extras por funcionário.",
            "Clique em salvar para recalcular automaticamente valor/hora extra, total bruto e holerite.",
        ],
    },
    "ferias": {
        "title": "Férias",
        "goal": "Registrar férias e abono com cálculo didático para conferência.",
        "first_step": "Abra a competência do pagamento e informe início/gozo corretamente.",
        "fields": [
            {"name": "Início do gozo", "explain": "Data que inicia o período de férias."},
            {"name": "Data do pagamento", "explain": "Opcional, mas importante para compliance."},
            {"name": "Dias de gozo", "explain": "Quantidade de dias de férias usufruídos."},
            {"name": "Dias vendidos", "explain": "Abono pecuniário (0 a 10 dias)."},
        ],
        "steps": [
            "Registre férias respeitando limite de 30 dias totais (gozo + venda).",
            "Abra o recibo e confira valores e estimativas.",
            "Veja o impacto no Fechamento do mês.",
        ],
    },
    "decimo": {
        "title": "13º salário",
        "goal": "Registrar parcelas do 13º conforme CLT.",
        "first_step": "Defina tipo correto (1ª, 2ª ou integral) e meses trabalhados.",
        "fields": [
            {"name": "Ano de referência", "explain": "Ano-base do 13º."},
            {"name": "Data do pagamento", "explain": "Data efetiva do pagamento."},
            {"name": "Meses trabalhados", "explain": "Proporcionalidade (1 a 12)."},
            {"name": "Tipo", "explain": "1ª parcela, 2ª parcela ou integral."},
        ],
        "steps": [
            "1ª parcela preferencialmente em novembro.",
            "2ª parcela até 20/12 (com descontos).",
            "Valide avisos CLT no recibo.",
        ],
    },
    "rescisao": {
        "title": "Rescisão",
        "goal": "Registrar desligamento com aviso prévio e conferência de multa FGTS.",
        "first_step": "Escolha o tipo de rescisão correto e informe aviso prévio.",
        "fields": [
            {"name": "Data da rescisão", "explain": "Data oficial de desligamento."},
            {"name": "Tipo", "explain": "Sem justa causa, com justa causa, acordo ou pedido de demissão."},
            {"name": "Aviso prévio / dias", "explain": "Se foi trabalhado, indenizado ou não aplicável."},
            {"name": "Saldo FGTS estimado", "explain": "Base para cálculo de multa FGTS."},
            {"name": "Alíquota multa FGTS", "explain": "40% sem justa causa, 20% acordo, 0% demais casos (regra simplificada)."},
        ],
        "steps": [
            "Preencha os dados e salve a rescisão.",
            "Abra o recibo e siga o checklist guiado (TRCT, FGTS, etc.).",
            "Confira alertas no compliance-check.",
        ],
    },
    "afastamentos": {
        "title": "Afastamentos",
        "goal": "Registrar atestados/licenças e validar regras básicas.",
        "first_step": "Informe período completo (início e fim) sem inversão de datas.",
        "fields": [
            {"name": "Tipo", "explain": "Médico, maternidade, acidente, não remunerada, outro."},
            {"name": "Início / Fim", "explain": "Período do afastamento."},
            {"name": "Pagamento", "explain": "Empresa, INSS ou misto."},
        ],
        "steps": [
            "Registre o afastamento por competência.",
            "Para afastamento médico >15 dias, prefira INSS/misto quando aplicável.",
        ],
    },
    "receitas": {
        "title": "Receitas / Notas",
        "goal": "Registrar faturamento mensal para conferência e fechamento.",
        "first_step": "Abra a competência e cadastre cada nota/receita do mês.",
        "fields": [
            {"name": "Data", "explain": "Data da nota (opcional)."},
            {"name": "Cliente", "explain": "Nome do cliente (opcional)."},
            {"name": "Descrição", "explain": "Resumo do serviço."},
            {"name": "Valor", "explain": "Valor bruto da receita."},
        ],
        "steps": [
            "Registre todas as receitas do mês.",
            "Confira total no resumo da tela.",
            "Valide no Fechamento se o item de receitas ficou OK.",
        ],
    },
    "fechamento": {
        "title": "Fechamento",
        "goal": "Conferir checklist completo antes de encerrar competência.",
        "first_step": "Revise os cards pendentes e abra cada ação sugerida.",
        "fields": [
            {"name": "Checklist guiado", "explain": "Mostra o que falta por área e direciona para a tela certa."},
            {"name": "Resumo do mês", "explain": "Conferência final dos totais estimados."},
        ],
        "steps": [
            "Verifique receitas, folha, tabelas, eventos trabalhistas e guias.",
            "Só depois marque competência como fechada.",
        ],
    },
    "tabelas": {
        "title": "Config INSS/IRRF",
        "goal": "Manter tabelas fiscais para cálculos estimados consistentes.",
        "first_step": "Atualize vigências e faixas do ano corrente antes de fechar competência.",
        "fields": [
            {"name": "Vigência", "explain": "Data de início da tabela."},
            {"name": "Faixa até", "explain": "Limite superior da faixa (vazio = última faixa)."},
            {"name": "Alíquota", "explain": "Percentual em decimal (ex.: 0,075)."},
            {"name": "Dedução IRRF", "explain": "Dedução por dependente e parcela a deduzir."},
        ],
        "steps": [
            "Use o bloco 'Sincronização oficial' para executar dry-run e aplicar tabelas diretamente na tela.",
            "Se necessário, ajuste manualmente e reconfira no holerite/fechamento.",
        ],
    },
}


@payroll_bp.get("/help")
@login_required
def help_index():
    return render_template("payroll/help_index.html", tutorials=TUTORIALS)


@payroll_bp.get("/help/<slug>")
@login_required
def help_page(slug: str):
    item = TUTORIALS.get(slug)
    if not item:
        flash("Tutorial não encontrado.", "warning")
        return redirect(url_for("payroll.help_index"))
    return render_template("payroll/help_page.html", slug=slug, item=item)


def _guide_step_keys() -> set[str]:
    return {"employees", "revenue", "payroll", "taxes", "guides", "close"}


def _guide_session_key(year: int, month: int) -> str:
    return f"payroll_guide_done:{int(year)}-{int(month)}"


@payroll_bp.post("/guide/step")
@login_required
def monthly_guide_step_toggle():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    step_key = (request.form.get("step_key") or "").strip().lower()
    action = (request.form.get("action") or "").strip().lower()

    if year < 2000 or month < 1 or month > 12 or step_key not in _guide_step_keys() or action not in {"done", "undone"}:
        flash("Ação do modo guiado inválida.", "warning")
        return redirect(url_for("payroll.monthly_guide"))

    s_key = _guide_session_key(year, month)
    done = set(session.get(s_key, []))

    if action == "done":
        done.add(step_key)
    elif step_key in done:
        done.remove(step_key)

    session[s_key] = sorted(done)
    flash("Progresso do modo guiado atualizado.", "success")
    return redirect(url_for("payroll.monthly_guide", year=year, month=month))


@payroll_bp.post("/guide/reset")
@login_required
def monthly_guide_reset():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.monthly_guide"))

    session.pop(_guide_session_key(year, month), None)
    flash("Marcação manual do modo guiado foi resetada para esta competência.", "success")
    return redirect(url_for("payroll.monthly_guide", year=year, month=month))


@payroll_bp.get("/guide")
@login_required
def monthly_guide():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    comp = date(int(year), int(month), 1)
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    closed = CompetenceClose.query.filter_by(year=year, month=month).first()

    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }

    employees_count = Employee.query.count()
    active_employees_count = Employee.query.filter_by(active=True).count()
    revenue_summary = _calc_revenue_month_summary(year, month)
    vacations_summary = _calc_vacations_month_summary(year, month)
    thirteenth_summary = _calc_thirteenth_month_summary(year, month)
    terminations_summary = _calc_terminations_month_summary(year, month)
    leaves_summary = _calc_leaves_month_summary(year, month)

    steps = [
        {
            "key": "employees",
            "title": "1) Base de funcionários",
            "auto_done": employees_count > 0 and active_employees_count > 0,
            "desc": "Tenha pelo menos 1 funcionário ativo com dados cadastrais e salário em dia.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Abrir funcionários",
        },
        {
            "key": "revenue",
            "title": "2) Receitas da competência",
            "auto_done": bool(revenue_summary.get("count")),
            "desc": "Registre as notas/receitas do mês para conferência financeira.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Lançar receitas",
        },
        {
            "key": "payroll",
            "title": "3) Folha mensal",
            "auto_done": bool(run),
            "desc": "Crie/abra a folha do mês e salve os lançamentos de horas extras.",
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
            "action_label": "Abrir folha",
        },
        {
            "key": "taxes",
            "title": "4) Tabelas INSS/IRRF",
            "auto_done": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "desc": "Confirme as tabelas fiscais vigentes para estimativas coerentes.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Conferir tabelas",
        },
        {
            "key": "guides",
            "title": "5) Guias da competência",
            "auto_done": all(bool(docs.get(k)) for k in ("darf", "das", "fgts")),
            "desc": "Anexe os PDFs de DARF, DAS e FGTS para centralizar conferência.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
        {
            "key": "close",
            "title": "6) Encerramento do mês",
            "auto_done": bool(closed),
            "desc": "Depois de tudo conferido, marque a competência como fechada.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Ir para fechamento",
        },
    ]

    reviewed_steps = set(session.get(_guide_session_key(year, month), []))
    for s in steps:
        s["manual_done"] = s["key"] in reviewed_steps
        s["done"] = bool(s.get("auto_done")) or bool(s.get("manual_done"))

    total_steps = len(steps)
    done_steps = sum(1 for s in steps if s.get("done"))
    progress_pct = int((done_steps * 100) / total_steps) if total_steps else 0

    next_step = next((s for s in steps if not s.get("done")), None)

    return render_template(
        "payroll/monthly_guide.html",
        year=year,
        month=month,
        steps=steps,
        next_step=next_step,
        total_steps=total_steps,
        done_steps=done_steps,
        progress_pct=progress_pct,
        employees_count=employees_count,
        active_employees_count=active_employees_count,
        revenue_summary=revenue_summary,
        vacations_summary=vacations_summary,
        thirteenth_summary=thirteenth_summary,
        terminations_summary=terminations_summary,
        leaves_summary=leaves_summary,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
    )


def _to_decimal(v: str | None, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        s = s.replace(".", "").replace(",", ".") if "," in s else s
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default


def _monthly_hours_from_weekly(weekly_hours: Decimal | None) -> Decimal:
    weekly = Decimal(str(weekly_hours or 0))
    if weekly <= 0:
        weekly = Decimal("44")
    return (weekly * Decimal("5")).quantize(Decimal("0.01"))


def _overtime_rate_from_salary(base_salary: Decimal | None, weekly_hours: Decimal | None, additional_pct: Decimal | None) -> Decimal:
    base = Decimal(str(base_salary or 0))
    month_hours = _monthly_hours_from_weekly(weekly_hours)
    additional = Decimal(str(additional_pct or 0))
    if additional < 0:
        additional = Decimal("0")
    if base <= 0 or month_hours <= 0:
        return Decimal("0")
    multiplier = Decimal("1") + (additional / Decimal("100"))
    return ((base / month_hours) * multiplier).quantize(Decimal("0.01"))


def _parse_date(v: str | None) -> date | None:
    s = (v or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        pass
    try:
        parts = s.split("/")
        if len(parts) != 3:
            return None
        dd, mm, yyyy = (p.strip() for p in parts)
        if len(yyyy) == 2:
            yyyy = "20" + yyyy
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None


def _media_guides_dir() -> str:
    p = os.path.join(current_app.instance_path, "media", "guides")
    os.makedirs(p, exist_ok=True)
    return p


def _competence_start(year: int, month: int) -> date:
    return date(int(year), int(month), 1)


def _competence_is_closed(year: int, month: int) -> bool:
    return CompetenceClose.query.filter_by(year=int(year), month=int(month)).first() is not None


def _calc_revenue_month_summary(year: int, month: int) -> dict:
    notes = RevenueNote.query.filter_by(year=int(year), month=int(month)).all()
    total = Decimal("0")
    for n in notes:
        try:
            total += Decimal(str(n.amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(notes),
        "total": total,
    }


def _calc_vacation_amounts(base_salary: Decimal, days: int, sell_days: int) -> dict:
    # Fixed-salary version (no averages). Uses 30-day base.
    d = max(0, int(days or 0))
    s = max(0, int(sell_days or 0))
    daily = (base_salary / Decimal("30")) if base_salary > 0 else Decimal("0")
    vacation_pay = (daily * Decimal(str(d))).quantize(Decimal("0.01"))
    vacation_one_third = (vacation_pay / Decimal("3")).quantize(Decimal("0.01"))
    abono_pay = (daily * Decimal(str(s))).quantize(Decimal("0.01"))
    abono_one_third = (abono_pay / Decimal("3")).quantize(Decimal("0.01"))
    gross_total = (vacation_pay + vacation_one_third + abono_pay + abono_one_third).quantize(Decimal("0.01"))
    return {
        "daily": daily.quantize(Decimal("0.0001")) if daily else Decimal("0"),
        "vacation_pay": vacation_pay,
        "vacation_one_third": vacation_one_third,
        "abono_pay": abono_pay,
        "abono_one_third": abono_one_third,
        "gross_total": gross_total,
    }


def _calc_vacations_month_summary(year: int, month: int) -> dict:
    rows = EmployeeVacation.query.filter_by(year=int(year), month=int(month)).all()
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.gross_total or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(rows),
        "total_gross": total,
    }


def _calc_terminations_month_summary(year: int, month: int) -> dict:
    rows = EmployeeTermination.query.filter_by(year=int(year), month=int(month)).all()
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.gross_total or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(rows),
        "total_gross": total,
    }


def _calc_leaves_month_summary(year: int, month: int) -> dict:
    rows = EmployeeLeave.query.filter_by(year=int(year), month=int(month)).all()
    return {
        "count": len(rows),
    }


def _salary_for_employee(employee: Employee, year: int, month: int) -> Decimal:
    comp = _competence_start(year, month)
    s = (
        EmployeeSalary.query.filter(EmployeeSalary.employee_id == employee.id)
        .filter(EmployeeSalary.effective_from <= comp)
        .order_by(EmployeeSalary.effective_from.desc())
        .first()
    )
    if not s:
        return Decimal("0")
    try:
        return Decimal(str(s.base_salary))
    except Exception:
        return Decimal("0")


def _latest_inss_brackets(effective_date: date):
    eff = (
        db.session.query(TaxInssBracket.effective_from)
        .filter(TaxInssBracket.effective_from <= effective_date)
        .order_by(TaxInssBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )
    if not eff:
        return None, []
    rows = TaxInssBracket.query.filter_by(effective_from=eff).order_by(TaxInssBracket.up_to.asc().nullslast()).all()
    return eff, rows


def _latest_irrf_config(effective_date: date):
    return (
        TaxIrrfConfig.query.filter(TaxIrrfConfig.effective_from <= effective_date)
        .order_by(TaxIrrfConfig.effective_from.desc())
        .first()
    )


def _latest_irrf_brackets(effective_date: date):
    eff = (
        db.session.query(TaxIrrfBracket.effective_from)
        .filter(TaxIrrfBracket.effective_from <= effective_date)
        .order_by(TaxIrrfBracket.effective_from.desc())
        .limit(1)
        .scalar()
    )
    if not eff:
        return None, []
    rows = TaxIrrfBracket.query.filter_by(effective_from=eff).order_by(TaxIrrfBracket.up_to.asc().nullslast()).all()
    return eff, rows


def _calc_inss_progressive(base: Decimal, brackets: list[TaxInssBracket]) -> Decimal:
    if base <= 0:
        return Decimal("0")
    remaining = base
    prev = Decimal("0")
    total = Decimal("0")
    for b in brackets:
        up_to = Decimal(str(b.up_to)) if b.up_to is not None else None
        rate = Decimal(str(b.rate or 0))
        if rate <= 0:
            continue
        if up_to is None:
            taxable = max(Decimal("0"), remaining)
        else:
            taxable = max(Decimal("0"), min(base, up_to) - prev)
        if taxable > 0:
            total += (taxable * rate)
        if up_to is not None:
            prev = up_to
        if base <= prev:
            break
    return total.quantize(Decimal("0.01"))


def _calc_irrf(base: Decimal, cfg: TaxIrrfConfig | None, brackets: list[TaxIrrfBracket], dependents_count: int) -> Decimal:
    if base <= 0:
        return Decimal("0")
    dep_ded = Decimal(str(getattr(cfg, "dependent_deduction", 0) or 0)) if cfg else Decimal("0")
    calc_base = base - (dep_ded * Decimal(str(dependents_count or 0)))
    if calc_base <= 0:
        return Decimal("0")

    # IRRF (mensal) tipicamente é por faixa com "parcela a deduzir" (não progressivo no cálculo final).
    chosen = None
    for b in brackets:
        up_to = Decimal(str(b.up_to)) if b.up_to is not None else None
        if up_to is None or calc_base <= up_to:
            chosen = b
            break
    if not chosen:
        return Decimal("0")
    rate = Decimal(str(chosen.rate or 0))
    ded = Decimal(str(chosen.deduction or 0))
    val = (calc_base * rate) - ded
    if val < 0:
        val = Decimal("0")
    return val.quantize(Decimal("0.01"))


def _calc_month_summary(run: PayrollRun | None) -> dict | None:
    if not run:
        return None

    comp = date(int(run.year), int(run.month), 1)
    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()

    total_gross = Decimal("0")
    total_inss = Decimal("0")
    total_irrf = Decimal("0")

    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    for ln in lines:
        gross = (Decimal(str(ln.gross_total or 0)) if ln.gross_total is not None else Decimal("0"))
        total_gross += gross

        deps_count = EmployeeDependent.query.filter_by(employee_id=ln.employee_id).count()
        inss_est = Decimal("0")
        if inss_rows:
            inss_est = _calc_inss_progressive(gross, inss_rows)
        total_inss += inss_est

        irrf_est = Decimal("0")
        if irrf_rows and irrf_cfg:
            irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
        total_irrf += irrf_est

    total_gross = total_gross.quantize(Decimal("0.01"))
    total_inss = total_inss.quantize(Decimal("0.01"))
    total_irrf = total_irrf.quantize(Decimal("0.01"))
    total_net = (total_gross - total_inss - total_irrf).quantize(Decimal("0.01"))

    return {
        "year": int(run.year),
        "month": int(run.month),
        "employees_count": len(lines),
        "total_gross": total_gross,
        "total_inss_est": (total_inss if inss_rows else None),
        "total_irrf_est": (total_irrf if (irrf_rows and irrf_cfg) else None),
        "total_net_est": (total_net if (inss_rows and irrf_rows and irrf_cfg) else None),
        "inss_eff": inss_eff,
        "irrf_eff": irrf_eff,
        "has_tables": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
    }


@payroll_bp.get("/employees")
@login_required
def employees():
    items = Employee.query.order_by(Employee.active.desc(), Employee.full_name.asc()).all()
    return render_template("payroll/employees.html", items=items)


@payroll_bp.post("/employees")
@login_required
def employees_create():
    full_name = (request.form.get("full_name") or "").strip()
    cpf = (request.form.get("cpf") or "").strip() or None
    hired_at_raw = (request.form.get("hired_at") or "").strip()
    hired_at = _parse_date(hired_at_raw)

    if not full_name:
        flash("Informe o nome do funcionário.", "warning")
        return redirect(url_for("payroll.employees"))

    e = Employee(full_name=full_name, cpf=cpf, hired_at=hired_at)
    db.session.add(e)
    db.session.commit()
    flash("Funcionário cadastrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.get("/employees/<int:employee_id>")
@login_required
def employee_detail(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    deps = EmployeeDependent.query.filter_by(employee_id=e.id).order_by(EmployeeDependent.id.desc()).all()
    salaries = EmployeeSalary.query.filter_by(employee_id=e.id).order_by(EmployeeSalary.effective_from.desc()).all()
    return render_template("payroll/employee_detail.html", e=e, deps=deps, salaries=salaries)


@payroll_bp.get("/employees/<int:employee_id>/vacations")
@login_required
def employee_vacations(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = EmployeeVacation.query.filter_by(employee_id=e.id).order_by(EmployeeVacation.year.desc(), EmployeeVacation.month.desc(), EmployeeVacation.start_date.desc()).all()
    return render_template(
        "payroll/employee_vacations.html",
        e=e,
        year=year,
        month=month,
        rows=rows,
    )


@payroll_bp.post("/employees/<int:employee_id>/vacations")
@login_required
def employee_vacations_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    start_date = _parse_date(request.form.get("start_date"))
    pay_date = _parse_date(request.form.get("pay_date"))
    days = int(request.form.get("days") or 0)
    sell_days = int(request.form.get("sell_days") or 0)

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id))
    if not start_date:
        flash("Informe a data de início das férias.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))

    if days <= 0 or days > 30:
        flash("Dias de gozo inválidos (1 a 30).", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))
    if sell_days < 0 or sell_days > 10:
        flash("Dias vendidos inválidos (0 a 10).", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))
    if days + sell_days > 30:
        flash("Gozo + venda não pode ultrapassar 30 dias.", "warning")
        return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))

    base_salary = _salary_for_employee(e, year, month)
    amounts = _calc_vacation_amounts(base_salary, days, sell_days)

    # Estimate discounts using the same tax tables (didactic, not official).
    comp = _competence_start(year, month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    net_est = None
    gross = amounts["gross_total"]
    if inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross - inss_est - irrf_est).quantize(Decimal("0.01"))

    row = EmployeeVacation(
        employee_id=e.id,
        year=year,
        month=month,
        start_date=start_date,
        days=days,
        sell_days=sell_days,
        pay_date=pay_date,
        base_salary_at_calc=base_salary,
        vacation_pay=amounts["vacation_pay"],
        vacation_one_third=amounts["vacation_one_third"],
        abono_pay=amounts["abono_pay"],
        abono_one_third=amounts["abono_one_third"],
        gross_total=amounts["gross_total"],
        inss_est=(inss_est if inss_est is not None else None),
        irrf_est=(irrf_est if irrf_est is not None else None),
        net_est=(net_est if net_est is not None else None),
    )
    db.session.add(row)
    db.session.commit()
    flash("Férias registradas.", "success")
    return redirect(url_for("payroll.employee_vacations", employee_id=e.id, year=year, month=month))


@payroll_bp.get("/vacations/<int:vac_id>/receipt")
@login_required
def vacation_receipt(vac_id: int):
    v = EmployeeVacation.query.get_or_404(vac_id)

    comp = _competence_start(int(v.year), int(v.month))
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    return render_template(
        "payroll/vacation_receipt.html",
        v=v,
        employee=v.employee,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        has_tables=bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
    )


# =============================================================================
# 13º SALÁRIO (DECIMO TERCEIRO) - Conforme CLT
# =============================================================================

def _calc_thirteenth_amount(base_salary: Decimal, months_worked: int) -> dict:
    """Cálculo CLT: (salário / 12) × meses trabalhados."""
    m = max(1, min(12, int(months_worked or 12)))
    monthly_part = (base_salary / Decimal("12")).quantize(Decimal("0.01"))
    gross = (monthly_part * Decimal(str(m))).quantize(Decimal("0.01"))
    return {
        "monthly_part": monthly_part,
        "months_worked": m,
        "gross_amount": gross,
    }


def _termination_expected_fgts_rate(termination_type: str) -> Decimal:
    t = (termination_type or "").strip().lower()
    if t == "without_cause":
        return Decimal("0.40")
    if t == "agreement":
        return Decimal("0.20")
    return Decimal("0")


def _termination_guided_checklist(termination_type: str, notice_type: str) -> list[str]:
    t = (termination_type or "").strip().lower()
    n = (notice_type or "").strip().lower()
    items: list[str] = [
        "Conferir saldo de salário e férias (vencidas/proporcionais + 1/3).",
        "Emitir TRCT e termo de quitação para assinatura.",
        "Conferir lançamentos de eSocial/SEFIP/FGTS Digital conforme competência.",
    ]
    if t in ("without_cause", "agreement"):
        if n == "none":
            items.append("Definir aviso prévio (trabalhado ou indenizado) conforme CLT.")
        else:
            items.append(f"Aviso prévio informado: {n}.")
    if t == "without_cause":
        items.append("Aplicar multa de 40% do FGTS (quando houver saldo).")
        items.append("Gerar chave de conectividade e avaliar seguro-desemprego.")
    elif t == "agreement":
        items.append("Aplicar multa de 20% do FGTS (rescisão por acordo).")
    elif t == "with_cause":
        items.append("Sem aviso indenizado e sem multa FGTS (justa causa).")
    elif t == "resignation":
        items.append("Pedido de demissão: validar aviso prévio conforme política aplicável.")
    return items


def _calc_thirteenth_month_summary(year: int, month: int) -> dict:
    """Resumo de 13º registrados na competência."""
    rows = EmployeeThirteenth.query.filter_by(payment_year=int(year), payment_month=int(month)).all()
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.gross_amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))
    return {
        "count": len(rows),
        "total_gross": total,
    }


@payroll_bp.get("/employees/<int:employee_id>/thirteenth")
@login_required
def employee_thirteenth(employee_id: int):
    """Tela de gestão do 13º salário por funcionário."""
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = EmployeeThirteenth.query.filter_by(employee_id=e.id).order_by(
        EmployeeThirteenth.reference_year.desc(),
        EmployeeThirteenth.payment_year.desc(),
        EmployeeThirteenth.payment_month.desc(),
    ).all()
    return render_template(
        "payroll/employee_thirteenth.html",
        e=e,
        year=year,
        month=month,
        rows=rows,
    )


@payroll_bp.post("/employees/<int:employee_id>/thirteenth")
@login_required
def employee_thirteenth_add(employee_id: int):
    """Cadastra pagamento de 13º (1ª parcela, 2ª parcela ou integral)."""
    e = Employee.query.get_or_404(employee_id)
    ref_year = int(request.form.get("reference_year") or 0)
    pay_year = int(request.form.get("payment_year") or 0)
    pay_month = int(request.form.get("payment_month") or 0)
    pay_date = _parse_date(request.form.get("pay_date"))
    months_worked = int(request.form.get("months_worked") or 12)
    payment_type = (request.form.get("payment_type") or "").strip().lower()

    if ref_year < 2000 or pay_year < 2000 or pay_month < 1 or pay_month > 12:
        flash("Datas inválidas.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id))

    if payment_type not in ("1st_installment", "2nd_installment", "full"):
        flash("Tipo de pagamento inválido.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))

    if months_worked < 1 or months_worked > 12:
        flash("Meses trabalhados devem ser entre 1 e 12.", "warning")
        return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))

    # Usa salário do mês de pagamento como base
    base_salary = _salary_for_employee(e, pay_year, pay_month)
    amounts = _calc_thirteenth_amount(base_salary, months_worked)

    # Estimativa de descontos apenas para 2ª parcela (conforme CLT)
    comp = _competence_start(pay_year, pay_month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    net_est = None
    gross = amounts["gross_amount"]

    # CLT: descontos aplicam-se na 2ª parcela (ou no integral se for único pagamento)
    apply_discounts = payment_type in ("2nd_installment", "full")
    if apply_discounts and inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if apply_discounts and irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross - inss_est - irrf_est).quantize(Decimal("0.01"))

    row = EmployeeThirteenth(
        employee_id=e.id,
        reference_year=ref_year,
        payment_year=pay_year,
        payment_month=pay_month,
        payment_type=payment_type,
        pay_date=pay_date,
        base_salary_at_calc=base_salary,
        months_worked=amounts["months_worked"],
        gross_amount=amounts["gross_amount"],
        inss_est=inss_est,
        irrf_est=irrf_est,
        net_est=net_est,
    )
    db.session.add(row)
    db.session.commit()

    flash("13º salário registrado.", "success")
    return redirect(url_for("payroll.employee_thirteenth", employee_id=e.id, year=pay_year, month=pay_month))


@payroll_bp.get("/thirteenth/<int:thirteenth_id>/receipt")
@login_required
def thirteenth_receipt(thirteenth_id: int):
    """Recibo imprimível do 13º salário."""
    t = EmployeeThirteenth.query.get_or_404(thirteenth_id)

    comp = _competence_start(int(t.payment_year), int(t.payment_month))
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    # CLT: avisos sobre prazos
    clt_warnings = []
    if t.payment_type == "1st_installment":
        if int(t.payment_month) != 11:
            clt_warnings.append("CLT: 1ª parcela idealmente paga em novembro.")
    elif t.payment_type == "2nd_installment":
        if int(t.payment_month) != 12:
            clt_warnings.append("CLT: 2ª parcela deve ser paga até 20 de dezembro.")

    return render_template(
        "payroll/thirteenth_receipt.html",
        t=t,
        employee=t.employee,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        has_tables=bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
        clt_warnings=clt_warnings,
    )


@payroll_bp.get("/employees/<int:employee_id>/terminations")
@login_required
def employee_terminations(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = (
        EmployeeTermination.query.filter_by(employee_id=e.id)
        .order_by(EmployeeTermination.termination_date.desc(), EmployeeTermination.id.desc())
        .all()
    )
    return render_template("payroll/employee_terminations.html", e=e, year=year, month=month, rows=rows)


@payroll_bp.post("/employees/<int:employee_id>/terminations")
@login_required
def employee_terminations_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    termination_date = _parse_date(request.form.get("termination_date"))
    termination_type = (request.form.get("termination_type") or "").strip().lower()
    notice_type = (request.form.get("notice_type") or "none").strip().lower()
    notice_days = int(request.form.get("notice_days") or 0)
    reason = (request.form.get("reason") or "").strip() or None
    gross_total = _to_decimal(request.form.get("gross_total"))
    fgts_balance_est = _to_decimal(request.form.get("fgts_balance_est"), default=Decimal("0"))
    fgts_fine_rate_in = _to_decimal(request.form.get("fgts_fine_rate"), default=Decimal("-1"))

    if year < 2000 or month < 1 or month > 12 or not termination_date:
        flash("Dados da rescisão inválidos.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id))

    if termination_type not in ("without_cause", "with_cause", "agreement", "resignation"):
        flash("Tipo de rescisão inválido.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))
    if notice_type not in ("worked", "indemnified", "none"):
        flash("Tipo de aviso prévio inválido.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))
    if notice_days < 0 or notice_days > 120:
        flash("Dias de aviso prévio inválidos.", "warning")
        return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))

    inss_est = None
    irrf_est = None
    net_est = None
    comp = _competence_start(year, month)
    deps_count = EmployeeDependent.query.filter_by(employee_id=e.id).count()
    _inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    _irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    if gross_total > 0 and inss_rows:
        inss_est = _calc_inss_progressive(gross_total, inss_rows)
    if gross_total > 0 and irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross_total - inss_est, irrf_cfg, irrf_rows, deps_count)
    if inss_est is not None and irrf_est is not None:
        net_est = (gross_total - inss_est - irrf_est).quantize(Decimal("0.01"))

    expected_rate = _termination_expected_fgts_rate(termination_type)
    if fgts_fine_rate_in < 0:
        fgts_fine_rate = expected_rate
    else:
        fgts_fine_rate = fgts_fine_rate_in
    fgts_fine_est = None
    if fgts_balance_est > 0 and fgts_fine_rate > 0:
        fgts_fine_est = (fgts_balance_est * fgts_fine_rate).quantize(Decimal("0.01"))

    row = EmployeeTermination(
        employee_id=e.id,
        year=year,
        month=month,
        termination_date=termination_date,
        termination_type=termination_type,
        notice_type=notice_type,
        notice_days=notice_days,
        reason=reason,
        gross_total=gross_total,
        fgts_balance_est=fgts_balance_est,
        fgts_fine_rate=fgts_fine_rate,
        fgts_fine_est=fgts_fine_est,
        inss_est=inss_est,
        irrf_est=irrf_est,
        net_est=net_est,
    )
    # Employee is no longer active after termination record
    e.active = False
    db.session.add(row)
    db.session.add(e)
    db.session.commit()
    flash("Rescisão registrada e funcionário marcado como inativo.", "success")
    return redirect(url_for("payroll.employee_terminations", employee_id=e.id, year=year, month=month))


@payroll_bp.get("/terminations/<int:termination_id>/receipt")
@login_required
def termination_receipt(termination_id: int):
    t = EmployeeTermination.query.get_or_404(termination_id)
    checklist = _termination_guided_checklist(t.termination_type, t.notice_type)
    return render_template("payroll/termination_receipt.html", t=t, employee=t.employee, checklist=checklist)


@payroll_bp.get("/employees/<int:employee_id>/leaves")
@login_required
def employee_leaves(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)
    rows = (
        EmployeeLeave.query.filter_by(employee_id=e.id)
        .order_by(EmployeeLeave.start_date.desc(), EmployeeLeave.id.desc())
        .all()
    )
    return render_template("payroll/employee_leaves.html", e=e, year=year, month=month, rows=rows)


@payroll_bp.post("/employees/<int:employee_id>/leaves")
@login_required
def employee_leaves_add(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    leave_type = (request.form.get("leave_type") or "").strip().lower()
    start_date = _parse_date(request.form.get("start_date"))
    end_date = _parse_date(request.form.get("end_date"))
    paid_by = (request.form.get("paid_by") or "").strip().lower()
    reason = (request.form.get("reason") or "").strip() or None

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id))
    if not start_date or not end_date or end_date < start_date:
        flash("Período do afastamento inválido.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))
    if leave_type not in ("medical", "maternity", "accident", "unpaid", "other"):
        flash("Tipo de afastamento inválido.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))
    if paid_by not in ("company", "inss", "mixed"):
        flash("Origem de pagamento inválida.", "warning")
        return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))

    row = EmployeeLeave(
        employee_id=e.id,
        year=year,
        month=month,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        paid_by=paid_by,
        reason=reason,
    )
    db.session.add(row)
    db.session.commit()
    flash("Afastamento registrado.", "success")
    return redirect(url_for("payroll.employee_leaves", employee_id=e.id, year=year, month=month))


@payroll_bp.post("/employees/<int:employee_id>/salary")
@login_required
def employee_add_salary(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    eff_raw = (request.form.get("effective_from") or "").strip()
    base_raw = (request.form.get("base_salary") or "").strip()

    eff = _parse_date(eff_raw)
    if not eff:
        flash("Data de vigência inválida.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))

    base = _to_decimal(base_raw)
    if base <= 0:
        flash("Informe um salário base válido.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))

    s = EmployeeSalary(employee_id=e.id, effective_from=eff, base_salary=base)
    db.session.add(s)
    db.session.commit()
    flash("Salário registrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.post("/employees/<int:employee_id>/dependent")
@login_required
def employee_add_dependent(employee_id: int):
    e = Employee.query.get_or_404(employee_id)
    full_name = (request.form.get("dep_full_name") or "").strip()
    cpf = (request.form.get("dep_cpf") or "").strip() or None
    if not full_name:
        flash("Informe o nome do dependente.", "warning")
        return redirect(url_for("payroll.employee_detail", employee_id=e.id))
    d = EmployeeDependent(employee_id=e.id, full_name=full_name, cpf=cpf)
    db.session.add(d)
    db.session.commit()
    flash("Dependente registrado.", "success")
    return redirect(url_for("payroll.employee_detail", employee_id=e.id))


@payroll_bp.get("/")
@login_required
def payroll_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    return render_template("payroll/payroll_home.html", year=year, month=month, run=run)


@payroll_bp.post("/")
@login_required
def payroll_create_or_open():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.payroll_home"))

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    if not run:
        run = PayrollRun(
            year=year,
            month=month,
            overtime_hour_rate=Decimal("12.45"),
            overtime_weekly_hours=Decimal("44"),
            overtime_additional_pct=Decimal("50"),
        )
        db.session.add(run)
        db.session.flush()

        employees = Employee.query.filter_by(active=True).order_by(Employee.full_name.asc()).all()
        for e in employees:
            base = _salary_for_employee(e, year, month)
            line_rate = _overtime_rate_from_salary(base, run.overtime_weekly_hours, run.overtime_additional_pct)
            line = PayrollLine(
                payroll_run_id=run.id,
                employee_id=e.id,
                base_salary=base,
                overtime_hours=Decimal("0"),
                overtime_hour_rate=line_rate,
                overtime_amount=Decimal("0"),
                gross_total=base,
            )
            db.session.add(line)

        db.session.commit()

    return redirect(url_for("payroll.payroll_edit", run_id=run.id))


@payroll_bp.get("/<int:run_id>")
@login_required
def payroll_edit(run_id: int):
    run = PayrollRun.query.get_or_404(run_id)
    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).order_by(PayrollLine.id.asc()).all()
    monthly_hours = _monthly_hours_from_weekly(Decimal(str(run.overtime_weekly_hours or 44)))
    return render_template("payroll/payroll_edit.html", run=run, lines=lines, monthly_hours=monthly_hours)


@payroll_bp.post("/<int:run_id>")
@login_required
def payroll_save(run_id: int):
    run = PayrollRun.query.get_or_404(run_id)

    if _competence_is_closed(run.year, run.month):
        flash(
            "Atenção: esta competência está marcada como FECHADA. Você ainda pode alterar, mas revise os relatórios/guias para manter tudo consistente.",
            "warning",
        )

    weekly_hours = _to_decimal(
        request.form.get("overtime_weekly_hours"),
        default=Decimal(str(run.overtime_weekly_hours or 44)),
    )
    if weekly_hours <= 0:
        weekly_hours = Decimal("44")

    additional_pct = _to_decimal(
        request.form.get("overtime_additional_pct"),
        default=Decimal(str(run.overtime_additional_pct or 50)),
    )
    if additional_pct < 0:
        additional_pct = Decimal("0")

    run.overtime_weekly_hours = weekly_hours
    run.overtime_additional_pct = additional_pct

    lines = PayrollLine.query.filter_by(payroll_run_id=run.id).all()
    first_rate = None
    for ln in lines:
        key = f"overtime_hours_{ln.employee_id}"
        hours = _to_decimal(request.form.get(key), default=Decimal("0"))
        if hours < 0:
            hours = Decimal("0")
        rate = _overtime_rate_from_salary(ln.base_salary, run.overtime_weekly_hours, run.overtime_additional_pct)
        ln.overtime_hours = hours
        ln.overtime_hour_rate = rate
        ln.overtime_amount = (hours * rate).quantize(Decimal("0.01"))
        ln.gross_total = (Decimal(str(ln.base_salary)) + ln.overtime_amount).quantize(Decimal("0.01"))
        if first_rate is None:
            first_rate = rate
        db.session.add(ln)

    run.overtime_hour_rate = first_rate if first_rate is not None else Decimal("0")

    db.session.add(run)
    db.session.commit()
    flash("Folha salva.", "success")
    return redirect(url_for("payroll.payroll_edit", run_id=run.id))


@payroll_bp.get("/<int:run_id>/holerite/<int:employee_id>")
@login_required
def payroll_holerite(run_id: int, employee_id: int):
    run = PayrollRun.query.get_or_404(run_id)
    ln = PayrollLine.query.filter_by(payroll_run_id=run.id, employee_id=employee_id).first()
    if not ln:
        flash("Funcionário não encontrado nesta folha.", "warning")
        return redirect(url_for("payroll.payroll_edit", run_id=run.id))

    comp = date(int(run.year), int(run.month), 1)
    deps_count = EmployeeDependent.query.filter_by(employee_id=employee_id).count()
    gross = (Decimal(str(ln.gross_total or 0)) if ln.gross_total is not None else Decimal("0"))

    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)

    inss_est = None
    irrf_est = None
    if inss_rows:
        inss_est = _calc_inss_progressive(gross, inss_rows)
    if irrf_rows and irrf_cfg and inss_est is not None:
        irrf_est = _calc_irrf(gross - inss_est, irrf_cfg, irrf_rows, deps_count)

    return render_template(
        "payroll/holerite.html",
        run=run,
        ln=ln,
        deps_count=deps_count,
        inss_eff=inss_eff,
        irrf_eff=irrf_eff,
        inss_est=inss_est,
        irrf_est=irrf_est,
        irrf_dep_ded=(getattr(irrf_cfg, "dependent_deduction", None) if irrf_cfg else None),
    )


@payroll_bp.get("/config/taxes")
@login_required
def tax_config():
    context = _tax_config_context()
    return render_template("payroll/tax_config.html", **context)


def _tax_config_context() -> dict:
    inss_rows = TaxInssBracket.query.order_by(TaxInssBracket.effective_from.desc(), TaxInssBracket.up_to.asc().nullslast()).all()
    irrf_rows = TaxIrrfBracket.query.order_by(TaxIrrfBracket.effective_from.desc(), TaxIrrfBracket.up_to.asc().nullslast()).all()
    irrf_configs = TaxIrrfConfig.query.order_by(TaxIrrfConfig.effective_from.desc()).all()
    return {
        "inss_rows": inss_rows,
        "irrf_rows": irrf_rows,
        "irrf_configs": irrf_configs,
    }


@payroll_bp.post("/config/taxes/sync")
@login_required
def tax_sync_trigger():
    try:
        target_year = int(request.form.get("target_year") or date.today().year)
    except (TypeError, ValueError):
        target_year = 0
    mode = (request.form.get("mode") or "dry_run").strip().lower()
    apply_changes = mode == "apply"

    if target_year < 2000 or target_year > 9999:
        flash("Ano inválido para sincronização fiscal.", "warning")
        context = _tax_config_context()
        return render_template("payroll/tax_config.html", **context, sync_result=None)

    sync_result = None
    try:
        sync_result = run_tax_sync(target_year=target_year, apply_changes=apply_changes)
        if sync_result.get("applied"):
            flash("Sincronização concluída e tabelas fiscais gravadas no banco.", "success")
        else:
            flash("Simulação concluída (dry-run). Revise o relatório antes de aplicar.", "info")
    except Exception as e:
        flash(f"Falha na sincronização fiscal: {e}", "warning")
        sync_result = {
            "target_year": target_year,
            "applied": False,
            "report_lines": [f"ERRO: {e}"],
        }

    context = _tax_config_context()
    return render_template("payroll/tax_config.html", **context, sync_result=sync_result)


@payroll_bp.post("/config/taxes/inss")
@login_required
def tax_inss_add():
    eff_raw = (request.form.get("effective_from") or "").strip()
    up_to_raw = (request.form.get("up_to") or "").strip()
    rate_raw = (request.form.get("rate") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    up_to = _to_decimal(up_to_raw) if up_to_raw else None
    rate = _to_decimal(rate_raw)
    if rate <= 0:
        flash("Alíquota inválida. Use formato 0,075 para 7,5%.", "warning")
        return redirect(url_for("payroll.tax_config"))

    row = TaxInssBracket(effective_from=eff, up_to=up_to, rate=rate)
    db.session.add(row)
    db.session.commit()
    flash("Faixa INSS adicionada.", "success")
    return redirect(url_for("payroll.tax_config"))


@payroll_bp.post("/config/taxes/irrf_config")
@login_required
def tax_irrf_config_set():
    eff_raw = (request.form.get("effective_from") or "").strip()
    dep_raw = (request.form.get("dependent_deduction") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    dep = _to_decimal(dep_raw)
    if dep < 0:
        dep = Decimal("0")

    cfg = TaxIrrfConfig.query.filter_by(effective_from=eff).first()
    if not cfg:
        cfg = TaxIrrfConfig(effective_from=eff, dependent_deduction=dep)
        db.session.add(cfg)
    else:
        cfg.dependent_deduction = dep
    db.session.commit()
    flash("Config IRRF salva.", "success")
    return redirect(url_for("payroll.tax_config"))


@payroll_bp.post("/config/taxes/irrf")
@login_required
def tax_irrf_add():
    eff_raw = (request.form.get("effective_from") or "").strip()
    up_to_raw = (request.form.get("up_to") or "").strip()
    rate_raw = (request.form.get("rate") or "").strip()
    ded_raw = (request.form.get("deduction") or "").strip()
    eff = _parse_date(eff_raw)
    if not eff:
        flash("Vigência inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    up_to = _to_decimal(up_to_raw) if up_to_raw else None
    rate = _to_decimal(rate_raw)
    ded = _to_decimal(ded_raw)
    if rate < 0:
        flash("Alíquota inválida.", "warning")
        return redirect(url_for("payroll.tax_config"))

    row = TaxIrrfBracket(effective_from=eff, up_to=up_to, rate=rate, deduction=ded)
    db.session.add(row)
    db.session.commit()
    flash("Faixa IRRF adicionada.", "success")
    return redirect(url_for("payroll.tax_config"))


def _next_month(year: int, month: int) -> tuple[int, int]:
    if int(month) == 12:
        return int(year) + 1, 1
    return int(year), int(month) + 1


def _deadline_status(today: date, due_date: date | None, paid_at: date | None) -> str:
    if paid_at:
        return "ok"
    if due_date is None:
        return "pending"
    days_left = (due_date - today).days
    if days_left < 0:
        return "danger"
    if days_left <= 3:
        return "warning"
    return "ok"


def _build_legal_deadlines(year: int, month: int, docs: dict[str, GuideDocument | None]) -> list[dict]:
    today = date.today()
    ny, nm = _next_month(year, month)
    default_due = date(int(ny), int(nm), 20)

    items = [
        {
            "key": "das",
            "title": "DAS (Simples Nacional)",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
        {
            "key": "fgts",
            "title": "FGTS Digital",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
        {
            "key": "darf",
            "title": "DARF (encargos folha)",
            "source": "Prazo operacional padrão: dia 20 do mês seguinte (confira a guia oficial).",
        },
    ]

    out: list[dict] = []
    for item in items:
        doc = docs.get(item["key"])
        due_date = (getattr(doc, "due_date", None) if doc else None) or default_due
        paid_at = getattr(doc, "paid_at", None) if doc else None
        status = _deadline_status(today=today, due_date=due_date, paid_at=paid_at)

        if paid_at:
            note = "Pago"
        elif status == "danger":
            note = "Atrasado"
        elif status == "warning":
            note = "Vence em breve"
        else:
            note = "No prazo"

        out.append(
            {
                "title": item["title"],
                "due_date": due_date,
                "paid_at": paid_at,
                "status": status,
                "note": note,
                "source": item["source"],
            }
        )

    if int(month) == 11:
        due_13_first = date(int(year), 11, 30)
        status_13_first = _deadline_status(today=today, due_date=due_13_first, paid_at=None)
        out.append(
            {
                "title": "13º salário - 1ª parcela",
                "due_date": due_13_first,
                "paid_at": None,
                "status": status_13_first,
                "note": "Conferir se todos os funcionários elegíveis receberam a 1ª parcela.",
                "source": "Regra CLT: até 30/11.",
            }
        )

    if int(month) == 12:
        due_13_second = date(int(year), 12, 20)
        status_13_second = _deadline_status(today=today, due_date=due_13_second, paid_at=None)
        out.append(
            {
                "title": "13º salário - 2ª parcela",
                "due_date": due_13_second,
                "paid_at": None,
                "status": status_13_second,
                "note": "Conferir se todos os funcionários elegíveis receberam a 2ª parcela.",
                "source": "Regra CLT: até 20/12.",
            }
        )

    return out


def _reminder_label(days_left: int | None, paid_at: date | None) -> str:
    if paid_at:
        return "Concluido"
    if days_left is None:
        return "Sem vencimento definido"
    if days_left < 0:
        return f"Atrasado ha {abs(days_left)} dia(s)"
    if days_left == 0:
        return "Vence hoje (D-0)"
    if days_left == 1:
        return "Vence amanha (D-1)"
    if days_left <= 3:
        return f"Prazo critico (D-{days_left})"
    if days_left <= 7:
        return f"Planejar esta semana (D-{days_left})"
    return f"No radar (D-{days_left})"


def _agenda_bucket(days_left: int | None, paid_at: date | None) -> str:
    if paid_at:
        return "done"
    if days_left is None:
        return "next_7_days"
    if days_left < 0:
        return "overdue"
    if days_left == 0:
        return "today"
    if days_left <= 7:
        return "next_7_days"
    return "later"


def _agenda_resolution_steps(bucket: str, action_label: str, title: str) -> list[str]:
    if bucket not in ("overdue", "today"):
        return []
    return [
        f"1) Clique em '{action_label}' e abra o item: {title}.",
        "2) Atualize os dados e confirme vencimento/pagamento para remover o alerta.",
        "3) Rode o compliance-check para validar se a pendência foi resolvida.",
    ]


def _build_obligations_agenda(year: int, month: int, docs: dict[str, GuideDocument | None]) -> list[dict]:
    today = date.today()
    ny, nm = _next_month(year, month)
    default_due = date(int(ny), int(nm), 20)

    agenda_items: list[dict] = []
    for key, title in (
        ("das", "Emitir e conferir DAS"),
        ("fgts", "Emitir e conferir FGTS Digital"),
        ("darf", "Emitir e conferir DARF da folha"),
    ):
        doc = docs.get(key)
        due_date = (getattr(doc, "due_date", None) if doc else None) or default_due
        paid_at = getattr(doc, "paid_at", None) if doc else None
        days_left = (due_date - today).days if due_date else None
        bucket = _agenda_bucket(days_left=days_left, paid_at=paid_at)
        action_label = "Abrir guias"
        title_full = title
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_date,
                "paid_at": paid_at,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=paid_at),
                "bucket": bucket,
                "action_url": url_for("payroll.close_home", year=year, month=month),
                "action_label": action_label,
                "why": "Evita atraso de encargos e reduz risco de multa/juros.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )

    if int(month) == 11:
        due_13_first = date(int(year), 11, 30)
        days_left = (due_13_first - today).days
        bucket = _agenda_bucket(days_left=days_left, paid_at=None)
        action_label = "Ver funcionarios"
        title_full = "Conferir pagamento da 1a parcela do 13o"
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_13_first,
                "paid_at": None,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=None),
                "bucket": bucket,
                "action_url": url_for("payroll.employees"),
                "action_label": action_label,
                "why": "Ajuda a cumprir o prazo legal do 13o e evitar passivo trabalhista.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )
    if int(month) == 12:
        due_13_second = date(int(year), 12, 20)
        days_left = (due_13_second - today).days
        bucket = _agenda_bucket(days_left=days_left, paid_at=None)
        action_label = "Ver funcionarios"
        title_full = "Conferir pagamento da 2a parcela do 13o"
        agenda_items.append(
            {
                "title": title_full,
                "due_date": due_13_second,
                "paid_at": None,
                "days_left": days_left,
                "reminder": _reminder_label(days_left=days_left, paid_at=None),
                "bucket": bucket,
                "action_url": url_for("payroll.employees"),
                "action_label": action_label,
                "why": "Ajuda a cumprir o prazo legal do 13o e evitar passivo trabalhista.",
                "resolution_steps": _agenda_resolution_steps(bucket=bucket, action_label=action_label, title=title_full),
            }
        )

    compliance_due = default_due - timedelta(days=2)
    compliance_days_left = (compliance_due - today).days
    compliance_bucket = _agenda_bucket(days_left=compliance_days_left, paid_at=None)
    compliance_action = "Abrir fechamento"
    compliance_title = "Rodar compliance-check final da competencia"
    agenda_items.append(
        {
            "title": compliance_title,
            "due_date": compliance_due,
            "paid_at": None,
            "days_left": compliance_days_left,
            "reminder": _reminder_label(days_left=compliance_days_left, paid_at=None),
            "bucket": compliance_bucket,
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": compliance_action,
            "why": "Detecta pendencias antes do vencimento das guias e evita retrabalho.",
            "resolution_steps": _agenda_resolution_steps(bucket=compliance_bucket, action_label=compliance_action, title=compliance_title),
        }
    )

    agenda_items.sort(key=lambda x: (x.get("due_date") is None, x.get("due_date") or date.max))
    return agenda_items


def _recommended_close_action(checklist: dict[str, dict]) -> dict | None:
    priority = ["revenue", "payroll", "taxes", "guides", "vacations", "thirteenth", "terminations", "leaves"]
    for key in priority:
        item = checklist.get(key)
        if item and not bool(item.get("ok")):
            return {
                "key": key,
                "title": item.get("title"),
                "help": item.get("help"),
                "action_url": item.get("action_url"),
                "action_label": item.get("action_label"),
            }
    return None


def _critical_close_pending_items(checklist: dict[str, dict]) -> list[dict]:
    critical_keys = ["revenue", "payroll", "taxes", "guides"]
    out: list[dict] = []
    for key in critical_keys:
        item = checklist.get(key)
        if item and not bool(item.get("ok")):
            out.append(
                {
                    "key": key,
                    "title": item.get("title"),
                    "help": item.get("help"),
                    "action_url": item.get("action_url"),
                    "action_label": item.get("action_label"),
                }
            )
    return out


@payroll_bp.get("/close")
@login_required
def close_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    comp = date(int(year), int(month), 1)
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    closed = CompetenceClose.query.filter_by(year=year, month=month).first()

    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }
    legal_deadlines = _build_legal_deadlines(year=year, month=month, docs=docs)
    obligations_agenda = _build_obligations_agenda(year=year, month=month, docs=docs)
    agenda_overdue = [item for item in obligations_agenda if item.get("bucket") == "overdue"]
    agenda_today = [item for item in obligations_agenda if item.get("bucket") == "today"]
    agenda_next_7_days = [item for item in obligations_agenda if item.get("bucket") == "next_7_days"]
    compliance_session_key = f"payroll_close_compliance:{year}-{month}"
    compliance_result = session.pop(compliance_session_key, None)

    summary = _calc_month_summary(run)
    revenue_summary = _calc_revenue_month_summary(year, month)
    vacations_summary = _calc_vacations_month_summary(year, month)
    thirteenth_summary = _calc_thirteenth_month_summary(year, month)
    terminations_summary = _calc_terminations_month_summary(year, month)
    leaves_summary = _calc_leaves_month_summary(year, month)

    checklist = {
        "revenue": {
            "ok": bool(revenue_summary.get("count")),
            "title": "Receitas / notas do mês",
            "help": "Registre as notas (receitas) da competência. Isso serve para conferência, relatórios e cálculo do Fator R.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Registrar receitas",
        },
        "payroll": {
            "ok": bool(run),
            "title": "Folha do mês",
            "help": "Você precisa ter uma folha criada para esta competência, para gerar holerites e apurar valores.",
            "action_url": (url_for("payroll.payroll_home", year=year, month=month)),
            "action_label": "Abrir folha",
        },
        "taxes": {
            "ok": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "title": "Tabelas de INSS/IRRF",
            "help": "Essas tabelas são usadas para estimar descontos no holerite. Se estiver vazio, rode o sync ou configure manualmente.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Ver configurações",
            "meta": {
                "inss_eff": inss_eff,
                "irrf_eff": irrf_eff,
            },
        },
        "guides": {
            "ok": all(bool(docs.get(k)) and bool(getattr(docs.get(k), "filename", None)) for k in ("darf", "das", "fgts")),
            "title": "Guias anexadas (DARF/DAS/FGTS)",
            "help": "Anexe os PDFs das guias da competência. Isso ajuda a centralizar e conferir antes de pagar.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
        "vacations": {
            "ok": True,
            "title": "Férias no mês",
            "help": "Se algum funcionário recebeu férias nesta competência, registre aqui para manter o histórico e conferir valores.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(vacations_summary.get("count") or 0),
                "total_gross": vacations_summary.get("total_gross"),
            },
        },
        "thirteenth": {
            "ok": True,
            "title": "13º no mês",
            "help": "Registre parcelas do 13º (1ª até 30/nov, 2ª até 20/dez) para controle.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(thirteenth_summary.get("count") or 0),
                "total_gross": thirteenth_summary.get("total_gross"),
            },
        },
        "terminations": {
            "ok": True,
            "title": "Rescisões no mês",
            "help": "Registre desligamentos para manter histórico trabalhista e controle de custos.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(terminations_summary.get("count") or 0),
                "total_gross": terminations_summary.get("total_gross"),
            },
        },
        "leaves": {
            "ok": True,
            "title": "Afastamentos no mês",
            "help": "Registre atestados/licenças para checagem de regras e histórico por funcionário.",
            "action_url": url_for("payroll.employees"),
            "action_label": "Ver funcionários",
            "meta": {
                "count": int(leaves_summary.get("count") or 0),
            },
        },
    }

    recommended_action = _recommended_close_action(checklist)
    critical_pending_items = _critical_close_pending_items(checklist)

    return render_template(
        "payroll/close_home.html",
        year=year,
        month=month,
        docs=docs,
        run=run,
        closed=closed,
        checklist=checklist,
        recommended_action=recommended_action,
        critical_pending_items=critical_pending_items,
        summary=summary,
        legal_deadlines=legal_deadlines,
        obligations_agenda=obligations_agenda,
        agenda_overdue=agenda_overdue,
        agenda_today=agenda_today,
        agenda_next_7_days=agenda_next_7_days,
        compliance_result=compliance_result,
        revenue_summary=revenue_summary,
        vacations_summary=vacations_summary,
        thirteenth_summary=thirteenth_summary,
        terminations_summary=terminations_summary,
        leaves_summary=leaves_summary,
    )


@payroll_bp.post("/close/compliance")
@login_required
def close_run_compliance():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    apply_sync = (request.form.get("apply_sync") or "0") == "1"

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida para compliance-check.", "warning")
        return redirect(url_for("payroll.close_home"))

    try:
        result = run_compliance_check(target_year=year, apply_tax_sync=apply_sync)
        if result.get("ok"):
            flash("Compliance-check concluído sem alertas.", "success")
        else:
            flash(f"Compliance-check encontrou {len(result.get('issues') or [])} alerta(s).", "warning")

        session[f"payroll_close_compliance:{year}-{month}"] = {
            "target_year": year,
            "ok": bool(result.get("ok")),
            "issues_count": len(result.get("issues") or []),
            "report_lines": list(result.get("report_lines") or []),
            "sync_report_lines": list(result.get("sync_report_lines") or []),
        }
    except Exception as e:
        flash(f"Falha ao executar compliance-check: {e}", "warning")
        session[f"payroll_close_compliance:{year}-{month}"] = {
            "target_year": year,
            "ok": False,
            "issues_count": 1,
            "report_lines": [f"ERRO: {e}"],
            "sync_report_lines": [],
        }

    return redirect(url_for("payroll.close_home", year=year, month=month))


@payroll_bp.get("/revenue")
@login_required
def revenue_home():
    now = datetime.now()
    year = int(request.args.get("year") or now.year)
    month = int(request.args.get("month") or now.month)

    notes = RevenueNote.query.filter_by(year=year, month=month).order_by(RevenueNote.issued_at.asc().nullslast()).all()
    total = Decimal("0")
    for n in notes:
        try:
            total += Decimal(str(n.amount or 0))
        except Exception:
            total += Decimal("0")
    total = total.quantize(Decimal("0.01"))

    return render_template(
        "payroll/revenue_home.html",
        year=year,
        month=month,
        notes=notes,
        total=total,
    )


@payroll_bp.post("/revenue")
@login_required
def revenue_add():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.revenue_home"))

    issued_at_raw = (request.form.get("issued_at") or "").strip()
    issued_at = _parse_date(issued_at_raw)

    customer_name = (request.form.get("customer_name") or "").strip()
    description = (request.form.get("description") or "").strip()
    amount = _to_decimal(request.form.get("amount"))
    if amount <= 0:
        flash("Informe um valor maior que zero.", "warning")
        return redirect(url_for("payroll.revenue_home", year=year, month=month))

    row = RevenueNote(
        year=year,
        month=month,
        issued_at=issued_at,
        customer_name=customer_name,
        description=description,
        amount=amount,
    )
    db.session.add(row)
    db.session.commit()

    flash("Receita registrada.", "success")
    return redirect(url_for("payroll.revenue_home", year=year, month=month))


@payroll_bp.post("/revenue/<int:note_id>/delete")
@login_required
def revenue_delete(note_id: int):
    row = RevenueNote.query.get_or_404(note_id)
    year = int(row.year)
    month = int(row.month)
    db.session.delete(row)
    db.session.commit()
    flash("Receita removida.", "success")
    return redirect(url_for("payroll.revenue_home", year=year, month=month))


@payroll_bp.post("/close/mark")
@login_required
def close_mark():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    run = PayrollRun.query.filter_by(year=year, month=month).first()
    comp = date(int(year), int(month), 1)
    inss_eff, inss_rows = _latest_inss_brackets(comp)
    irrf_cfg = _latest_irrf_config(comp)
    irrf_eff, irrf_rows = _latest_irrf_brackets(comp)
    docs = {
        "darf": GuideDocument.query.filter_by(year=year, month=month, doc_type="darf").first(),
        "das": GuideDocument.query.filter_by(year=year, month=month, doc_type="das").first(),
        "fgts": GuideDocument.query.filter_by(year=year, month=month, doc_type="fgts").first(),
    }
    revenue_summary = _calc_revenue_month_summary(year, month)

    close_checklist = {
        "revenue": {
            "ok": bool(revenue_summary.get("count")),
            "title": "Receitas / notas do mês",
            "help": "Registre as notas (receitas) da competência.",
            "action_url": url_for("payroll.revenue_home", year=year, month=month),
            "action_label": "Registrar receitas",
        },
        "payroll": {
            "ok": bool(run),
            "title": "Folha do mês",
            "help": "Crie/abra a folha da competência para gerar holerites.",
            "action_url": url_for("payroll.payroll_home", year=year, month=month),
            "action_label": "Abrir folha",
        },
        "taxes": {
            "ok": bool(inss_rows) and bool(irrf_rows) and bool(irrf_cfg),
            "title": "Tabelas de INSS/IRRF",
            "help": "Sincronize ou configure as tabelas fiscais vigentes.",
            "action_url": url_for("payroll.tax_config"),
            "action_label": "Ver configurações",
            "meta": {"inss_eff": inss_eff, "irrf_eff": irrf_eff},
        },
        "guides": {
            "ok": all(bool(docs.get(k)) and bool(getattr(docs.get(k), "filename", None)) for k in ("darf", "das", "fgts")),
            "title": "Guias anexadas (DARF/DAS/FGTS)",
            "help": "Anexe os PDFs das guias da competência.",
            "action_url": url_for("payroll.close_home", year=year, month=month),
            "action_label": "Anexar guias",
        },
    }

    critical_pending = _critical_close_pending_items(close_checklist)
    if critical_pending:
        flash("Não foi possível fechar: ainda existem pendências críticas na competência.", "warning")
        for item in critical_pending:
            flash(f"Pendente: {item['title']} — {item['help']}", "warning")
        return redirect(url_for("payroll.close_home", year=year, month=month))

    row = CompetenceClose.query.filter_by(year=year, month=month).first()
    if not row:
        row = CompetenceClose(year=year, month=month)
        db.session.add(row)
        db.session.commit()
    flash("Competência marcada como FECHADA (com aviso).", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))


@payroll_bp.post("/close/reopen")
@login_required
def close_reopen():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    row = CompetenceClose.query.filter_by(year=year, month=month).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Competência reaberta.", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))


@payroll_bp.post("/close/upload")
@login_required
def close_upload():
    year = int(request.form.get("year") or 0)
    month = int(request.form.get("month") or 0)
    doc_type = (request.form.get("doc_type") or "").strip().lower()

    if _competence_is_closed(year, month):
        flash(
            "Atenção: esta competência está marcada como FECHADA. Você pode substituir o PDF, mas revise se o fechamento continua correto.",
            "warning",
        )

    if year < 2000 or month < 1 or month > 12:
        flash("Competência inválida.", "warning")
        return redirect(url_for("payroll.close_home"))

    if doc_type not in ("darf", "das", "fgts"):
        flash("Tipo de guia inválido.", "warning")
        return redirect(url_for("payroll.close_home", year=year, month=month))

    amount = _to_decimal(request.form.get("amount"))
    due_date_raw = (request.form.get("due_date") or "").strip()
    paid_at_raw = (request.form.get("paid_at") or "").strip()

    due_date = _parse_date(due_date_raw)
    paid_at = _parse_date(paid_at_raw)

    doc = GuideDocument.query.filter_by(year=year, month=month, doc_type=doc_type).first()
    if not doc:
        doc = GuideDocument(year=year, month=month, doc_type=doc_type, filename=None)
        db.session.add(doc)

    f = request.files.get("file")
    if f and f.filename:
        fname = secure_filename(f.filename)
        ext = os.path.splitext(fname)[1].lower()
        if ext != ".pdf":
            flash("Apenas PDF.", "warning")
            return redirect(url_for("payroll.close_home", year=year, month=month))

        target_name = f"{year}-{month:02d}_{doc_type}.pdf"
        target_path = os.path.join(_media_guides_dir(), target_name)
        f.save(target_path)
        doc.filename = target_name
    doc.amount = amount if amount > 0 else None
    doc.due_date = due_date
    doc.paid_at = paid_at

    db.session.commit()
    flash("Guia atualizada.", "success")
    return redirect(url_for("payroll.close_home", year=year, month=month))
