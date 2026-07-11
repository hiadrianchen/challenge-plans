"""Deliberation/voting engine: multiple agents vote on options,
with model_family weight caps to prevent false consensus and an escape gate for verifiable
blockers, which are routed into adversarial verification. Ties produce discuss + tie_breaker.
It shares adapters, panel-integrity checks, and the run_manifest skeleton with challenge mode.

v1 only implements stage 3, convergence voting, where options are already provided and
closed. Stages 1 and 2, context alignment and divergent candidate generation for the full
three-stage open-decision flow must be supplied manually by the caller;
the engine does not yet include generate_options.
"""
from __future__ import annotations

import concurrent.futures
from collections import Counter

from .adapters import VoterSpec, strip_marker
from .engine import _build_panel, _extract_json
from .prompts import END_MARKER, UNTRUSTED_GUARD, lang_directive
from .schema import PanelIntegrity


def build_voter_prompt(question: str, options: list[dict], lens: str) -> str:
    opts = "\n".join(f"  [{o['id']}] {o['text']}" for o in options)
    return f"""You are a voter on a deliberation panel (lens: {lens}). Below are a decision question and several options.
Rank the options and choose a first choice based on evidence and tradeoffs. Do not hedge. If an option has a **mechanically verifiable blocker**
(constraint violation, irreversible cost, or boundary breach), call it out separately with specific evidence; it will be removed from voting and routed to adversarial verification.{lang_directive()}

Question: {question}
Options:
{opts}

{UNTRUSTED_GUARD}

Output strict JSON only, followed by {END_MARKER} on its own final line:
{{"ranking": ["<all option_ids from best to worst>"], "first_choice": "<option_id>",
  "reasons": {{"<option_id>": "<one-sentence reason>"}},
  "blockers": [{{"option_id": "<id>", "blocker": "<blocker>", "anchor": "<specific constraint/field/irreversible point>"}}]}}
{END_MARKER}"""


_TIE_EPS = 1e-3  # Match weighted Borda granularity (weight=1/family vote count); 1e-6 misses ties too easily.


def _parse_vote(raw: dict, option_ids: set) -> dict | None:
    ranking = [o for o in (raw.get("ranking") or []) if o in option_ids]
    # Ranking must list every option exactly once; otherwise truncated strategic votes can
    # give all omitted options the same worst score.
    if len(ranking) != len(option_ids) or set(ranking) != option_ids:
        return None
    fc = raw.get("first_choice")
    if fc not in option_ids:
        fc = ranking[0]
    blockers = [b for b in (raw.get("blockers") or [])
                if b.get("option_id") in option_ids and (b.get("anchor") or "").strip()]
    return {"ranking": ranking, "first_choice": fc,
            "reasons": raw.get("reasons") or {}, "blockers": blockers}


