#!/usr/bin/env python3
"""Generate synthetic 'scanned' banking/legal documents for the demo.

Renders HTML through headless Chrome, with CSS that fakes a scan (grayscale,
skew, paper grain, JPEG-ish softness). Ground truth is declared alongside each
document so eval/golden.json can be derived from it rather than hand-typed.

Zero dependencies: Chrome is already on macOS dev machines, and everything else
is stdlib.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
DOCS = ROOT / "docs"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 0 }
* { box-sizing: border-box; margin: 0; padding: 0 }
body {
  width: 1240px; min-height: 1754px; background: #fff; padding: 72px 84px;
  font: 15px/1.55 "Times New Roman", Georgia, serif; color: #111;
  /* fake the scan */
  filter: grayscale(1) contrast(1.08) brightness(0.99) blur(0.35px);
}
.skew { transform: rotate(-0.5deg); transform-origin: 50% 0 }
.grain {
  position: fixed; inset: 0; pointer-events: none; opacity: .055;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence baseFrequency='0.85' numOctaves='3'/></filter><rect width='120' height='120' filter='url(%23n)'/></svg>");
}
.hdr { display: flex; justify-content: space-between; align-items: flex-end;
       border-bottom: 2.5px solid #111; padding-bottom: 12px; margin-bottom: 26px }
.bank { font: 700 27px/1 Helvetica, Arial, sans-serif; letter-spacing: -.5px }
.bank small { display: block; font: 400 11px/1.4 Helvetica, Arial, sans-serif;
              letter-spacing: 2.4px; margin-top: 5px; text-transform: uppercase }
.meta { text-align: right; font-size: 12.5px; line-height: 1.7 }
h1 { font: 700 20px/1.3 Helvetica, Arial, sans-serif; margin: 26px 0 14px;
     text-transform: uppercase; letter-spacing: .6px }
h2 { font: 700 14.5px/1.3 Helvetica, Arial, sans-serif; margin: 20px 0 7px }
p { margin-bottom: 10px; text-align: justify }
.kv { width: 100%; border-collapse: collapse; margin: 14px 0 20px }
.kv td { padding: 7px 10px; border-bottom: 1px solid #c8c8c8; font-size: 13.5px; vertical-align: top }
.kv td:first-child { width: 34%; font-weight: 700; background: #f1f1f1 }
table.tx { width: 100%; border-collapse: collapse; margin: 12px 0 18px; font-size: 12.5px }
table.tx th { background: #1d1d1d; color: #fff; padding: 8px 9px; text-align: left;
              font: 700 11.5px Helvetica, Arial, sans-serif; text-transform: uppercase; letter-spacing: .4px }
table.tx td { padding: 7px 9px; border-bottom: 1px solid #d5d5d5 }
table.tx td.n { text-align: right; font-family: "Courier New", monospace }
table.tx tr.tot td { border-top: 2px solid #111; border-bottom: none;
                     font-weight: 700; padding-top: 10px }
.stamp { position: absolute; right: 95px; top: 1210px; width: 215px; height: 215px;
         border: 4px double #333; border-radius: 50%; transform: rotate(-16deg);
         display: flex; flex-direction: column; align-items: center; justify-content: center;
         text-align: center; font: 700 12px/1.45 Helvetica, Arial, sans-serif;
         color: #333; opacity: .62; letter-spacing: 1px }
.sig { margin-top: 44px; display: flex; gap: 70px }
.sig div { flex: 1; border-top: 1px solid #111; padding-top: 7px; font-size: 11.5px }
.sig i { display: block; font: italic 25px/1 "Snell Roundhand", "Brush Script MT", cursive;
         margin-bottom: 7px; transform: rotate(-2.5deg) }
.fine { font-size: 11px; color: #3a3a3a; margin-top: 26px; line-height: 1.5 }
.clause { margin-bottom: 13px; font-size: 13.5px }
.clause b { display: inline-block; min-width: 34px }
"""


