"""
pdf_generator.py — Génération PDF avec ReportLab (fpdf2 en fallback)
"""
import os
from config import (INVOICES_DIR, SHOP_NAME, SHOP_ADDRESS,
                    SHOP_PHONE, SHOP_EMAIL, LOGO_PATH, CURRENCY)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, HRFlowable)
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    PDF_ENGINE = "reportlab"
except ImportError:
    PDF_ENGINE = "none"

try:
    from fpdf import FPDF
    if PDF_ENGINE == "none":
        PDF_ENGINE = "fpdf2"
except ImportError:
    pass


def _ps(name, size=10, color="#1e1e1e", align="LEFT", bold=False, leading=None):
    """Crée un ParagraphStyle ReportLab."""
    al = {"LEFT": TA_LEFT, "CENTER": TA_CENTER, "RIGHT": TA_RIGHT}.get(align, TA_LEFT)
    c = colors.HexColor(color) if color.startswith("#") else colors.white
    return ParagraphStyle(
        name, fontSize=size, textColor=c, alignment=al,
        leading=leading or size * 1.5
    )


def _rl_invoice(sale, items, client):
    invoice_number = sale.get("invoice_number", "0000")
    sale_date = str(sale.get("sale_date", ""))[:10]
    filepath = os.path.join(INVOICES_DIR, f"facture_{invoice_number}.pdf")
    os.makedirs(INVOICES_DIR, exist_ok=True)

    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm, bottomMargin=1.5*cm)
    BLUE = colors.HexColor("#1a73e8")
    LBLUE = colors.HexColor("#e8f0fe")
    GRAY = colors.HexColor("#666666")
    ALT = colors.HexColor("#f8f9fc")
    story = []

    # En-tête : 2 colonnes
    hdr = Table([[
        Paragraph(
            f'<font color="#1a73e8" size="17"><b>{SHOP_NAME}</b></font><br/>'
            f'<font color="#666" size="8">{SHOP_ADDRESS}</font><br/>'
            f'<font color="#666" size="8">Tél : {SHOP_PHONE} | {SHOP_EMAIL}</font>',
            _ps("h_left", 9, leading=14)
        ),
        Paragraph(
            f'<font color="#1a73e8" size="20"><b>FACTURE</b></font><br/>'
            f'<font color="#1e1e1e" size="14"><b>#{invoice_number}</b></font><br/>'
            f'<font color="#666" size="9">Date : {sale_date}</font>',
            _ps("h_right", 9, align="RIGHT", leading=18)
        )
    ]], colWidths=[10*cm, 8*cm])
    hdr.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=8))

    # Client
    cn = client.get("name", "Client divers")
    cp = client.get("phone", "")
    ca = client.get("address", "")
    lines = f"<b>FACTURÉ À :</b><br/><b>{cn}</b>"
    if cp: lines += f"<br/>Tél : {cp}"
    if ca: lines += f"<br/>{ca}"
    ct = Table([[Paragraph(lines, _ps("cl", 10, leading=16))]],
               colWidths=[18*cm])
    ct.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), LBLUE),
        ("TOPPADDING",(0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",(0,0),(-1,-1), 12),
    ]))
    story.append(ct)
    story.append(Spacer(1, 10))

    # Tableau articles
    W = [8.5*cm, 2*cm, 3.5*cm, 4*cm]
    thead = [Paragraph(f"<b>{t}</b>", _ps(f"th{i}", 10, color="white", align=a))
             for i,(t,a) in enumerate([("Désignation","LEFT"),("Qté","CENTER"),
                                        (f"P.U.({CURRENCY})","RIGHT"),(f"Total({CURRENCY})","RIGHT")])]
    rows = [thead]
    for i, item in enumerate(items):
        rows.append([
            Paragraph(str(item.get("part_name","")), _ps(f"td0{i}", 9)),
            Paragraph(str(item.get("quantity","")), _ps(f"td1{i}", 9, align="CENTER")),
            Paragraph(f"{item.get('unit_price',0):,.2f}", _ps(f"td2{i}", 9, align="RIGHT")),
            Paragraph(f"{item.get('total',0):,.2f}", _ps(f"td3{i}", 9, align="RIGHT")),
        ])
    ts = [
        ("BACKGROUND",(0,0),(-1,0), BLUE), ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("LINEBELOW",(0,1),(-1,-1), 0.3, colors.HexColor("#dddddd")),
        ("TOPPADDING",(0,0),(-1,-1), 6), ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING",(0,0),(0,-1), 8), ("RIGHTPADDING",(-1,0),(-1,-1), 8),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0: ts.append(("BACKGROUND",(0,i),(-1,i), ALT))
    at = Table(rows, colWidths=W, repeatRows=1)
    at.setStyle(TableStyle(ts))
    story.append(at)
    story.append(Spacer(1, 8))

    # Total
    ttable = Table([[
        Paragraph(f"Mode de paiement : <b>{sale.get('payment_method','Espèces')}</b>",
                  _ps("pm", 10, color="white", leading=14)),
        Paragraph(f"<b>TOTAL : {sale.get('total_amount',0):,.2f} {CURRENCY}</b>",
                  _ps("tot", 12, color="white", align="RIGHT", leading=14))
    ]], colWidths=[10*cm, 8*cm])
    ttable.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), BLUE),
        ("TOPPADDING",(0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",(0,0),(0,-1), 12), ("RIGHTPADDING",(-1,0),(-1,-1), 12),
    ]))
    story.append(ttable)
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    story.append(Paragraph(
        f"Merci pour votre confiance — {SHOP_NAME} | {SHOP_PHONE} | {SHOP_EMAIL}",
        _ps("footer", 8, color="#888888", align="CENTER")
    ))
    doc.build(story)
    return filepath