def weigh_options(question: str, options: list[dict], adapters, profile: str = "standard") -> dict:
    """options: [{id, text}]. Return a deliberation manifest."""
    if not adapters:
        raise RuntimeError("No available adapters; run `challenge-plans doctor` first")
    if len(options) < 2:
        raise ValueError("Deliberation mode requires at least 2 options")
    option_ids = {o["id"] for o in options}
    n = len(options)
    voters = _build_panel(profile, adapters)
    panel = PanelIntegrity(expected_voters=len(voters))

    def _run(adapter, lens, voter_id):
        spec = VoterSpec(voter_id=voter_id, backend=adapter.backend,
                         model_family=adapter.model_family, role="voter", persona=lens,
                         family_source=getattr(adapter, "family_source", "builtin"))
        cap = adapter.invoke(build_voter_prompt(question, options, lens), spec)
        return voter_id, spec, cap

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(voters)) as ex:
        for fut in [ex.submit(_run, a, p, v) for a, p, v in voters]:
            results.append(fut.result())

    votes, voters_meta = [], []
    user_declared_families: set[str] = set()
    builtin_families: set[str] = set()  # families with ≥1 collected BUILTIN voter
    for voter_id, spec, cap in results:
        family = spec.model_family
        meta = {"voter_id": voter_id, "model_family": family,
                "family_source": spec.family_source}
        if not cap.ok:
            panel.missing.append({"voter": voter_id, "reason": cap.reason.value if cap.reason else "unknown"})
            meta["status"] = "capture_failed"; voters_meta.append(meta); continue
        raw = _extract_json(strip_marker(cap.text))
        parsed = _parse_vote(raw, option_ids) if raw else None
        if parsed is None:
            panel.missing.append({"voter": voter_id, "reason": "parse_error"})
            meta["status"] = "parse_error"; voters_meta.append(meta); continue
        panel.collected_voters += 1
        if spec.family_source == "user_declared":
            user_declared_families.add(family)
        else:
            builtin_families.add(family)
        meta["status"] = "ok"; voters_meta.append(meta)
        votes.append({"voter_id": voter_id, "model_family": family, **parsed})

    # model_family weight cap: each family totals 1.0, split across its ok votes.
    fam_ok = Counter(v["model_family"] for v in votes)
    families = set(fam_ok)
    for v in votes:
        v["weight"] = 1.0 / fam_ok[v["model_family"]]

    # blocker = an **unverified** blocker claim: annotate and warn, but do not remove options,
    # avoiding single-vote vetoes over weighted majorities. Only downgrade to discuss when the
    # blocker lands on the weighted winner, so challenge-mode Verifier can decide.
    blocked = {}
    for v in votes:
        for b in v["blockers"]:
            blocked.setdefault(b["option_id"], []).append(
                {"by": v["voter_id"], "blocker": b["blocker"], "anchor": b["anchor"]})

    # Weighted Borda: rank r (0=best) earns (n-1-r) points times vote weight.
    # Rankings are enforced complete, so there is no "not listed" case.
    scores = {o["id"]: 0.0 for o in options}
    raw_first = Counter()
    for v in votes:
        raw_first[v["first_choice"]] += 1
        rank_of = {oid: i for i, oid in enumerate(v["ranking"])}
        for oid in option_ids:
            scores[oid] += v["weight"] * (n - 1 - rank_of[oid])

    ranked = sorted(options, key=lambda o: (-scores[o["id"]], o["id"]))
    winner = ranked[0]["id"]
    low_diversity = len(families) <= 1
    tie = len(ranked) >= 2 and abs(scores[winner] - scores[ranked[1]["id"]]) < _TIE_EPS

    if not votes or not panel.complete:
        recommendation = "inconclusive"
    elif low_diversity:
        recommendation = "discuss"       # Do not present a single family as consensus.
    elif tie:
        recommendation = "discuss"       # Weighted tie; hand off to the owner tie_breaker.
    elif winner in blocked:
        recommendation = "discuss"       # Winner has a blocker claim; route to adversarial verification.
    else:
        recommendation = winner

    raw_winner = raw_first.most_common(1)[0][0] if raw_first else None
    raw_weighted_conflict = (recommendation in option_ids and raw_winner is not None
                             and raw_winner != recommendation)

    # Strongest dissent: expose the highest-weight opposition to the leader for any outcome.
    leader = recommendation if recommendation in option_ids else winner
    against = [v for v in votes if v["first_choice"] != leader]
    strongest = None
    if against:
        top = max(against, key=lambda v: v["weight"])
        strongest = {"by": top["voter_id"], "prefers": top["first_choice"],
                     "reason": top["reasons"].get(top["first_choice"], "")}

    return {
        "mode": "deliberation", "question": question, "recommendation": recommendation,
        "weighted_winner": winner, "raw_winner": raw_winner,
        "raw_weighted_conflict": raw_weighted_conflict,
        "winner_unverified_blocker": blocked.get(winner, []),
        "source_diversity": {"families": len(families), "voters": panel.collected_voters,
                             "user_declared_families": sorted(user_declared_families),
                             # A family cap lifted only by a user-DECLARED (BYO) family is
                             # asserted diversity, not verified — flag it like engine does
                             # (per-voter builtin tracking, not name subtraction).
                             "warning": ("low_diversity_single_family" if low_diversity
                                         else "diversity_relies_on_user_declared_family"
                                         if len(builtin_families) <= 1 else None)},
        "panel_integrity": {"expected_voters": panel.expected_voters,
                            "collected_voters": panel.collected_voters,
                            "missing": panel.missing, "complete": panel.complete,
                            "action": "flagged" if panel.missing else ""},
        "vote_policy": {"unit": "backend+model_family", "model_family_weight_cap": 1.0,
                        "tie_breaker": "owner_decision"},
        "options": [{"id": o["id"], "text": o["text"], "rank": ranked.index(o) + 1,
                     "raw_first_choice": raw_first[o["id"]],
                     "weighted_score": round(scores[o["id"]], 4),
                     "blocked": o["id"] in blocked, "blocker_notes": blocked.get(o["id"], [])}
                    for o in options],
        "votes": [{"voter_id": v["voter_id"], "model_family": v["model_family"],
                   "weight": round(v["weight"], 3), "first_choice": v["first_choice"],
                   "ranking": v["ranking"]} for v in votes],
        "voters": voters_meta, "strongest_dissent": strongest,
    }
