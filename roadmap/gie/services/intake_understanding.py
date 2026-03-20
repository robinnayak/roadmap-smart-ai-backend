import re
from collections import defaultdict


class GIEIntakeUnderstandingService:
    """
    Deterministic Step 1-2 intake service:
    - Step 1: Natural-language understanding signal extraction.
    - Step 2: Intent and goal-domain classification.
    """

    DOMAIN_KEYWORDS = {
        'career': (
            'career', 'job', 'promotion', 'salary', 'interview', 'resume',
            'role', 'manager', 'leadership', 'office', 'work',
        ),
        'health': (
            'health', 'fitness', 'workout', 'exercise', 'run', 'running',
            'marathon', 'sleep', 'diet', 'weight', 'gym', 'injury',
            'meal', 'meals', 'meal prep', 'nutrition', 'protein',
        ),
        'financial': (
            'financial', 'finance', 'money', 'save', 'savings', 'invest',
            'investment', 'debt', 'income', 'revenue', 'emergency fund',
            'budget', 'house', 'home', 'mortgage', 'down payment',
            'property', 'rent', 'real estate',
        ),
        'learning': (
            'learn', 'learning', 'study', 'course', 'certification', 'skill',
            'skills', 'book', 'training', 'practice', 'master',
        ),
        'personal': (
            'personal', 'relationship', 'family', 'confidence', 'habit',
            'discipline', 'mindset', 'balance', 'lifestyle', 'self',
        ),
        'business': (
            'business', 'startup', 'founder', 'company', 'product', 'launch',
            'customers', 'client', 'market', 'sales', 'profit',
        ),
    }

    INTENT_SIGNALS = {
        'build_habit': (
            'daily', 'routine', 'habit', 'consistently', 'every day',
            'per week', 'times a week',
        ),
        'achieve_outcome': (
            'achieve', 'reach', 'complete', 'finish', 'launch', 'build',
            'save', 'earn', 'become', 'hit',
        ),
        'maintain_state': (
            'maintain', 'keep', 'sustain', 'continue', 'preserve',
        ),
        'recover_or_reduce': (
            'reduce', 'decrease', 'cut', 'quit', 'stop', 'recover', 'avoid',
            'lose',
        ),
        'explore_or_start': (
            'start', 'begin', 'try', 'explore', 'discover',
        ),
    }

    DOMAIN_ORDER = ['career', 'health', 'financial', 'learning', 'personal', 'business', 'other']
    INTENT_ORDER = ['build_habit', 'achieve_outcome', 'recover_or_reduce', 'maintain_state', 'explore_or_start']

    @classmethod
    def analyze_goal_text(cls, goal_text: str) -> dict:
        normalized_text = cls._normalize_text(goal_text)
        tokens = cls._tokenize(normalized_text)

        nlu = cls._extract_nlu_signals(normalized_text)
        domain = cls._classify_domain(normalized_text, tokens)
        intent = cls._classify_intent(normalized_text, tokens)

        return {
            'goal_text': goal_text.strip(),
            'normalized_goal_text': normalized_text,
            'nlu': nlu,
            'goal_domain': domain,
            'intent': intent,
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r'\s+', ' ', (text or '').strip().lower())

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9']+", text)

    @classmethod
    def _extract_nlu_signals(cls, normalized_text: str) -> dict:
        horizon = cls._extract_time_horizon(normalized_text)
        cadence = cls._extract_weekly_cadence(normalized_text)
        numeric_targets = cls._extract_numeric_targets(normalized_text)

        return {
            'time_horizon': horizon,
            'weekly_cadence': cadence,
            'numeric_targets': numeric_targets,
        }

    @staticmethod
    def _extract_time_horizon(normalized_text: str) -> dict | None:
        matches = list(re.finditer(r'\b(\d+)\s*(day|week|month|year)s?\b', normalized_text))
        if not matches:
            return None
        unit_scale = {'day': 1, 'week': 7, 'month': 30, 'year': 365}
        match = max(
            matches,
            key=lambda candidate: int(candidate.group(1)) * unit_scale[candidate.group(2)],
        )
        value = int(match.group(1))
        unit = f"{match.group(2)}s"
        return {
            'raw': match.group(0),
            'value': value,
            'unit': unit,
        }

    @staticmethod
    def _extract_weekly_cadence(normalized_text: str) -> dict | None:
        match = re.search(r'\b(\d+)\s*(day|days|time|times)\s*(per|a)?\s*week\b', normalized_text)
        if not match:
            return None
        return {
            'raw': match.group(0),
            'value': int(match.group(1)),
            'unit': 'times_per_week',
        }

    @staticmethod
    def _extract_numeric_targets(normalized_text: str) -> list[dict]:
        matches = re.findall(r'\b\d+(?:\.\d+)?\b', normalized_text)
        if not matches:
            return []
        return [{'value': float(value)} for value in matches]

    @classmethod
    def _classify_domain(cls, normalized_text: str, tokens: list[str]) -> dict:
        scores = defaultdict(int)
        matched_signals: dict[str, list[str]] = {key: [] for key in cls.DOMAIN_KEYWORDS.keys()}

        token_set = set(tokens)
        for domain, keywords in cls.DOMAIN_KEYWORDS.items():
            for keyword in keywords:
                if ' ' in keyword:
                    if keyword in normalized_text:
                        scores[domain] += 2
                        matched_signals[domain].append(keyword)
                elif keyword in token_set:
                    scores[domain] += 1
                    matched_signals[domain].append(keyword)

        top_domain = 'other'
        top_score = 0
        for domain in cls.DOMAIN_ORDER:
            score = scores.get(domain, 0)
            if score > top_score:
                top_domain = domain
                top_score = score

        total_score = sum(scores.values())
        if top_domain == 'other':
            confidence = 0.35 if normalized_text else 0.0
            matched = []
        else:
            confidence = round(min(0.99, 0.45 + (top_score / max(total_score, 1)) * 0.5), 2)
            matched = sorted(set(matched_signals[top_domain]))

        return {
            'value': top_domain,
            'confidence': confidence,
            'matched_signals': matched,
            'score_breakdown': {domain: scores.get(domain, 0) for domain in cls.DOMAIN_ORDER if domain != 'other'},
        }

    @classmethod
    def _classify_intent(cls, normalized_text: str, tokens: list[str]) -> dict:
        scores = defaultdict(int)
        matched_signals: dict[str, list[str]] = {key: [] for key in cls.INTENT_SIGNALS.keys()}
        token_set = set(tokens)

        for intent, signals in cls.INTENT_SIGNALS.items():
            for signal in signals:
                if ' ' in signal:
                    if signal in normalized_text:
                        scores[intent] += 2
                        matched_signals[intent].append(signal)
                elif signal in token_set:
                    scores[intent] += 1
                    matched_signals[intent].append(signal)

        top_intent = 'achieve_outcome'
        top_score = 0
        for intent in cls.INTENT_ORDER:
            score = scores.get(intent, 0)
            if score > top_score:
                top_intent = intent
                top_score = score

        total_score = sum(scores.values())
        confidence = round(min(0.99, 0.4 + (top_score / max(total_score, 1)) * 0.55), 2) if total_score else 0.4

        return {
            'value': top_intent,
            'confidence': confidence,
            'matched_signals': sorted(set(matched_signals.get(top_intent, []))),
            'score_breakdown': {intent: scores.get(intent, 0) for intent in cls.INTENT_ORDER},
        }