def _rl_purchase_order(order, items):
    order_id = order.get("id", 0)
    filepath = os.path.join(INVOICES_DIR, f"bc_{order_id:04d}.pdf")
    os.makedirs(INVOICES_DIR, exist_ok=True)
    doc = SimpleDocTemplate(filepath, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=1.5*cm, bottomMargin=1.5*cm)
    BLUE = colors.HexColor("#1a73e8")
    LBLUE = colors.HexColor("#e8f0fe")
    GRAY = colors.HexColor("#666666")
    ALT = colors.HexColor("#f8f9fc")
    story = []

    hdr = Table([[
        Paragraph(
            f'<font color="#1a73e8" size="17"><b>{SHOP_NAME}</b></font><br/>'
            f'<font color="#666" size="8">{SHOP_ADDRESS} | {SHOP_PHONE}</font>',
            _ps("bch", 9, leading=14)
        ),
        Paragraph(
            f'<font color="#1a73e8" size="20"><b>BON DE COMMANDE</b></font><br/>'
            f'<font color="#1e1e1e" size="14"><b>#BC{order_id:04d}</b></font><br/>'
            f'<font color="#666" size="9">Date : {str(order.get("order_date",""))[:10]}</font>',
            _ps("bchr", 9, align="RIGHT", leading=18)
        )
    ]], colWidths=[10*cm, 8*cm])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=8))

    sup = Table([[Paragraph(
        f"<b>FOURNISSEUR :</b><br/><b>{order.get('supplier_name','')}</b>",
        _ps("supbl", 11, leading=18)
    )]], colWidths=[18*cm])
    sup.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), LBLUE),
        ("TOPPADDING",(0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",(0,0),(-1,-1), 12),
    ]))
    story.append(sup)
    story.append(Spacer(1, 10))

    W = [8.5*cm, 2*cm, 3.5*cm, 4*cm]
    thead = [Paragraph(f"<b>{t}</b>", _ps(f"bth{i}", 10, color="white", align=a))
             for i,(t,a) in enumerate([("Désignation","LEFT"),("Qté","CENTER"),
                                        (f"P.U.({CURRENCY})","RIGHT"),(f"Total({CURRENCY})","RIGHT")])]
    rows = [thead]
    for i, item in enumerate(items):
        rows.append([
            Paragraph(str(item.get("part_name","")), _ps(f"btd0{i}", 9)),
            Paragraph(str(item.get("quantity","")), _ps(f"btd1{i}", 9, align="CENTER")),
            Paragraph(f"{item.get('unit_price',0):,.2f}", _ps(f"btd2{i}", 9, align="RIGHT")),
            Paragraph(f"{item.get('total',0):,.2f}", _ps(f"btd3{i}", 9, align="RIGHT")),
        ])
    ts = [
        ("BACKGROUND",(0,0),(-1,0), BLUE), ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("LINEBELOW",(0,1),(-1,-1), 0.3, colors.HexColor("#dddddd")),
        ("TOPPADDING",(0,0),(-1,-1), 6), ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING",(0,0),(0,-1), 8), ("RIGHTPADDING",(-1,0),(-1,-1), 8),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0: ts.append(("BACKGROUND",(0,i),(-1,i), ALT))
    at = Table(rows, colWidths=W, repeatRows=1)
    at.setStyle(TableStyle(ts))
    story.append(at)
    story.append(Spacer(1, 8))

    tt = Table([[
        Paragraph("", _ps("emp", 9)),
        Paragraph(f"<b>TOTAL : {order.get('total_amount',0):,.2f} {CURRENCY}</b>",
                  _ps("bctot", 13, color="white", align="RIGHT", leading=16))
    ]], colWidths=[10*cm, 8*cm])
    tt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), BLUE),
        ("TOPPADDING",(0,0),(-1,-1), 8), ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("RIGHTPADDING",(-1,0),(-1,-1), 12),
    ]))
    story.append(tt)
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY))
    story.append(Paragraph(
        f"{SHOP_NAME} — {SHOP_ADDRESS}",
        _ps("bcfooter", 8, color="#888888", align="CENTER")
    ))
    doc.build(story)
    return filepath


