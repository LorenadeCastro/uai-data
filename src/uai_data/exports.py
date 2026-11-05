"""Exportações geradas na hora do build: Excel (.xlsx) e PDF do painel completo.

Os arquivos são cifrados junto com os dados; o navegador decifra e entrega o download.
CSV e PNG saem direto no navegador, já respeitando os filtros que o leitor escolheu.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import Card, Dashboard

NAVY, ORANGE, YELLOW = "#002655", "#F1791B", "#FBC327"
XL_NAVY = NAVY.lstrip("#")   # openpyxl não aceita o "#"
ASSETS = Path(__file__).parent / "web" / "assets"
XLSX_FORMATS = {
    "currency": '"R$" #,##0.00', "number": "#,##0.00", "integer": "#,##0",
    "percent": "0.00%", "text": "@",
}


def _visible(payload: dict) -> list[tuple[int, dict]]:
    """Colunas que o leitor vê (esconde as colunas auxiliares de média ponderada)."""
    return [(i, c) for i, c in enumerate(payload["columns"]) if c["kind"] != "weight"]


def _sheet_name(title: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]\*\?/\\:]", " ", title).strip()[:28] or "Card"
    name, n = base, 2
    while name.lower() in used:
        name, n = f"{base[:25]} {n}", n + 1
    used.add(name.lower())
    return name


def dashboard_xlsx(dash: Dashboard, data: dict[str, dict], generated: dt.datetime) -> bytes:
    wb = Workbook()
    summary = wb.active
    summary.title = "Resumo"
    summary["A1"] = dash.title
    summary["A1"].font = Font(size=16, bold=True, color=XL_NAVY)
    summary["A2"] = dash.description or ""
    summary["A3"] = f"Gerado em {generated:%d/%m/%Y %H:%M} — dados completos, sem filtros de tela."
    summary["A5"], summary["B5"] = "Aba", "Card"
    for cell in (summary["A5"], summary["B5"]):
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=XL_NAVY)

    used = {"resumo"}
    head_fill = PatternFill("solid", fgColor=XL_NAVY)
    for r, card in enumerate(dash.cards, start=6):
        payload = data[card.id]
        name = _sheet_name(card.title, used)
        summary.cell(r, 1, name)
        summary.cell(r, 2, card.title)
        ws = wb.create_sheet(name)
        cols = _visible(payload)
        for j, (_, col) in enumerate(cols, start=1):
            cell = ws.cell(1, j, col["label"])
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for i, row in enumerate(payload["rows"], start=2):
            for j, (src, col) in enumerate(cols, start=1):
                cell = ws.cell(i, j, row[src])
                if col["kind"] == "measure":
                    cell.number_format = XLSX_FORMATS.get(col["format"], "#,##0.00")
        ws.freeze_panes = "A2"
        if payload["rows"]:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(payload['rows']) + 1}"
        for j, (src, col) in enumerate(cols, start=1):
            longest = max([len(str(col["label"]))] + [len(f"{r[src]:,.2f}" if isinstance(r[src], float) else str(r[src])) for r in payload["rows"][:500]])
            ws.column_dimensions[get_column_letter(j)].width = min(max(10, longest + 2), 60)
    summary.column_dimensions["A"].width = 30
    summary.column_dimensions["B"].width = 60
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------- PDF
def _brl(value, fmt: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and fmt != "text":
        if fmt == "integer":
            text = f"{value:,.0f}"
        elif fmt == "percent":
            text = f"{value * 100:,.2f}%"
        else:
            text = f"{value:,.2f}"
        text = text.replace(",", "§").replace(".", ",").replace("§", ".")
        return f"R$ {text}" if fmt == "currency" else text
    return str(value)


def _chart(card: Card, payload: dict) -> Drawing | None:
    cols = _visible(payload)
    dims = [(i, c) for i, c in cols if c["kind"] == "dim"]
    meas = [(i, c) for i, c in cols if c["kind"] == "measure"]
    if not dims or not meas or card.viz in ("table", "pivot", "number", "gauge", "heatmap", "treemap"):
        return None
    xi, yi = dims[0][0], meas[0][0]
    totals: dict[str, float] = {}
    for row in payload["rows"]:                       # agrega pela primeira dimensão
        totals[str(row[xi])] = totals.get(str(row[xi]), 0.0) + float(row[yi] or 0)
    items = list(totals.items())
    if card.viz not in ("line", "area"):
        items = sorted(items, key=lambda kv: kv[1], reverse=True)
    items = items[:12]
    if not items:
        return None
    d = Drawing(24 * cm, 6.2 * cm)
    palette = [colors.HexColor(c) for c in (NAVY, ORANGE, YELLOW, "#2F6DB5", "#8A5A00", "#5FA8D3")]
    if card.viz in ("pie", "donut", "funnel"):
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 5 * cm, 0.4 * cm, 5.4 * cm, 5.4 * cm
        pie.data = [max(v, 0) for _, v in items]
        pie.labels = [k[:18] for k, _ in items]
        pie.sideLabels = True
        for n in range(len(items)):
            pie.slices[n].fillColor = palette[n % len(palette)]
        d.add(pie)
    elif card.viz in ("line", "area"):
        lp = LinePlot()
        lp.x, lp.y, lp.width, lp.height = 1.6 * cm, 0.8 * cm, 21 * cm, 5 * cm
        lp.data = [[(n, v) for n, (_, v) in enumerate(items)]]
        lp.lines[0].strokeColor = colors.HexColor(NAVY)
        lp.lines[0].strokeWidth = 2
        d.add(lp)
    else:
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 1.6 * cm, 1.3 * cm, 21 * cm, 4.6 * cm
        bc.data = [[v for _, v in items]]
        bc.categoryAxis.categoryNames = [k[:14] for k, _ in items]
        bc.categoryAxis.labels.angle = 25
        bc.categoryAxis.labels.fontSize = 7
        bc.valueAxis.labels.fontSize = 7
        bc.bars[0].fillColor = colors.HexColor(NAVY)
        d.add(bc)
    return d


def dashboard_pdf(dash: Dashboard, data: dict[str, dict], generated: dt.datetime, site_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=dash.title, author=site_name)
    styles = getSampleStyleSheet()
    h1, h2, small = styles["Title"], styles["Heading2"], styles["Normal"]
    h1.textColor = h2.textColor = colors.HexColor(NAVY)
    story: list = []
    logo = ASSETS / "logo.png"
    if logo.exists():
        story.append(Image(str(logo), width=6 * cm, height=6 * cm * 283 / 900, hAlign="LEFT"))
        story.append(Spacer(1, 0.3 * cm))
    story += [Paragraph(dash.title, h1)]
    if dash.description:
        story.append(Paragraph(dash.description, small))
    story += [Paragraph(f"Gerado em {generated:%d/%m/%Y %H:%M} — dados completos, sem filtros de tela.", small),
              Spacer(1, 0.4 * cm)]

    max_table_rows = 40
    for card in dash.cards:
        payload = data[card.id]
        cols = _visible(payload)
        story.append(Paragraph(card.title, h2))
        if card.description:
            story.append(Paragraph(card.description, small))
        chart = _chart(card, payload)
        if chart:
            story.append(chart)
        head = [c["label"] for _, c in cols]
        body = [[_brl(r[i], c["format"]) for i, c in cols] for r in payload["rows"][:max_table_rows]]
        if body:
            table = Table([head, *body], repeatRows=1)
            style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                     ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                     ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5FA")]),
                     ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D2E3"))]
            for j, (_, c) in enumerate(cols):
                if c["kind"] == "measure":
                    style.append(("ALIGN", (j, 1), (j, -1), "RIGHT"))
            table.setStyle(TableStyle(style))
            story.append(table)
            extra = len(payload["rows"]) - max_table_rows
            if extra > 0:
                story.append(Paragraph(f"… e mais {extra} linhas. Baixe o Excel para ver todas.", small))
        else:
            story.append(Paragraph("Sem dados.", small))
        story.append(Spacer(1, 0.6 * cm))
    doc.build(story)
    return buf.getvalue()
