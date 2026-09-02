"""Synthetic failed-payment generator + baseline vs RecoverAI benchmark.

Runs entirely in-process (no HTTP, no DB writes) so the numbers are
reproducible and fast. Uses the exact same stub_llm the live system uses
for RecoverAI's decisions, so what the benchmark shows is what the live
service would do.

Usage:
    python scripts/simulator.py --n 5000 --seed 42
    python scripts/simulator.py --n 10000 --out results.json
"""
from __future__ import annotations
import argparse
import json
import random
import statistics
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Make `app` importable when run as `python scripts/simulator.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.schema import AgentContext, AgentDecision
from app.agent.stub_llm import decide as recoverai_decide

# --- Ground-truth model -----------------------------------------------------
#
# For each true failure class we specify:
#   weight               how common it is in the wild
#   template             (error_code, error_source, error_step, error_reason_code)
#   recovery_prob_by_action  P(success) for each recovery action, per attempt
#
# The per-action probabilities encode the domain knowledge the agent has to
# learn: retrying an invalid card is hopeless, retrying a gateway timeout is
# ~usually fine, insufficient_funds benefits from a delay, etc.
#
# `unnecessary` marks an action that would have "worked" but wasn't needed
# (e.g. retrying a case that would have self-resolved) — we score it as
# waste, not a win.

FAILURE_CLASSES = {
    "transient_gateway_failure": {
        "weight": 0.30,
        "template": ("GATEWAY_ERROR", "gateway", "payment_authorization", "gateway_timeout"),
        "recovery_prob": {
            "retry": 0.75, "delayed_retry": 0.80, "payment_link": 0.55,
            "notify": 0.20, "escalate": 0.0,
        },
    },
    "insufficient_funds": {
        "weight": 0.20,
        "template": ("BAD_REQUEST_ERROR", "customer", "payment_authorization", "insufficient_funds"),
        "recovery_prob": {
            "retry": 0.15, "delayed_retry": 0.55, "payment_link": 0.60,
            "notify": 0.25, "escalate": 0.0,
        },
    },
    "invalid_instrument": {
        "weight": 0.15,
        "template": ("BAD_REQUEST_ERROR", "customer", "payment_authentication", "invalid_card_number"),
        "recovery_prob": {
            "retry": 0.02, "delayed_retry": 0.02, "payment_link": 0.55,
            "notify": 0.20, "escalate": 0.0,
        },
    },
    "authentication_failed": {
        "weight": 0.15,
        "template": ("BAD_REQUEST_ERROR", "customer", "payment_authentication", "payment_failed"),
        "recovery_prob": {
            "retry": 0.30, "delayed_retry": 0.40, "payment_link": 0.65,
            "notify": 0.25, "escalate": 0.0,
        },
    },
    "bank_declined": {
        "weight": 0.15,
        "template": ("BAD_REQUEST_ERROR", "bank", "payment_authorization", "payment_failed"),
        "recovery_prob": {
            "retry": 0.20, "delayed_retry": 0.30, "payment_link": 0.50,
            "notify": 0.15, "escalate": 0.0,
        },
    },
    "risk_declined": {
        "weight": 0.05,
        "template": ("BAD_REQUEST_ERROR", "risk", "payment_authorization", "payment_fraud"),
        "recovery_prob": {
            "retry": 0.02, "delayed_retry": 0.02, "payment_link": 0.05,
            "notify": 0.05, "escalate": 0.0,  # escalate is "correct" here, but 0 recovery
        },
    },
}


@dataclass
class SyntheticCase:
    id: int
    true_class: str
    amount: float
    error_code: str
    error_source: str
    error_step: str
    error_reason_code: str
    customer_success_rate: float
    customer_previous_failures: int
    customer_previous_successes: int
    payment_method: str


@dataclass
class RunResult:
    strategy: str
    total_cases: int
    revenue_at_risk: float
    revenue_recovered: float
    cases_recovered: int
    total_actions: int
    unnecessary_actions: int      # actions taken on cases that would never recover, OR redundant
    escalated: int
    per_action_counts: dict = field(default_factory=dict)

    @property
    def recovery_rate(self) -> float:
        return self.revenue_recovered / self.revenue_at_risk if self.revenue_at_risk else 0.0

    @property
    def avg_actions_per_case(self) -> float:
        return self.total_actions / self.total_cases if self.total_cases else 0.0


# --- Generation -------------------------------------------------------------

def generate_batch(n: int, seed: int = 42) -> list[SyntheticCase]:
    rng = random.Random(seed)
    classes = list(FAILURE_CLASSES.items())
    class_names = [k for k, _ in classes]
    weights = [v["weight"] for _, v in classes]
    methods = ["card", "upi", "netbanking", "wallet"]

    out: list[SyntheticCase] = []
    for i in range(n):
        cls_name = rng.choices(class_names, weights=weights, k=1)[0]
        tpl = FAILURE_CLASSES[cls_name]["template"]

        # Customer history: skewed — most customers are OK, some are chronic failers
        prev_success = rng.choices(
            [rng.randint(0, 2), rng.randint(3, 10), rng.randint(10, 40)],
            weights=[0.3, 0.5, 0.2],
        )[0]
        prev_fail = rng.choices(
            [0, rng.randint(1, 3), rng.randint(3, 10)],
            weights=[0.6, 0.3, 0.1],
        )[0]
        total = prev_success + prev_fail
        success_rate = prev_success / total if total else 0.5

        # Amount: log-uniform between ₹100 and ₹50,000
        amount = round(10 ** rng.uniform(2, 4.7), 2)

        out.append(SyntheticCase(
            id=i + 1,
            true_class=cls_name,
            amount=amount,
            error_code=tpl[0],
            error_source=tpl[1],
            error_step=tpl[2],
            error_reason_code=tpl[3],
            customer_success_rate=success_rate,
            customer_previous_failures=prev_fail,
            customer_previous_successes=prev_success,
            payment_method=rng.choice(methods),
        ))
    return out


# --- Strategies -------------------------------------------------------------

def baseline_decide(case: SyntheticCase, attempt: int) -> AgentDecision:
    """Fixed policy: retry once, then give up."""
    return AgentDecision(
        diagnosis="baseline_always_retry",
        confidence=1.0,
        recommended_action="retry" if attempt == 1 else "escalate",
        reason="fixed baseline",
    )


def recoverai_decide_case(case: SyntheticCase, attempt: int) -> AgentDecision:
    ctx = AgentContext(
        amount=case.amount,
        error_code=case.error_code,
        error_source=case.error_source,
        error_step=case.error_step,
        error_reason_code=case.error_reason_code,
        attempt_number=attempt,
        customer_success_rate=case.customer_success_rate,
        customer_previous_failures=case.customer_previous_failures,
        customer_previous_successes=case.customer_previous_successes,
        payment_method=case.payment_method,
    )
    return recoverai_decide(ctx)


# --- Simulation loop --------------------------------------------------------

MAX_ATTEMPTS = 3


def simulate(cases: list[SyntheticCase], strategy: str, decide_fn, seed: int = 1337) -> RunResult:
    rng = random.Random(seed)
    result = RunResult(
        strategy=strategy,
        total_cases=len(cases),
        revenue_at_risk=sum(c.amount for c in cases),
        revenue_recovered=0.0,
        cases_recovered=0,
        total_actions=0,
        unnecessary_actions=0,
        escalated=0,
    )
    action_counts: dict[str, int] = {}

    for case in cases:
        recovered = False
        attempts = 0
        while attempts < MAX_ATTEMPTS and not recovered:
            attempts += 1
            decision = decide_fn(case, attempts)
            action = decision.recommended_action
            result.total_actions += 1
            action_counts[action] = action_counts.get(action, 0) + 1

            if action == "escalate":
                result.escalated += 1
                break

            prob = FAILURE_CLASSES[case.true_class]["recovery_prob"].get(action, 0.0)
            # Retry effectiveness decays with attempts (customer patience, gateway backoff)
            if action in ("retry", "delayed_retry") and attempts > 1:
                prob *= 0.7
            if rng.random() < prob:
                recovered = True
                result.revenue_recovered += case.amount
                result.cases_recovered += 1

        # Unnecessary-action accounting: any action beyond the first on a
        # case that never recovers, and every action on `risk_declined`
        # (should have gone straight to escalate).
        if not recovered and attempts > 1:
            result.unnecessary_actions += (attempts - 1)
        if case.true_class == "risk_declined" and not recovered:
            result.unnecessary_actions += max(attempts - 0, 0)  # every retry was waste

    result.per_action_counts = dict(sorted(action_counts.items()))
    return result


# --- Output -----------------------------------------------------------------

def fmt_inr(x: float) -> str:
    return f"₹{x:,.0f}"


def print_comparison(baseline: RunResult, recover: RunResult) -> None:
    rows = [
        ("At-risk transactions",    f"{baseline.total_cases:,}",             f"{recover.total_cases:,}"),
        ("Revenue at risk",         fmt_inr(baseline.revenue_at_risk),       fmt_inr(recover.revenue_at_risk)),
        ("Cases recovered",         f"{baseline.cases_recovered:,}",         f"{recover.cases_recovered:,}"),
        ("Revenue recovered",       fmt_inr(baseline.revenue_recovered),     fmt_inr(recover.revenue_recovered)),
        ("Recovery rate",           f"{baseline.recovery_rate:.1%}",         f"{recover.recovery_rate:.1%}"),
        ("Avg actions / case",      f"{baseline.avg_actions_per_case:.2f}",  f"{recover.avg_actions_per_case:.2f}"),
        ("Unnecessary actions",     f"{baseline.unnecessary_actions:,}",     f"{recover.unnecessary_actions:,}"),
        ("Escalated",               f"{baseline.escalated:,}",               f"{recover.escalated:,}"),
    ]
    print()
    print(f"{'Metric':<26} {'Baseline':>18} {'RecoverAI':>18}")
    print("-" * 66)
    for label, b, r in rows:
        print(f"{label:<26} {b:>18} {r:>18}")
    print("-" * 66)
    lift = recover.recovery_rate - baseline.recovery_rate
    print(f"{'RecoverAI lift':<26} {'':>18} {lift*100:>+17.1f}pp")
    print()
    print("Action mix — RecoverAI:", recover.per_action_counts)
    print("Action mix — Baseline: ", baseline.per_action_counts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000, help="number of synthetic cases")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for case generation")
    ap.add_argument("--out", type=str, default=None, help="write JSON results to this path")
    args = ap.parse_args()

    cases = generate_batch(args.n, args.seed)
    baseline = simulate(cases, "baseline_always_retry", baseline_decide, seed=1337)
    recover  = simulate(cases, "recoverai",              recoverai_decide_case, seed=1337)

    print_comparison(baseline, recover)

    if args.out:
        payload = {
            "n_cases": args.n,
            "seed": args.seed,
            "class_distribution": {k: sum(1 for c in cases if c.true_class == k) for k in FAILURE_CLASSES},
            "baseline": {**asdict(baseline), "recovery_rate": baseline.recovery_rate,
                         "avg_actions_per_case": baseline.avg_actions_per_case},
            "recoverai": {**asdict(recover), "recovery_rate": recover.recovery_rate,
                          "avg_actions_per_case": recover.avg_actions_per_case},
            "lift_pp": (recover.recovery_rate - baseline.recovery_rate) * 100,
        }
        Path(args.out).write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
