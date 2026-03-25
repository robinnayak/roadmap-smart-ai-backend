from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO
from typing import Any


class ImageGenerator:
    def __init__(self, metrics: dict[str, Any]):
        self.metrics = metrics or {}
        self.journals = sorted(
            self.metrics.get("journals") or [],
            key=lambda x: x.get("entry_date") or date.min,
        )

    def generate_completion_chart(self) -> BytesIO:
        mpl = self._load_matplotlib()
        if not mpl:
            return self._text_fallback_image("Completion chart unavailable")
        plt = mpl["plt"]

        dates = [row.get("entry_date") for row in self.journals if row.get("entry_date")]
        values = [
            100.0 if float(row.get("sentiment_score") or 0.0) >= 0 else 0.0
            for row in self.journals
            if row.get("entry_date")
        ]
        if not dates:
            dates = [date.today()]
            values = [0.0]

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(dates, values, color="#4F7942", linewidth=2.0)
        ax.set_title("Your Consistency Over Time")
        ax.set_ylabel("Completion %")
        ax.set_ylim(0, 100)
        ax.grid(alpha=0.25)
        return self._figure_to_buffer(fig)

    def generate_sentiment_chart(self) -> BytesIO:
        mpl = self._load_matplotlib()
        if not mpl:
            return self._text_fallback_image("Sentiment chart unavailable")
        plt = mpl["plt"]

        dates = [row.get("entry_date") for row in self.journals if row.get("entry_date")]
        sentiments = [
            float(row.get("sentiment_score") or 0.0)
            for row in self.journals
            if row.get("entry_date")
        ]
        if not dates:
            dates = [date.today()]
            sentiments = [0.0]

        fig, ax = plt.subplots(figsize=(8, 4))
        for idx in range(1, len(dates)):
            color = "#2E8B57" if sentiments[idx] >= 0 else "#C0392B"
            ax.plot(dates[idx - 1 : idx + 1], sentiments[idx - 1 : idx + 1], color=color, linewidth=2.0)
        if len(dates) == 1:
            ax.plot(dates, sentiments, color="#2E8B57", linewidth=2.0)
        ax.axhline(0, color="#666666", linestyle="--", linewidth=1)
        ax.set_title("Your Emotional Journey")
        ax.set_ylabel("Sentiment")
        ax.set_ylim(-1, 1)
        ax.grid(alpha=0.2)
        return self._figure_to_buffer(fig)

    def generate_streak_chart(self) -> BytesIO:
        mpl = self._load_matplotlib()
        if not mpl:
            return self._text_fallback_image("Streak chart unavailable")
        plt = mpl["plt"]

        streak_lengths = self._compute_streak_lengths()
        if not streak_lengths:
            streak_lengths = [0]

        fig, ax = plt.subplots(figsize=(8, 4))
        x = list(range(1, len(streak_lengths) + 1))
        ax.bar(x, streak_lengths, color="#FFD700")
        ax.set_title("Streak Milestones")
        ax.set_xlabel("Streak Number")
        ax.set_ylabel("Days")
        ax.grid(axis="y", alpha=0.2)
        return self._figure_to_buffer(fig)

    def generate_heatmap(self) -> BytesIO:
        mpl = self._load_matplotlib()
        if not mpl:
            return self._text_fallback_image("Journey calendar unavailable")
        plt = mpl["plt"]
        patches = mpl["patches"]

        if self.journals:
            start = self.journals[0]["entry_date"]
            end = self.journals[-1]["entry_date"]
        else:
            start = date.today() - timedelta(days=30)
            end = date.today()

        if start is None or end is None:
            start = date.today() - timedelta(days=30)
            end = date.today()

        total_days = (end - start).days + 1
        weeks = max((total_days + start.weekday() + 6) // 7, 1)
        existing_dates = {row["entry_date"] for row in self.journals if row.get("entry_date")}

        fig, ax = plt.subplots(figsize=(10, 4))
        for offset in range(total_days):
            current = start + timedelta(days=offset)
            col = current.weekday()  # Mon-Sun => 0-6
            row = (offset + start.weekday()) // 7
            has_entry = current in existing_dates
            face = "#D4AF37" if has_entry else "#E5E5E5"
            rect = patches.Rectangle((col, row), 0.95, 0.95, facecolor=face, edgecolor="white")
            ax.add_patch(rect)

        ax.set_title("Your Journey Calendar")
        ax.set_xlim(0, 7)
        ax.set_ylim(0, weeks)
        ax.set_xticks(range(7))
        ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        ax.set_yticks([])
        ax.invert_yaxis()
        ax.set_frame_on(False)
        return self._figure_to_buffer(fig)

    def generate_wordcloud(self, frequencies: dict[str, int]) -> BytesIO:
        frequencies = frequencies or {}
        if not frequencies:
            return self._text_fallback_image("No word data available")

        try:
            from wordcloud import STOPWORDS, WordCloud

            wc = WordCloud(
                width=800,
                height=400,
                background_color="white",
                stopwords=STOPWORDS,
                max_words=100,
            )
            wc.generate_from_frequencies(frequencies)
            buffer = BytesIO()
            wc.to_image().save(buffer, format="PNG")
            buffer.seek(0)
            return buffer
        except Exception:
            mpl = self._load_matplotlib()
            if not mpl:
                return self._text_fallback_image("Wordcloud unavailable")
            plt = mpl["plt"]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.axis("off")
            top_items = sorted(frequencies.items(), key=lambda item: item[1], reverse=True)[:20]
            if not top_items:
                ax.text(0.5, 0.5, "No words", ha="center", va="center")
                return self._figure_to_buffer(fig)
            max_count = max(count for _, count in top_items) or 1
            for index, (word, count) in enumerate(top_items):
                x = (index % 5) / 5 + 0.1
                y = 0.9 - (index // 5) * 0.2
                size = 8 + int((count / max_count) * 24)
                ax.text(x, y, word, fontsize=size, alpha=0.8, transform=ax.transAxes)
            return self._figure_to_buffer(fig)

    def generate_milestone_timeline(self, milestones: list[dict[str, Any]]) -> BytesIO:
        mpl = self._load_matplotlib()
        if not mpl:
            return self._text_fallback_image("Milestone timeline unavailable")
        plt = mpl["plt"]

        milestones = milestones or []
        if not milestones:
            milestones = [
                {"label": "Your next milestone is being defined", "achieved_date": date.today()}
            ]

        fig, ax = plt.subplots(figsize=(8, max(4, len(milestones) * 0.8)))
        ax.set_title("Milestones Achieved")
        ax.plot([0.5, 0.5], [0, len(milestones) - 1], color="#999999", linewidth=2)

        for idx, item in enumerate(milestones):
            side = -1 if idx % 2 == 0 else 1
            x = 0.5 + side * 0.15
            y = idx
            label = item.get("label") or "Milestone"
            achieved = item.get("achieved_date")
            achieved_text = achieved.isoformat() if hasattr(achieved, "isoformat") else str(achieved or "")

            ax.scatter([0.5], [y], color="#D4AF37", s=80)
            ax.plot([0.5, x], [y, y], color="#CCCCCC", linewidth=1)
            align = "right" if side < 0 else "left"
            ax.text(x, y, f"{label}\n{achieved_text}", ha=align, va="center")

        ax.set_xlim(0, 1)
        ax.set_ylim(-0.5, len(milestones) - 0.5)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.invert_yaxis()
        ax.set_frame_on(False)
        return self._figure_to_buffer(fig)

    @staticmethod
    def _load_matplotlib():
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import patches

            return {"plt": plt, "patches": patches}
        except Exception:
            return None

    @staticmethod
    def _figure_to_buffer(fig) -> BytesIO:
        buffer = BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", dpi=150)
        buffer.seek(0)
        try:
            fig.clf()
        except Exception:
            pass
        return buffer

    @staticmethod
    def _text_fallback_image(message: str) -> BytesIO:
        try:
            from PIL import Image as PILImage
            from PIL import ImageDraw

            image = PILImage.new("RGB", (800, 400), color=(250, 248, 240))
            draw = ImageDraw.Draw(image)
            draw.text((40, 180), message, fill=(80, 60, 40))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer
        except Exception:
            buffer = BytesIO()
            buffer.write(b"")
            buffer.seek(0)
            return buffer

    def _compute_streak_lengths(self) -> list[int]:
        entry_dates = [row["entry_date"] for row in self.journals if row.get("entry_date")]
        entry_dates = sorted(set(entry_dates))
        if not entry_dates:
            return []

        streaks = []
        current = 1
        for prev, curr in zip(entry_dates, entry_dates[1:]):
            if (curr - prev).days == 1:
                current += 1
            else:
                streaks.append(current)
                current = 1
        streaks.append(current)
        return streaks
