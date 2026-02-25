from __future__ import annotations

from io import BytesIO
from typing import Any


class PDFBuilder:
    def __init__(self, user_data: dict[str, Any], metrics: dict[str, Any], book_type: str):
        self.user_data = user_data or {}
        self.metrics = metrics or {}
        self.book_type = book_type

    def build(
        self,
        chapters: list[str],
        motivational_pages: list[str],
        images: dict[str, BytesIO],
    ) -> BytesIO:
        reportlab = self._load_reportlab()
        if not reportlab:
            raise RuntimeError("ReportLab is required to build Journey Book PDFs.")

        A4 = reportlab["A4"]
        HexColor = reportlab["HexColor"]
        TA_CENTER = reportlab["TA_CENTER"]
        TA_JUSTIFY = reportlab["TA_JUSTIFY"]
        TA_LEFT = reportlab["TA_LEFT"]
        inch = reportlab["inch"]
        getSampleStyleSheet = reportlab["getSampleStyleSheet"]
        ParagraphStyle = reportlab["ParagraphStyle"]
        SimpleDocTemplate = reportlab["SimpleDocTemplate"]
        Paragraph = reportlab["Paragraph"]
        Spacer = reportlab["Spacer"]
        PageBreak = reportlab["PageBreak"]
        Table = reportlab["Table"]
        TableStyle = reportlab["TableStyle"]
        HRFlowable = reportlab["HRFlowable"]

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=72,
            rightMargin=72,
            topMargin=72,
            bottomMargin=72,
            title="The Journey",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleStyle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=36,
            leading=42,
            textColor=HexColor("#3D2B1F"),
            alignment=TA_CENTER,
        )
        subtitle_style = ParagraphStyle(
            "SubtitleStyle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=18,
            leading=24,
            textColor=HexColor("#666666"),
            alignment=TA_CENTER,
        )
        chapter_heading_style = ParagraphStyle(
            "ChapterHeadingStyle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=HexColor("#3D2B1F"),
            alignment=TA_LEFT,
        )
        body_style = ParagraphStyle(
            "BodyStyle",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
        )
        quote_style = ParagraphStyle(
            "QuoteStyle",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=12,
            leading=16,
            leftIndent=0.5 * inch,
            textColor=HexColor("#555555"),
        )
        small_caps_style = ParagraphStyle(
            "SmallCapsStyle",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=HexColor("#888888"),
            alignment=TA_LEFT,
        )
        projection_style = ParagraphStyle(
            "ProjectionStyle",
            parent=body_style,
            fontName="Helvetica-Oblique",
        )

        story = []
        self._add_title_page(
            story=story,
            Paragraph=Paragraph,
            Spacer=Spacer,
            subtitle_style=subtitle_style,
            title_style=title_style,
            images=images,
        )
        story.append(PageBreak())
        story.append(Paragraph("For the version of me that chose to continue.", quote_style))
        story.append(Spacer(1, 18))
        story.append(
            Paragraph(
                "Every page in this book asks: what did this cost me, and was it worth it?",
                body_style,
            )
        )

        chapter_titles = self._chapter_titles_for_book_type(self.book_type)
        image_order = ["completion", "sentiment", "heatmap", "wordcloud", "milestone", "streak"]

        for idx, chapter_text in enumerate(chapters, start=1):
            story.append(PageBreak())
            chapter_title = chapter_titles[idx - 1] if idx - 1 < len(chapter_titles) else f"Chapter {idx}"
            story.append(Paragraph(f"CHAPTER {idx}", small_caps_style))
            story.append(Spacer(1, 6))
            story.append(Paragraph(chapter_title, chapter_heading_style))
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#D7C9AA")))
            story.append(Spacer(1, 12))

            image_key = image_order[idx - 1] if idx - 1 < len(image_order) else None
            if image_key and images.get(image_key):
                image_flowable = self._embed_image(images[image_key], width_inches=5.0, reportlab=reportlab)
                if image_flowable:
                    story.append(image_flowable)
                    story.append(Spacer(1, 10))

            if self.book_type == "in_progress" and idx in (4, 5):
                warning_table = Table(
                    [[
                        "PROJECTION - Based on your current trajectory"
                    ]],
                    colWidths=[doc.width],
                )
                warning_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F3F3F3")),
                            ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#666666")),
                            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                story.append(warning_table)
                story.append(Spacer(1, 10))
                self._append_body_paragraphs(story, chapter_text, Paragraph, projection_style)
            else:
                self._append_body_paragraphs(story, chapter_text, Paragraph, body_style)

        for page_text in motivational_pages:
            story.append(PageBreak())
            story.append(Paragraph("MOTIVATIONAL PAGE", small_caps_style))
            story.append(Spacer(1, 8))
            self._append_body_paragraphs(story, page_text, Paragraph, body_style)

        story.append(PageBreak())
        story.append(Paragraph("Appendix", chapter_heading_style))
        story.append(Spacer(1, 10))

        goal_table = self._append_goal_summary_table(
            story=story,
            Table=Table,
            TableStyle=TableStyle,
            Paragraph=Paragraph,
            body_style=body_style,
            reportlab=reportlab,
        )
        if goal_table:
            story.append(goal_table)
            story.append(Spacer(1, 12))

        milestones = self.metrics.get("derived_milestones") or []
        if milestones:
            story.append(Paragraph("Milestones", small_caps_style))
            for milestone in milestones:
                achieved = milestone.get("achieved_date")
                achieved_text = achieved.isoformat() if hasattr(achieved, "isoformat") else str(achieved or "")
                line = f"- {milestone.get('label', 'Milestone')} ({achieved_text})"
                story.append(Paragraph(line, body_style))
        else:
            story.append(Paragraph("No milestones recorded yet.", body_style))

        doc.build(story, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _load_reportlab():
        try:
            from reportlab.lib.colors import HexColor
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import (
                HRFlowable,
                Image as RLImage,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            return {
                "A4": A4,
                "HexColor": HexColor,
                "TA_CENTER": TA_CENTER,
                "TA_JUSTIFY": TA_JUSTIFY,
                "TA_LEFT": TA_LEFT,
                "inch": inch,
                "ParagraphStyle": ParagraphStyle,
                "getSampleStyleSheet": getSampleStyleSheet,
                "SimpleDocTemplate": SimpleDocTemplate,
                "Paragraph": Paragraph,
                "Spacer": Spacer,
                "PageBreak": PageBreak,
                "Table": Table,
                "TableStyle": TableStyle,
                "HRFlowable": HRFlowable,
                "RLImage": RLImage,
            }
        except Exception:
            return None

    def _add_title_page(
        self,
        story,
        Paragraph,
        Spacer,
        subtitle_style,
        title_style,
        images: dict[str, BytesIO],
    ) -> None:
        profile = self.user_data.get("profile") or {}
        overview = self.metrics.get("journey_overview") or {}
        name = profile.get("name") or profile.get("email") or "My"
        start_date = overview.get("start_date")
        end_date = overview.get("end_date")
        start_text = start_date.isoformat() if hasattr(start_date, "isoformat") else "unknown"
        end_text = end_date.isoformat() if hasattr(end_date, "isoformat") else "present"

        story.append(Spacer(1, 160))
        story.append(Paragraph("The Journey", title_style))
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"{name}'s Transformation", subtitle_style))
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"{start_text} - {end_text}", subtitle_style))
        if self.book_type == "in_progress":
            story.append(Spacer(1, 8))
            story.append(Paragraph("(In Progress)", subtitle_style))

        image_flowable = self._embed_image(images.get("sunrise"), 5.5, self._load_reportlab())
        if image_flowable:
            story.append(Spacer(1, 18))
            story.append(image_flowable)

    @staticmethod
    def _chapter_titles_for_book_type(book_type: str) -> list[str]:
        if book_type == "complete":
            return [
                "Who I Was - Day One",
                "First 30 Days",
                "The Dip",
                "The Turning Point",
                "The Progress",
                "The Moments",
                "Who I Became",
            ]
        return [
            "Who I Was - Day One",
            "Your Journey So Far",
            "The Challenges",
            "If You Keep Going",
            "The Future You",
        ]

    @staticmethod
    def _append_body_paragraphs(story, text: str, Paragraph, style) -> None:
        text = (text or "").strip()
        if not text:
            return
        paragraphs = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
        for chunk in paragraphs:
            safe = chunk.replace("\n", "<br/>")
            story.append(Paragraph(safe, style))

    @staticmethod
    def _embed_image(image_bytesio: BytesIO | None, width_inches: float, reportlab) -> Any | None:
        if not image_bytesio or not reportlab:
            return None
        try:
            RLImage = reportlab["RLImage"]
            inch = reportlab["inch"]
            image_bytesio.seek(0)
            return RLImage(
                image_bytesio,
                width=width_inches * inch,
                height=(width_inches * 0.5) * inch,
            )
        except Exception:
            return None

    def _append_goal_summary_table(self, story, Table, TableStyle, Paragraph, body_style, reportlab):
        HexColor = reportlab["HexColor"]
        goal = self.user_data.get("goal") or self.metrics.get("goal") or {}
        if not goal:
            return None
        deadline = goal.get("deadline")
        deadline_text = deadline.isoformat() if hasattr(deadline, "isoformat") else str(deadline or "")
        rows = [
            ["Goal", "Status", "Deadline"],
            [goal.get("title") or "Journey Goal", goal.get("status") or "-", deadline_text or "-"],
        ]
        table = Table(rows, colWidths=[200, 120, 120])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EFE7D4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#3D2B1F")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#D7C9AA")),
                    ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    @staticmethod
    def _add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillGray(0.45)
        canvas.drawCentredString(300, 24, str(doc.page))
        canvas.restoreState()