def _fpdf_invoice(sale, items, client):
    invoice_number = sale.get("invoice_number", "0000")
    sale_date = str(sale.get("sale_date", ""))[:10]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page(); pdf.set_margins(15, 15, 15)
    pdf.set_font("Helvetica", "B", 18); pdf.set_text_color(26,115,232)
    pdf.cell(0, 10, SHOP_NAME, ln=True)
    pdf.set_font("Helvetica", "", 9); pdf.set_text_color(100,100,100)
    pdf.cell(0, 5, SHOP_ADDRESS, ln=True)
    pdf.cell(0, 5, f"Tel: {SHOP_PHONE} | {SHOP_EMAIL}", ln=True)
    pdf.set_draw_color(26,115,232); pdf.set_line_width(0.8)
    pdf.line(15, pdf.get_y()+3, 195, pdf.get_y()+3); pdf.ln(8)
    pdf.set_font("Helvetica","B",20); pdf.set_text_color(30,30,30)
    pdf.cell(0,12,f"FACTURE #{invoice_number}", ln=True, align="R")
    pdf.set_font("Helvetica","",10); pdf.set_text_color(100,100,100)
    pdf.cell(0,6,f"Date : {sale_date}", ln=True, align="R"); pdf.ln(4)
    pdf.set_fill_color(232,240,254); pdf.set_font("Helvetica","B",10)
    pdf.set_text_color(26,115,232)
    pdf.cell(0,8,f"  FACTURE A : {client.get('name','Client divers')}", ln=True, fill=True)
    pdf.set_font("Helvetica","",9); pdf.set_text_color(80,80,80)
    if client.get("phone"): pdf.cell(0,5,f"  Tel: {client['phone']}", ln=True)
    pdf.ln(6)
    pdf.set_fill_color(26,115,232); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",10)
    for h,w in [("Designation",80),("Qte",25),(f"P.U.({CURRENCY})",40),(f"Total({CURRENCY})",40)]:
        pdf.cell(w,9,h,fill=True,align="C")
    pdf.ln()
    pdf.set_text_color(30,30,30); pdf.set_font("Helvetica","",9)
    for i,item in enumerate(items):
        pdf.set_fill_color(255,255,255) if i%2==0 else pdf.set_fill_color(248,249,252)
        pdf.cell(80,8,f"  {item['part_name']}",border="B",fill=True)
        pdf.cell(25,8,str(item["quantity"]),border="B",fill=True,align="C")
        pdf.cell(40,8,f"{item['unit_price']:,.2f}",border="B",fill=True,align="R")
        pdf.cell(40,8,f"{item['total']:,.2f}",border="B",fill=True,align="R"); pdf.ln()
    pdf.ln(4)
    pdf.set_fill_color(26,115,232); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",12)
    pdf.cell(145,10,f"Paiement: {sale.get('payment_method','')}",fill=True)
    pdf.cell(40,10,f"TOTAL: {sale.get('total_amount',0):,.2f} {CURRENCY}",fill=True,align="R",ln=True)
    filepath = os.path.join(INVOICES_DIR, f"facture_{invoice_number}.pdf")
    pdf.output(filepath)
    return filepath


