"""Create the mock booking request used by the interactive SQL agent demo."""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas


target = Path(__file__).resolve().parents[1] / "examples" / "sql-user-demo" / "booking-request.pdf"
target.parent.mkdir(parents=True, exist_ok=True)

pdf = canvas.Canvas(str(target), pagesize=(612, 792))
pdf.setTitle("Mock booking request BR-1042")
pdf.setAuthor("Mangekyo Agent demo")
pdf.setFillColor(HexColor("#B44370"))
pdf.rect(0, 748, 612, 44, fill=1, stroke=0)
pdf.setFillColor(HexColor("#FFFFFF"))
pdf.setFont("Helvetica-Bold", 16)
pdf.drawString(48, 763, "BOOKING REQUEST")
pdf.setFillColor(HexColor("#423D40"))
pdf.setFont("Helvetica-Bold", 22)
pdf.drawString(48, 682, "Toronto bookings count")
pdf.setFont("Helvetica", 11)
pdf.drawString(48, 648, "Reference: BR-1042")
pdf.drawString(48, 624, "Question: Count Toronto bookings")
pdf.drawString(48, 600, "Source table: bookings")
pdf.drawString(48, 576, "Expected count: 3")
pdf.setFillColor(HexColor("#F9F1F5"))
pdf.roundRect(48, 472, 516, 72, 8, fill=1, stroke=0)
pdf.setFillColor(HexColor("#6D5864"))
pdf.setFont("Helvetica-Bold", 11)
pdf.drawString(64, 518, "Review note")
pdf.setFont("Helvetica", 10)
pdf.drawString(64, 495, "The invoices table has one Toronto row. Count bookings, not invoices.")
pdf.setFillColor(HexColor("#968791"))
pdf.setFont("Helvetica", 9)
pdf.drawString(48, 48, "Synthetic data for a local agent recovery demonstration - no real customers.")
pdf.showPage()
pdf.save()
print(target)