def page(body, extra=""):
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><style>%s%s</style></head>"
            "<body><div class='grain'></div><div class='skew'>%s</div></body></html>"
            % (CSS, extra, body))


# ---------------------------------------------------------------- documents ---
DOCUMENTS = []

# 1. Bank statement -----------------------------------------------------------
TX = [
    ("02/07/2026", "Transferencia recibida - NOMINA JULIO", "", "3.412,00", "8.067,45"),
    ("05/07/2026", "Recibo hipoteca prest. 0098-4471", "1.284,36", "", "6.783,09"),
    ("07/07/2026", "Comision mantenimiento cuenta", "18,50", "", "6.764,59"),
    ("11/07/2026", "Pago tarjeta **** 4412 - SUPERCOR", "212,88", "", "6.551,71"),
    ("14/07/2026", "Transferencia emitida - ALQUILER", "950,00", "", "5.601,71"),
    ("18/07/2026", "Comision descubierto", "42,00", "", "5.559,71"),
    ("22/07/2026", "Abono intereses cuenta remunerada", "", "14,22", "5.573,93"),
    ("25/07/2026", "Pago domiciliado - IBERDROLA", "127,40", "", "5.446,53"),
    ("29/07/2026", "Comision transferencia internacional", "31,00", "", "5.415,53"),
    ("31/07/2026", "Liquidacion comisiones trimestre", "24,75", "", "5.390,78"),
]
rows = "".join(
    "<tr><td>%s</td><td>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n'>%s</td></tr>"
    % t for t in TX)
DOCUMENTS.append(dict(
    id="stmt-2026-07",
    name="Extracto Bancario - Julio 2026",
    doc_type="bank_statement",
    html=page("""
    <div class='hdr'><div class='bank'>BANCO MERIDIANO<small>Banca Privada</small></div>
      <div class='meta'><b>EXTRACTO DE CUENTA</b><br>Periodo: 01/07/2026 - 31/07/2026<br>
      Pagina 1 de 1<br>Emitido: 03/08/2026</div></div>
    <table class='kv'>
      <tr><td>Titular</td><td>MARTA ELENA RUIZ SANTOS</td></tr>
      <tr><td>NIF</td><td>52410887M</td></tr>
      <tr><td>IBAN</td><td>ES9121000418450200051332</td></tr>
      <tr><td>Oficina</td><td>0418 - Barcelona Diagonal</td></tr>
      <tr><td>Saldo inicial</td><td>4.655,45 EUR</td></tr>
    </table>
    <h1>Movimientos del periodo</h1>
    <table class='tx'>
      <tr><th>Fecha</th><th>Concepto</th><th style='text-align:right'>Debe</th>
          <th style='text-align:right'>Haber</th><th style='text-align:right'>Saldo</th></tr>
      %s
      <tr class='tot'><td colspan='2'>TOTALES DEL PERIODO</td><td class='n'>2.690,89</td>
          <td class='n'>3.426,22</td><td class='n'>5.390,78</td></tr>
    </table>
    <h2>Resumen de comisiones aplicadas</h2>
    <table class='kv'>
      <tr><td>Total comisiones periodo</td><td>116,25 EUR</td></tr>
      <tr><td>Saldo final</td><td>5.390,78 EUR</td></tr>
    </table>
    <div class='fine'>Documento generado automaticamente. Las comisiones se liquidan conforme
    al contrato marco de cuenta. Para reclamaciones dispone de 60 dias naturales desde la
    fecha de emision.</div>""" % rows),
    truth=dict(
        iban="ES9121000418450200051332",
        holder="MARTA ELENA RUIZ SANTOS",
        nif="52410887M",
        period_start="2026-07-01",
        period_end="2026-07-31",
        opening_balance=4655.45,
        closing_balance=5390.78,
        total_debit=2690.89,
        total_credit=3426.22,
        total_fees=116.25,
    ),
))