def _fpdf_purchase_order(order, items):
    order_id = order.get("id", 0)
    pdf = FPDF(); pdf.add_page(); pdf.set_margins(15,15,15)
    pdf.set_font("Helvetica","B",16); pdf.set_text_color(26,115,232)
    pdf.cell(0,10,SHOP_NAME,ln=True)
    pdf.set_font("Helvetica","B",18); pdf.set_text_color(30,30,30)
    pdf.cell(0,12,f"BON DE COMMANDE #BC{order_id:04d}",ln=True,align="R")
    pdf.set_font("Helvetica","",10); pdf.set_text_color(100,100,100)
    pdf.cell(0,6,f"Fournisseur: {order.get('supplier_name','')}",ln=True); pdf.ln(4)
    pdf.set_fill_color(26,115,232); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",10)
    for h,w in [("Designation",80),("Qte",25),(f"P.U.({CURRENCY})",40),(f"Total({CURRENCY})",40)]:
        pdf.cell(w,9,h,fill=True,align="C")
    pdf.ln(); pdf.set_text_color(30,30,30); pdf.set_font("Helvetica","",9)
    for item in items:
        pdf.cell(80,8,f"  {item['part_name']}",border="B")
        pdf.cell(25,8,str(item["quantity"]),border="B",align="C")
        pdf.cell(40,8,f"{item['unit_price']:,.2f}",border="B",align="R")
        pdf.cell(40,8,f"{item['total']:,.2f}",border="B",align="R"); pdf.ln()
    pdf.ln(4); pdf.set_fill_color(26,115,232); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",12)
    pdf.cell(185,10,f"TOTAL: {order.get('total_amount',0):,.2f} {CURRENCY}",fill=True,align="R",ln=True)
    filepath = os.path.join(INVOICES_DIR, f"bc_{order_id:04d}.pdf")
    pdf.output(filepath)
    return filepath


def generate_invoice_pdf(sale: dict, items: list, client: dict) -> str:
    os.makedirs(INVOICES_DIR, exist_ok=True)
    if PDF_ENGINE == "reportlab":
        return _rl_invoice(sale, items, client)
    elif PDF_ENGINE == "fpdf2":
        return _fpdf_invoice(sale, items, client)
    raise RuntimeError("Aucune bibliothèque PDF disponible (fpdf2 ou reportlab).")


def generate_purchase_order_pdf(order: dict, items: list) -> str:
    os.makedirs(INVOICES_DIR, exist_ok=True)
    if PDF_ENGINE == "reportlab":
        return _rl_purchase_order(order, items)
    elif PDF_ENGINE == "fpdf2":
        return _fpdf_purchase_order(order, items)
    raise RuntimeError("Aucune bibliothèque PDF disponible (fpdf2 ou reportlab).")
