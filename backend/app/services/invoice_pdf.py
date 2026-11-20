from __future__ import annotations

from fpdf import FPDF

from app.models import Invoice


def _money(c: int) -> str:
    return f"${c / 100:,.2f}"


def render_invoice_pdf(inv: Invoice, client_name: str, agency_name: str) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, agency_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, f"Invoice {inv.number}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Bill to: {client_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Issued {inv.issue_date.isoformat()}   Due {inv.due_date.isoformat()}   Terms {inv.payment_terms}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    for w, h in ((100, "Description"), (20, "Qty"), (35, "Unit"), (35, "Amount")):
        pdf.cell(w, 8, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    for li in inv.line_items:
        pdf.cell(100, 8, str(li["description"])[:60], border=1)
        pdf.cell(20, 8, str(li["quantity"]), border=1)
        pdf.cell(35, 8, _money(li["unit_price_cents"]), border=1)
        pdf.cell(35, 8, _money(round(li["quantity"] * li["unit_price_cents"])), border=1)
        pdf.ln()
    pdf.ln(2)
    for label, val in (("Subtotal", inv.subtotal_cents), (f"Tax ({inv.tax_rate:.2%})", inv.tax_cents),
                       ("Total", inv.total_cents), ("Paid", inv.paid_cents), ("Balance due", inv.total_cents - inv.paid_cents)):
        pdf.cell(155, 7, label, align="R")
        pdf.cell(35, 7, _money(val), align="R", new_x="LMARGIN", new_y="NEXT")
    if inv.memo:
        pdf.ln(4)
        pdf.multi_cell(0, 6, inv.memo)
    return bytes(pdf.output())
