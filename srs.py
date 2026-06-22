"""SM-2 spaced repetition algorithm."""


def sm2(repetitions: int, ease_factor: float, interval: int, quality: int) -> tuple[int, float, int]:
    """
    Returns (new_interval_days, new_ease_factor, new_repetitions).
    quality: 0=blackout, 2=hard, 4=good, 5=easy
    """
    if quality < 3:
        new_repetitions = 0
        new_interval = 1
        new_ef = ease_factor
    else:
        new_repetitions = repetitions + 1
        if repetitions == 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            new_interval = round(interval * ease_factor)

        new_ef = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        new_ef = max(1.3, new_ef)

    return new_interval, new_ef, new_repetitions