# 2. Loan contract ------------------------------------------------------------
DOCUMENTS.append(dict(
    id="loan-0098-4471",
    name="Contrato de Prestamo Hipotecario",
    doc_type="loan_contract",
    html=page("""
    <div class='hdr'><div class='bank'>BANCO MERIDIANO<small>Banca Privada</small></div>
      <div class='meta'><b>CONTRATO DE PRESTAMO</b><br>Ref. 0098-4471<br>
      Barcelona, 14 de marzo de 2024</div></div>
    <h1>Contrato de prestamo con garantia hipotecaria</h1>
    <h2>Intervinientes</h2>
    <table class='kv'>
      <tr><td>Prestamista</td><td>BANCO MERIDIANO S.A. - CIF A58923471</td></tr>
      <tr><td>Prestatario</td><td>MARTA ELENA RUIZ SANTOS - NIF 52410887M</td></tr>
      <tr><td>Cuenta de cargo (IBAN)</td><td>ES9121000418450200051332</td></tr>
    </table>
    <h2>Condiciones economicas</h2>
    <table class='kv'>
      <tr><td>Capital concedido</td><td>245.000,00 EUR</td></tr>
      <tr><td>Plazo</td><td>300 meses (25 anos)</td></tr>
      <tr><td>Tipo de interes</td><td>Variable - EURIBOR 12M + 0,89%</td></tr>
      <tr><td>Tipo inicial (12 primeros meses)</td><td>2,45% nominal anual</td></tr>
      <tr><td>Cuota mensual inicial</td><td>1.284,36 EUR</td></tr>
      <tr><td>TAE</td><td>2,71%</td></tr>
      <tr><td>Comision de apertura</td><td>0,50% (1.225,00 EUR)</td></tr>
    </table>
    <h2>Clausulas</h2>
    <div class='clause'><b>4.1</b> El prestatario podra amortizar anticipadamente,
      total o parcialmente, el capital pendiente, con un preaviso minimo de quince (15) dias
      naturales.</div>
    <div class='clause'><b>4.2</b> La amortizacion anticipada devengara una
      <b style='min-width:0'>compensacion del 0,25%</b> sobre el capital reembolsado
      anticipadamente, aplicable unicamente durante los tres (3) primeros anos de vigencia
      del contrato. Transcurrido dicho plazo, la amortizacion anticipada no devengara
      compensacion alguna.</div>
    <div class='clause'><b>5.1</b> El impago de dos (2) cuotas consecutivas facultara al
      prestamista para declarar el vencimiento anticipado del prestamo.</div>
    <div class='clause'><b>5.2</b> Los intereses de demora se fijan en el interes
      remuneratorio incrementado en tres (3) puntos porcentuales.</div>
    <div class='clause'><b>7.3</b> El prestatario se obliga a mantener domiciliada su nomina
      en la entidad. El incumplimiento supondra un incremento de 0,30 puntos en el
      diferencial aplicable.</div>
    <div class='stamp'>BANCO<br>MERIDIANO<br>- - -<br>INTERVENIDO<br>14 MAR 2024</div>
    <div class='sig'>
      <div><i>M. Ruiz</i>El prestatario<br>MARTA ELENA RUIZ SANTOS</div>
      <div><i>J. Alarcon</i>P.P. El prestamista<br>BANCO MERIDIANO S.A.</div>
    </div>"""),
    truth=dict(
        contract_ref="0098-4471",
        borrower="MARTA ELENA RUIZ SANTOS",
        nif="52410887M",
        iban="ES9121000418450200051332",
        principal=245000.00,
        term_months=300,
        rate_type="variable",
        spread="0,89%",
        monthly_payment=1284.36,
        apr="2,71%",
        early_repayment_penalty="0,25% during first 3 years, none thereafter",
        signature_present=True,
        stamp_present=True,
    ),
))

