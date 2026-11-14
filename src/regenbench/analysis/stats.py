import math
from typing import Tuple


def wilson_score_interval(successes: int, trials: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Computes Wilson score 95% confidence interval for a proportion.
    Rule of three: if successes == 0, upper bound is approximately 3 / trials.
    """
    if trials == 0:
        return (0.0, 0.0)

    z = 1.95996  # 95% confidence z-score
    p = successes / trials

    if successes == 0:
        # Rule of three upper bound
        upper = min(1.0, 3.0 / trials)
        return (0.0, upper)

    denominator = 1 + z**2 / trials
    centre_adjusted_probability = p + z**2 / (2 * trials)
    adjusted_std_dev = math.sqrt((p * (1 - p) + z**2 / (4 * trials)) / trials)

    lower_bound = (centre_adjusted_probability - z * adjusted_std_dev) / denominator
    upper_bound = (centre_adjusted_probability + z * adjusted_std_dev) / denominator

    return (max(0.0, lower_bound), min(1.0, upper_bound))
