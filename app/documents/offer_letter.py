"""Renders an offer letter as a self-contained, printable HTML page (browser: Print -> Save as PDF)."""
from decimal import Decimal
from html import escape
from typing import List, Optional

from app.core.config import settings
from app.models.offer_letter import OfferLetter, OfferLetterStatus
from app.models.payroll import ComponentType
from app.repositories.offer_letter_repository import components_of


def _inr(value) -> str:
    """Indian digit grouping, e.g. 1234567.5 -> 12,34,567.50"""
    amount = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}&#8377;{whole}.{frac}"


def _date(d) -> str:
    return d.strftime("%d %B %Y") if d else ""


def _e(v: Optional[str]) -> str:
    return escape(v or "")


def _rows(items: List[dict]) -> str:
    return "".join(
        f"<tr><td>{_e(c['name'])}</td><td class='num'>{_inr(c['monthly'])}</td>"
        f"<td class='num'>{_inr(c['annual'])}</td></tr>"
        for c in items
    )


def render_offer_letter(letter: OfferLetter) -> str:
    provisional = letter.status == OfferLetterStatus.PROVISIONAL
    title = "Provisional Offer Letter" if provisional else "Offer Letter"
    earnings = components_of(letter, ComponentType.EARNING)
    deductions = components_of(letter, ComponentType.DEDUCTION)

    if letter.joining_date:
        joining = f"Your date of joining is <strong>{_date(letter.joining_date)}</strong>."
    elif letter.tentative_joining_date:
        joining = (
            f"Your tentative date of joining is <strong>{_date(letter.tentative_joining_date)}</strong>. "
            "The final date of joining will be confirmed in your offer letter."
        )
    else:
        joining = "Your date of joining will be confirmed in your offer letter."

    location = f" at our <strong>{_e(letter.work_location)}</strong> location" if letter.work_location else ""
    department = f" in the <strong>{_e(letter.department)}</strong> department" if letter.department else ""
    validity = (
        f"<p>This offer is valid until <strong>{_date(letter.valid_until)}</strong>. "
        "Please confirm your acceptance by that date.</p>"
        if letter.valid_until else ""
    )
    provisional_note = (
        "<p class='note'>This is a provisional offer. It discloses the compensation offered to you; "
        "your date of joining will be confirmed in the final offer letter.</p>"
        if provisional else ""
    )
    withdrawn = (
        f"<div class='withdrawn'>WITHDRAWN on {_date(letter.withdrawn_at)}</div>"
        if letter.status == OfferLetterStatus.WITHDRAWN else ""
    )
    terms = f"<h3>Terms</h3><p class='terms'>{_e(letter.terms)}</p>" if letter.terms else ""
    deduction_rows = (
        f"<tr class='section'><td colspan='3'>Deductions</td></tr>{_rows(deductions)}"
        f"<tr class='total'><td>Total deductions</td><td class='num'>{_inr(letter.monthly_deductions)}</td>"
        f"<td class='num'>{_inr(Decimal(letter.monthly_deductions) * 12)}</td></tr>"
        if deductions else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - {_e(letter.letter_number)}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; color: #222; background: #fff;
         max-width: 780px; margin: 32px auto; padding: 0 24px; line-height: 1.55; }}
  header {{ border-bottom: 2px solid #222; padding-bottom: 12px; margin-bottom: 24px; }}
  header h1 {{ margin: 0; font-size: 22px; }}
  header p {{ margin: 4px 0 0; color: #555; font-size: 13px; white-space: pre-line; }}
  h2 {{ text-align: center; text-transform: uppercase; letter-spacing: 1px; font-size: 17px; }}
  .meta {{ display: flex; justify-content: space-between; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #bbb; padding: 6px 10px; text-align: left; }}
  th {{ background: #f2f2f2; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .section td {{ background: #fafafa; font-weight: bold; }}
  .total td {{ font-weight: bold; }}
  .grand td {{ font-weight: bold; background: #f2f2f2; }}
  .note {{ font-style: italic; color: #555; }}
  .terms {{ white-space: pre-line; }}
  .withdrawn {{ border: 3px solid #b00; color: #b00; text-align: center; font-weight: bold;
                padding: 8px; margin-bottom: 16px; letter-spacing: 2px; }}
  .sign {{ margin-top: 56px; display: flex; justify-content: space-between; }}
  @media print {{ body {{ margin: 0 auto; }} }}
</style>
</head>
<body>
<header>
  <h1>{_e(settings.COMPANY_NAME)}</h1>
  {f"<p>{_e(settings.COMPANY_ADDRESS)}</p>" if settings.COMPANY_ADDRESS else ""}
</header>
{withdrawn}
<div class="meta"><span>Ref: {_e(letter.letter_number)}</span><span>Date: {_date(letter.offer_date)}</span></div>
<h2>{title}</h2>
<p>Dear {_e(letter.candidate_name)},</p>
<p>We are pleased to offer you the position of <strong>{_e(letter.designation)}</strong>{department}{location}
with {_e(settings.COMPANY_NAME)}. {joining}</p>
<p>Your annual gross compensation will be <strong>{_inr(letter.annual_gross)}</strong>
({_inr(letter.monthly_gross)} per month), structured as follows:</p>
<table>
  <thead><tr><th>Component</th><th class="num">Monthly</th><th class="num">Annual</th></tr></thead>
  <tbody>
    <tr class="section"><td colspan="3">Earnings</td></tr>
    {_rows(earnings)}
    <tr class="total"><td>Gross salary</td><td class="num">{_inr(letter.monthly_gross)}</td>
      <td class="num">{_inr(letter.annual_gross)}</td></tr>
    {deduction_rows}
    <tr class="grand"><td>Net take-home (approx.)</td><td class="num">{_inr(letter.monthly_net)}</td>
      <td class="num">{_inr(Decimal(letter.monthly_net) * 12)}</td></tr>
  </tbody>
</table>
<p>Salary is paid monthly in proportion to the days worked, as per company attendance and leave policy.
Statutory deductions are subject to applicable law.</p>
{provisional_note}
{validity}
{terms}
<p>We look forward to having you on our team.</p>
<div class="sign">
  <div>For {_e(settings.COMPANY_NAME)}<br><br><br>Authorised Signatory</div>
  <div>Accepted by<br><br><br>{_e(letter.candidate_name)}</div>
</div>
</body>
</html>"""