# 3. Mortgage deed (for the cross-document comparison demo) -------------------
# NOTE: principal here is 245.000,00 but the monthly payment is stated as
# 1.248,36 -- a transposed-digit mismatch vs. the contract's 1.284,36.
# This is deliberate: it is the cross-document inconsistency the demo finds.
DOCUMENTS.append(dict(
    id="deed-4471",
    name="Escritura de Prestamo Hipotecario",
    doc_type="mortgage_deed",
    html=page("""
    <div class='hdr'><div class='bank' style='font-size:22px'>NOTARIA DE BARCELONA
      <small>Ilmo. Sr. D. Ramon Puig Ferrer - Notario</small></div>
      <div class='meta'><b>ESCRITURA PUBLICA</b><br>Protocolo 1.482/2024<br>
      Barcelona, 14 de marzo de 2024</div></div>
    <h1>Escritura de prestamo con garantia hipotecaria</h1>
    <p>En Barcelona, mi residencia, a catorce de marzo de dos mil veinticuatro, ante mi,
    RAMON PUIG FERRER, Notario del Ilustre Colegio de Catalunya, COMPARECEN:</p>
    <p>De una parte, <b>BANCO MERIDIANO S.A.</b>, con CIF A58923471, representada por
    D. JAVIER ALARCON MOLINA. De otra parte, Dna. <b>MARTA ELENA RUIZ SANTOS</b>,
    con NIF 52410887M, mayor de edad, de nacionalidad espanola.</p>
    <h2>Objeto</h2>
    <table class='kv'>
      <tr><td>Finca registral</td><td>N. 24.881 - Registro de la Propiedad n.8 de Barcelona</td></tr>
      <tr><td>Domicilio</td><td>C/ Provenca 287, 4o 2a, 08008 Barcelona</td></tr>
      <tr><td>Referencia catastral</td><td>8842701DF2884S0014WR</td></tr>
      <tr><td>Valor de tasacion</td><td>352.000,00 EUR</td></tr>
      <tr><td>Capital del prestamo</td><td>245.000,00 EUR</td></tr>
      <tr><td>Cuota mensual</td><td>1.248,36 EUR</td></tr>
      <tr><td>Plazo</td><td>300 meses</td></tr>
      <tr><td>Responsabilidad hipotecaria total</td><td>294.000,00 EUR</td></tr>
    </table>
    <p class='fine'>Y yo, el Notario, DOY FE de que el consentimiento ha sido libremente
    prestado, que el otorgamiento se adecua a la legalidad y a la voluntad debidamente
    informada de los intervinientes.</p>
    <div class='stamp' style='top:1130px'>NOTARIA<br>PUIG FERRER<br>- - -<br>PROTOCOLO<br>1.482/2024</div>
    <div class='sig'>
      <div><i>R. Puig</i>El Notario</div>
      <div><i>M. Ruiz</i>La prestataria</div>
    </div>"""),
    truth=dict(
        protocol="1.482/2024",
        borrower="MARTA ELENA RUIZ SANTOS",
        nif="52410887M",
        principal=245000.00,
        monthly_payment=1248.36,          # mismatch vs loan contract, on purpose
        term_months=300,
        appraisal_value=352000.00,
        property="C/ Provenca 287, 4o 2a, 08008 Barcelona",
        cadastral_ref="8842701DF2884S0014WR",
    ),
))


def render(doc):
    DOCS.mkdir(parents=True, exist_ok=True)
    html = DOCS / ("%s.html" % doc["id"])
    png = DOCS / ("%s.png" % doc["id"])
    html.write_text(doc["html"], encoding="utf-8")
    subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", "--window-size=1240,1754",
         "--screenshot=%s" % png, "--virtual-time-budget=1800", html.as_uri()],
        check=True, capture_output=True, timeout=90)
    html.unlink()
    return png


def main():
    if not pathlib.Path(CHROME).exists():
        sys.exit("Chrome not found at %s" % CHROME)
    manifest = []
    for d in DOCUMENTS:
        png = render(d)
        manifest.append(dict(id=d["id"], name=d["name"], doc_type=d["doc_type"],
                             image=png.name, truth=d["truth"]))
        print("  rendered %-18s %7d bytes  %s" % (d["id"], png.stat().st_size, png.name))
    (DOCS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
    print("  manifest: %s (%d documents)" % (DOCS / "manifest.json", len(manifest)))


if __name__ == "__main__":
    main()
