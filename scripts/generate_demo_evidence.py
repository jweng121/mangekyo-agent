"""Regenerate the small, synthetic evidence bundled with the offline demo."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1] / "mangekyo" / "assets"


def main() -> None:
    pdf = canvas.Canvas(str(ROOT / "demo-instruction.pdf"), pagesize=letter)
    pdf.setTitle("Demo work instruction")
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(70, 700, "Demo work instruction")
    pdf.setFont("Helvetica", 13)
    pdf.drawString(70, 630, "Task: update the disposable target file")
    pdf.drawString(70, 598, "Approved value: safe")
    pdf.drawString(70, 566, "Do not write: unsafe")
    pdf.drawString(70, 510, "This document is a synthetic test fixture.")
    pdf.save()

    image = Image.new("RGB", (900, 480), "#f9f5f7")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 40, 858, 430), radius=22, fill="white", outline="#e6dce1", width=3)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 32)
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 42)
    draw.text((90, 90), "Target state preview", font=bold, fill="#453840")
    draw.text((90, 192), "target.txt", font=font, fill="#65545e")
    draw.rounded_rectangle((85, 254, 810, 348), radius=12, fill="#fcf5f8", outline="#dfb6c9", width=2)
    draw.text((112, 280), "Current value: original", font=font, fill="#8f3158")
    image.save(ROOT / "demo-target.png")


if __name__ == "__main__":
    main()
