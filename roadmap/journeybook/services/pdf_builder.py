from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from journeybook.services.print_spec import DEFAULT_TRIM_SIZE, get_print_spec


class PDFBuilder:
    def __init__(
        self,
        user_data: dict[str, Any],
        metrics: dict[str, Any],
        book_type: str,
        trim_size: str | None = None,
    ):
        self.user_data = user_data or {}
        self.metrics = metrics or {}
        self.book_type = book_type
        self.print_spec = get_print_spec(trim_size or DEFAULT_TRIM_SIZE)
        self.trim_size = self.print_spec["trim_size"]

    def get_image_frame_size_points(self) -> tuple[float, float]:
        width = float(self.print_spec["image_frame_inches"]["width"]) * 72.0
        height = float(self.print_spec["image_frame_inches"]["height"]) * 72.0
        return width, height

    def get_page_size_points(self) -> tuple[float, float]:
        page_size = self.print_spec["page_size_points"]
        return float(page_size[0]), float(page_size[1])

    def build(
        self,
        chapters: list[str],
        motivational_pages: list[str],
        images: dict[str, BytesIO],
    ) -> BytesIO:
        reportlab = self._load_reportlab()
        if not reportlab:
            raise RuntimeError("ReportLab is required to build Journey Book PDFs.")

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
        margins = self.print_spec["margins_points"]
        doc = SimpleDocTemplate(
            buffer,
            pagesize=tuple(self.print_spec["page_size_points"]),
            leftMargin=float(margins["left"]),
            rightMargin=float(margins["right"]),
            topMargin=float(margins["top"]),
            bottomMargin=float(margins["bottom"]),
            title="The Journey",
        )

        font_scale = float(self.print_spec.get("font_scale", 1.0))
        frame_width_inches = float(self.print_spec["image_frame_inches"]["width"])
        frame_height_inches = float(self.print_spec["image_frame_inches"]["height"])

        body_font, heading_font, italic_font = self._book_fonts(reportlab)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleStyle",
            parent=styles["Title"],
            fontName=heading_font,
            fontSize=36 * font_scale,
            leading=42 * font_scale,
            textColor=HexColor("#3D2B1F"),
            alignment=TA_CENTER,
        )
        subtitle_style = ParagraphStyle(
            "SubtitleStyle",
            parent=styles["Normal"],
            fontName=body_font,
            fontSize=18 * font_scale,
            leading=24 * font_scale,
            textColor=HexColor("#666666"),
            alignment=TA_CENTER,
        )
        chapter_heading_style = ParagraphStyle(
            "ChapterHeadingStyle",
            parent=styles["Heading1"],
            fontName=heading_font,
            fontSize=24 * font_scale,
            leading=30 * font_scale,
            textColor=HexColor("#3D2B1F"),
            alignment=TA_LEFT,
        )
        body_style = ParagraphStyle(
            "BodyStyle",
            parent=styles["BodyText"],
            fontName=body_font,
            fontSize=12 * font_scale,
            leading=17 * font_scale,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
        )
        quote_style = ParagraphStyle(
            "QuoteStyle",
            parent=styles["BodyText"],
            fontName=italic_font,
            fontSize=12 * font_scale,
            leading=16 * font_scale,
            leftIndent=0.5 * inch,
            textColor=HexColor("#555555"),
        )
        small_caps_style = ParagraphStyle(
            "SmallCapsStyle",
            parent=styles["BodyText"],
            fontName=body_font,
            fontSize=9 * font_scale,
            leading=12 * font_scale,
            textColor=HexColor("#888888"),
            alignment=TA_LEFT,
        )
        projection_style = ParagraphStyle(
            "ProjectionStyle",
            parent=body_style,
            fontName=italic_font,
        )

        story = []
        self._add_title_page(
            story=story,
            Paragraph=Paragraph,
            Spacer=Spacer,
            subtitle_style=subtitle_style,
            title_style=title_style,
            reportlab=reportlab,
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
            if image_key:
                image_flowable = self._build_image_frame(
                    image_bytesio=images.get(image_key),
                    frame_width_inches=frame_width_inches,
                    frame_height_inches=frame_height_inches,
                    reportlab=reportlab,
                    body_font=body_font,
                )
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
                            ("FONTNAME", (0, 0), (-1, -1), heading_font),
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
            body_font=body_font,
            heading_font=heading_font,
            reportlab=reportlab,
            table_width=doc.width,
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
            import reportlab as reportlab_pkg

            from reportlab.lib.colors import HexColor
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.lib.utils import ImageReader
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
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
                "reportlab_pkg": reportlab_pkg,
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
                "ImageReader": ImageReader,
                "pdfmetrics": pdfmetrics,
                "TTFont": TTFont,
            }
        except Exception:
            return None

    @staticmethod
    def _book_fonts(reportlab):
        # Prefer embedded TrueType fonts for deterministic print output.
        pdfmetrics = reportlab["pdfmetrics"]
        TTFont = reportlab["TTFont"]
        reportlab_pkg = reportlab["reportlab_pkg"]
        candidates = [
            ("JourneySerif", "JourneySerifBold", "JourneySerifItalic", "Vera.ttf", "VeraBd.ttf", "VeraIt.ttf"),
            ("JourneySans", "JourneySansBold", "JourneySansItalic", "Vera.ttf", "VeraBd.ttf", "VeraIt.ttf"),
        ]

        fonts_dir = Path(reportlab_pkg.__file__).resolve().parent / "fonts"
        for normal_name, bold_name, italic_name, normal_file, bold_file, italic_file in candidates:
            normal_path = fonts_dir / normal_file
            bold_path = fonts_dir / bold_file
            italic_path = fonts_dir / italic_file
            if not (normal_path.exists() and bold_path.exists() and italic_path.exists()):
                continue
            try:
                if normal_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(normal_name, str(normal_path)))
                if bold_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                if italic_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(italic_name, str(italic_path)))
                return normal_name, bold_name, italic_name
            except Exception:
                continue
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"

    def _add_title_page(
        self,
        story,
        Paragraph,
        Spacer,
        subtitle_style,
        title_style,
        reportlab,
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
        story.append(Paragraph(f"{start_text} to {end_text}", subtitle_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"Print Trim: {self.trim_size}", subtitle_style))
        if self.book_type == "in_progress":
            story.append(Spacer(1, 8))
            story.append(Paragraph("(In Progress)", subtitle_style))

        image_flowable = self._embed_image(
            images.get("sunrise"),
            width_inches=float(self.print_spec["image_frame_inches"]["width"]),
            reportlab=reportlab,
        )
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
            ImageReader = reportlab["ImageReader"]
            image_bytesio.seek(0)
            source = ImageReader(image_bytesio)
            src_width, src_height = source.getSize()
            if src_width <= 0 or src_height <= 0:
                return None
            max_width = width_inches * inch
            max_height = (width_inches * 0.62) * inch
            draw_width, draw_height = PDFBuilder._fit_within_frame(
                src_width=float(src_width),
                src_height=float(src_height),
                frame_width=max_width,
                frame_height=max_height,
            )
            if draw_width <= 0 or draw_height <= 0:
                return None
            image_bytesio.seek(0)
            return RLImage(
                image_bytesio,
                width=draw_width,
                height=draw_height,
            )
        except Exception:
            return None

    def _build_image_frame(
        self,
        image_bytesio: BytesIO | None,
        frame_width_inches: float,
        frame_height_inches: float,
        reportlab,
        body_font: str,
    ) -> Any | None:
        Table = reportlab["Table"]
        TableStyle = reportlab["TableStyle"]
        RLImage = reportlab["RLImage"]
        ImageReader = reportlab["ImageReader"]
        inch = reportlab["inch"]
        HexColor = reportlab["HexColor"]

        frame_width_points = frame_width_inches * inch
        frame_height_points = frame_height_inches * inch

        if image_bytesio:
            try:
                image_bytesio.seek(0)
                source = ImageReader(image_bytesio)
                src_width, src_height = source.getSize()
                if src_width > 0 and src_height > 0:
                    draw_width, draw_height = self._fit_within_frame(
                        src_width=float(src_width),
                        src_height=float(src_height),
                        frame_width=frame_width_points,
                        frame_height=frame_height_points,
                    )
                    if draw_width <= 0 or draw_height <= 0:
                        raise ValueError("Invalid image frame fit.")
                    x_pad = max((frame_width_points - draw_width) / 2.0, 0.0)
                    y_pad = max((frame_height_points - draw_height) / 2.0, 0.0)
                    image_bytesio.seek(0)
                    image = RLImage(image_bytesio, width=draw_width, height=draw_height)
                    frame = Table([[image]], colWidths=[frame_width_points], rowHeights=[frame_height_points])
                    frame.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFFFFF")),
                                ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D7C9AA")),
                                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), x_pad),
                                ("RIGHTPADDING", (0, 0), (-1, -1), x_pad),
                                ("TOPPADDING", (0, 0), (-1, -1), y_pad),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), y_pad),
                            ]
                        )
                    )
                    return frame
            except Exception:
                pass

        placeholder = Table(
            [["Image unavailable"]],
            colWidths=[frame_width_points],
            rowHeights=[frame_height_points],
        )
        placeholder.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F7F4EC")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#8B7A60")),
                    ("FONTNAME", (0, 0), (-1, -1), body_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#D7C9AA")),
                ]
            )
        )
        return placeholder

    @staticmethod
    def _fit_within_frame(
        src_width: float,
        src_height: float,
        frame_width: float,
        frame_height: float,
    ) -> tuple[float, float]:
        if src_width <= 0 or src_height <= 0 or frame_width <= 0 or frame_height <= 0:
            return 0.0, 0.0
        scale = min(frame_width / src_width, frame_height / src_height)
        return max(1.0, src_width * scale), max(1.0, src_height * scale)

    def _append_goal_summary_table(
        self,
        story,
        Table,
        TableStyle,
        Paragraph,
        body_style,
        body_font: str,
        heading_font: str,
        reportlab,
        table_width: float,
    ):
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
        table = Table(
            rows,
            colWidths=[table_width * 0.50, table_width * 0.22, table_width * 0.28],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#EFE7D4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#3D2B1F")),
                    ("FONTNAME", (0, 0), (-1, 0), heading_font),
                    ("FONTNAME", (0, 1), (-1, -1), body_font),
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
        page_width = getattr(doc, "pagesize", (595, 842))[0]
        canvas.drawCentredString(page_width / 2, 24, str(doc.page))
        canvas.restoreState()
