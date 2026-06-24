"""Invariant test suite (MockAdapter, no real model calls).

Pins the key invariants established across the cross-agent adversarial-review rounds:
concern identity / single verdict pipeline / panel integrity / dedup-keeps-strictest /
Verifier cross-family + concrete-evidence threshold / field preflight.
Run: `pytest` (pythonpath/testpaths are preconfigured).
"""
import json

import pytest

from challenge_plans.adapters import MockAdapter, claude_cli_env
from challenge_plans.engine import _extract_json, run_challenge
from challenge_plans.prompts import END_MARKER
from challenge_plans.schema import (
    Concern, PanelIntegrity, Severity, Verdict, canonical_key,
    resolve_verdict, stricter_verdict,
)

M = END_MARKER


def test_claude_cli_env_strips_anthropic_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CHALLENGE_PLANS_LANG", "zh")
    env = claude_cli_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert env["CHALLENGE_PLANS_LANG"] == "zh"


def cbody(concerns):
    return json.dumps({"steelman": "ok", "concerns": concerns}, ensure_ascii=False) + "\n" + M


def vbody(assessment, repro=""):
    return json.dumps({"assessment": assessment, "reproduction": repro, "rebuttal": repro},
                      ensure_ascii=False) + "\n" + M


def concern(span="L2-2", ft="security_or_privacy_boundary", sev="high"):
    return {"artifact_span": span, "failure_type": ft, "severity": sev,
            "title": "t", "evidence": "e", "concrete_failure_step": "s"}


def mk(tmp_path, text="# spec\nL2 user export\nL3 async generation\n"):
    p = tmp_path / "spec.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── concern identity ─────────────────────────────────────────────────────
def test_canonical_key_rejects_empty_anchor():
    with pytest.raises(ValueError):
        canonical_key(artifact_span="", failure_type="x")


def test_canonical_key_deterministic_and_anchor_sensitive():
    k1 = canonical_key(artifact_span="L12-15", failure_type="missing_acceptance_test")
    k2 = canonical_key(artifact_span="L12-15", failure_type="missing_acceptance_test")
    k3 = canonical_key(artifact_span="L99", failure_type="missing_acceptance_test")
    assert k1 == k2 != k3


# ── single verdict pipeline ────────────────────────────────────────────────
def test_verdict_precedence_and_verified_gating():
    hi = Concern(artifact_span="L1", failure_type="hidden_dependency", severity=Severity.HIGH)
    # Unverified high -> no hard gate; discuss.
    assert resolve_verdict([hi]) == Verdict.DISCUSS
    hi.severity_verified = True
    # Verified high -> request_changes.
    assert resolve_verdict([hi]) == Verdict.REQUEST_CHANGES


def test_panel_incomplete_never_approves():
    med = Concern(artifact_span="L1", failure_type="scope_creep", severity=Severity.MEDIUM)
    incomplete = PanelIntegrity(expected_voters=3, collected_voters=2,
                                missing=[{"voter": "x", "reason": "truncated"}])
    assert resolve_verdict([med], panel=incomplete) == Verdict.INCONCLUSIVE


def test_stricter_verdict():
    assert stricter_verdict(Verdict.REQUEST_CHANGES, Verdict.DISCUSS) == Verdict.REQUEST_CHANGES
    assert stricter_verdict(Verdict.APPROVE, Verdict.DISCUSS) == Verdict.DISCUSS


# ── _extract_json robustness ─────────────────────────────────────────────────
def test_extract_json_tolerates_string_braces_and_rejects_multi():
    assert _extract_json('prose {x}\n{"concerns":[],"s":"a } b"}')["s"] == "a } b"
    assert _extract_json('{"a":1}{"b":2}') is None


# ── engine end-to-end (MockAdapter) ───────────────────────────────────────────
def test_dedup_keeps_most_severe(tmp_path):
    sc = {"mock:execution-failure": cbody([concern(sev="low")]),
          "mock:correctness": cbody([concern(sev="critical")]),
          "mock:scope-boundary": cbody([])}
    m = run_challenge(mk(tmp_path), "spec", "standard", [MockAdapter(sc, "mock")])
    real = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]]
    assert len(real) == 1 and real[0]["severity"] == "critical"
    assert set(real[0]["raised_by"]) == {"mock:execution-failure", "mock:correctness"}


def test_hallucinated_span_dropped_not_silent(tmp_path):
    sc = {"mock:execution-failure": cbody([concern(span="L9999-10000"), concern(span="L2-2",
          ft="hidden_dependency")])}
    m = run_challenge(mk(tmp_path), "spec", "fast", [MockAdapter(sc, "mock")])
    assert any(d["reason"] == "invalid_or_hallucinated_span" for d in m["dropped_concerns"])


def test_marker_substring_does_not_fake_complete(tmp_path):
    fake = '{"steelman":"' + M + ' x","concerns":[]}'  # Marker is inside a string, not the final line.
    m = run_challenge(mk(tmp_path), "spec", "fast", [MockAdapter({"mock:execution-failure": fake}, "mock")])
    assert m["panel_integrity"]["missing"][0]["reason"] == "truncated"


def test_low_diversity_caps_discuss(tmp_path):
    # Complete frontmatter with no synthetic concerns + clean single family -> cap at discuss, not approve.
    text = "---\nartifact_type: spec\ntitle: t\nintent: i\nacceptance_criteria: [a]\nnon_goals: [n]\n---\nExport user CSV\nGenerate asynchronously\nFilter by date\n"
    m = run_challenge(mk(tmp_path, text), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert m["verdict"] == "discuss" and m["source_diversity"]["warning"]


def test_multi_family_unlocks_approve(tmp_path):
    text = "---\nartifact_type: spec\ntitle: t\nintent: i\nacceptance_criteria: [a]\nnon_goals: [n]\n---\nExport user CSV\nGenerate asynchronously\nFilter by date\n"
    sc = {"claude:execution-failure": cbody([]), "gpt:correctness": cbody([]),
          "claude:scope-boundary": cbody([])}
    m = run_challenge(mk(tmp_path, text), "spec", "standard",
                      [MockAdapter(sc, "claude"), MockAdapter(sc, "gpt")])
    assert m["verdict"] == "approve" and m["source_diversity"]["families"] == 2


# ── Verifier threshold ────────────────────────────────────────────────────────
def _run_verify(tmp_path, vscript, second="gpt"):
    text = "---\nartifact_type: spec\ntitle: t\nintent: i\nacceptance_criteria: [a]\nnon_goals: [n]\n---\nExport user CSV\nGenerate asynchronously\nFilter by date\n"
    sc = {"claude:execution-failure": cbody([concern()]), f"{second}:verifier": vscript}
    return run_challenge(mk(tmp_path, text), "spec", "fast",
                         [MockAdapter(sc, "claude"), MockAdapter(sc, second)])


def test_verify_real_with_concrete_repro_gates(tmp_path):
    m = _run_verify(tmp_path, vbody("real", "At L2, unauthorized export can send PHI externally"))
    c = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]][0]
    assert m["verdict"] == "request_changes" and c["severity_verified"]


def test_verify_real_without_repro_downgraded(tmp_path):
    m = _run_verify(tmp_path, vbody("real", "This probably has a problem"))
    c = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]][0]
    assert not c["severity_verified"]
    assert m["verifications"][0]["downgraded"] == "no_concrete_repro"


def test_same_family_self_verification_not_trusted(tmp_path):
    text = "---\nartifact_type: spec\ntitle: t\nintent: i\nacceptance_criteria: [a]\nnon_goals: [n]\n---\nExport user CSV\nGenerate asynchronously\nFilter by date\n"
    sc = {"claude:execution-failure": cbody([concern()]), "claude:verifier": vbody("real", "See L2")}
    m = run_challenge(mk(tmp_path, text), "spec", "fast", [MockAdapter(sc, "claude")])
    c = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]][0]
    assert not c["severity_verified"] and m["verifications"][0]["downgraded"] == "same_family"


def test_verifier_infra_failure_forces_inconclusive(tmp_path):
    m = _run_verify(tmp_path, '{"assessment":"real","reproduction":"L2"}')  # Missing final marker line.
    assert m["verifications"][0]["assessment"] == "capture_failed"
    assert m["verdict"] == "inconclusive"


# ── preflight ──────────────────────────────────────────────────────────────
def test_preflight_injects_synthetic_for_bare_spec(tmp_path):
    m = run_challenge(mk(tmp_path), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert set(m["preflight"]["missing_required_to_approve"]) == {"acceptance_criteria", "non_goals"}
    assert m["verdict"] == "request_changes"  # Missing acceptance criteria = high synthetic, mechanically verified.


def test_preflight_invalid_artifact_type_schema_invalid(tmp_path):
    text = "---\nartifact_type: blogpost\ntitle: x\n---\nExport user CSV\nGenerate asynchronously\nFilter by date\n"
    m = run_challenge(mk(tmp_path, text), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert m["verdict"] == "schema_invalid"


def test_empty_artifact_schema_invalid(tmp_path):
    m = run_challenge(mk(tmp_path, "   \n"), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert m["verdict"] == "schema_invalid"


# ── final adversarial-fix regressions ─────────────────────────────────────────
from challenge_plans.cli import main  # noqa: E402


def test_body_hint_only_matches_heading_not_prose(tmp_path):
    # Prose mentions acceptance criteria without a heading -> still missing -> inject synthetic.
    prose = mk(tmp_path, "# spec\nThis spec currently has no acceptance criteria; to be added later\nL3 content\n")
    m = run_challenge(prose, "spec", "fast", [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert "acceptance_criteria" in m["preflight"]["missing_required_to_approve"]
    # Heading section ## Acceptance Criteria -> considered present.
    heading = mk(tmp_path, "# spec\n## Acceptance Criteria\nComplete within 10 seconds\nL4 x\n")
    m2 = run_challenge(heading, "spec", "fast", [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert "acceptance_criteria" not in m2["preflight"]["missing_required_to_approve"]


def test_artifact_type_mismatch_schema_invalid(tmp_path):
    text = "---\nartifact_type: plan\ntitle: t\nintent: i\n---\nBody line one\nBody line two\n"
    m = run_challenge(mk(tmp_path, text), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert m["verdict"] == "schema_invalid"


def test_crlf_frontmatter_parsed(tmp_path):
    text = "---\r\nartifact_type: spec\r\ntitle: t\r\nintent: i\r\nacceptance_criteria: [a]\r\nnon_goals: [n]\r\n---\r\nBody\r\n"
    m = run_challenge(mk(tmp_path, text), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert m["preflight"]["missing_required_to_approve"] == []  # CRLF frontmatter is recognized.


def test_non_utf8_artifact_no_crash(tmp_path):
    p = tmp_path / "gbk.md"
    p.write_bytes(b"\xff\xfeSpec acceptance criteria")
    assert main(["run", str(p), "--type", "spec"]) == 2  # Friendly exit instead of traceback.


def test_schema_invalid_manifest_has_preflight_key(tmp_path):
    m = run_challenge(mk(tmp_path, "  \n"), "spec", "fast",
                      [MockAdapter({"mock:execution-failure": cbody([])}, "mock")])
    assert "preflight" in m and "action" in m["panel_integrity"]  # Both manifest paths have the same shape.


# ── --type diff rubric ──────────────────────────────────────────────────────
_DIFF = ("diff --git a/foo.py b/foo.py\n"
         "index 1111111..2222222 100644\n"
         "--- a/foo.py\n"
         "+++ b/foo.py\n"
         "@@ -1,3 +1,4 @@\n"
         " def add(x, y):\n"
         "-    return x - y\n"
         "+    return x + y\n"
         "+    log(x)\n")


def dmk(tmp_path, text=_DIFF):
    p = tmp_path / "change.diff"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_diff_type_runs_no_longer_notimplemented(tmp_path):
    # Regression: `run <diff> --type diff` no longer raises NotImplementedError and returns a verdict like spec.
    sc = {"mock:regression": cbody([concern(span="L7-8", ft="regression_risk")])}
    m = run_challenge(dmk(tmp_path), "diff", "fast", [MockAdapter(sc, "mock")])
    assert m["artifact_type"] == "diff" and m["verdict"] in {v.value for v in Verdict}
    real = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]]
    assert len(real) == 1 and real[0]["failure_type"] == "regression_risk"


def test_diff_no_frontmatter_preflight_injection(tmp_path):
    # A diff is not a frontmatter artifact; never inject acceptance_criteria/non_goals synthetic concerns.
    m = run_challenge(dmk(tmp_path), "diff", "fast",
                      [MockAdapter({"mock:regression": cbody([])}, "mock")])
    assert m["preflight"]["missing_required_to_approve"] == []
    assert all(c["raised_by"] != ["preflight"] for c in m["concerns"])


def test_diff_rejects_spec_failure_type_out_of_enum(tmp_path):
    # A spec-only failure_type in a diff run is dropped out-of-enum and recorded, never silently swallowed.
    sc = {"mock:regression": cbody([concern(span="L7-8", ft="missing_acceptance_test")])}
    m = run_challenge(dmk(tmp_path), "diff", "fast", [MockAdapter(sc, "mock")])
    assert any(d["reason"] == "failure_type_out_of_enum" for d in m["dropped_concerns"])
    assert [c for c in m["concerns"] if c["raised_by"] != ["preflight"]] == []


def test_diff_clean_multi_family_approves(tmp_path):
    # Clean diff + complete cross-family panel + no live objections -> approve; diff has no frontmatter contract gate.
    sc = {"claude:regression": cbody([]), "gpt:correctness-security": cbody([]),
          "claude:test-coverage": cbody([])}
    m = run_challenge(dmk(tmp_path), "diff", "standard",
                      [MockAdapter(sc, "claude"), MockAdapter(sc, "gpt")])
    assert m["verdict"] == "approve" and m["source_diversity"]["families"] == 2


def test_diff_verified_concern_cross_family_gates(tmp_path):
    # Cross-family Verifier real with line-anchored reproduction -> request_changes through the same verdict pipeline as spec.
    sc = {"claude:regression": cbody([concern(span="L8-8", ft="regression_risk")]),
          "gpt:verifier": vbody("real", "At L8 addition changes to x+y while callers still expect subtraction, causing regression")}
    m = run_challenge(dmk(tmp_path), "diff", "fast",
                      [MockAdapter(sc, "claude"), MockAdapter(sc, "gpt")])
    c = [c for c in m["concerns"] if c["raised_by"] != ["preflight"]][0]
    assert m["verdict"] == "request_changes" and c["severity_verified"]


def test_empty_diff_schema_invalid(tmp_path):
    m = run_challenge(dmk(tmp_path, "   \n"), "diff", "fast",
                      [MockAdapter({"mock:regression": cbody([])}, "mock")])
    assert m["verdict"] == "schema_invalid"


def test_plan_decision_still_unsupported(tmp_path):
    # plan/decision enums are still missing, so they are rejected before run.
    for t in ("plan", "decision"):
        with pytest.raises(NotImplementedError):
            run_challenge(dmk(tmp_path), t, "fast", [MockAdapter({}, "mock")])


# ── weigh-options deliberation mode ───────────────────────────────────────────
from challenge_plans.deliberation import weigh_options  # noqa: E402

_OPTS = [{"id": "A", "text": "Option Alpha"}, {"id": "B", "text": "Option Beta"}]


def _vb(ranking, blockers=None):
    return json.dumps({"ranking": ranking, "first_choice": ranking[0],
                       "reasons": {x: "r" for x in ranking}, "blockers": blockers or []},
                      ensure_ascii=False) + "\n" + M


def _weigh(scripted, profile="standard"):
    return weigh_options("Choose Alpha or Beta?", _OPTS,
                         [MockAdapter(scripted, "claude"), MockAdapter(scripted, "gpt")], profile)


def test_deliberation_weighted_winner():
    m = _weigh({"claude:execution-failure": _vb(["A", "B"]), "gpt:correctness": _vb(["A", "B"]),
                "claude:scope-boundary": _vb(["A", "B"])})
    assert m["recommendation"] == "A"


def test_deliberation_family_cap_forces_tie_discuss():
    # 2 claude votes for A + 1 gpt vote for B -> raw 2:1 but weighted cap 1:1 -> discuss.
    m = _weigh({"claude:execution-failure": _vb(["A", "B"]), "gpt:correctness": _vb(["B", "A"]),
                "claude:scope-boundary": _vb(["A", "B"])})
    assert m["recommendation"] == "discuss"
    raw = {o["id"]: o["raw_first_choice"] for o in m["options"]}
    assert raw == {"A": 2, "B": 1}


def test_deliberation_blocker_on_winner_forces_discuss():
    # Winner A has an unverified blocker -> discuss for adversarial verification; do not adopt or switch to B directly.
    m = _weigh({"claude:execution-failure": _vb(["A", "B"], blockers=[
                    {"option_id": "A", "blocker": "irreversible", "anchor": "Option Alpha deletes the database and cannot be rolled back"}]),
                "gpt:correctness": _vb(["A", "B"]), "claude:scope-boundary": _vb(["A", "B"])})
    assert m["recommendation"] == "discuss" and m["winner_unverified_blocker"]


def test_deliberation_blocker_on_loser_no_veto():
    # A random blocker on non-winner B cannot veto or change the result; A still wins.
    m = _weigh({"claude:execution-failure": _vb(["A", "B"], blockers=[
                    {"option_id": "B", "blocker": "spurious", "anchor": "I do not like B"}]),
                "gpt:correctness": _vb(["A", "B"]), "claude:scope-boundary": _vb(["A", "B"])})
    assert m["recommendation"] == "A"


def test_deliberation_incomplete_ranking_rejected():
    # Ranking only the first choice is a truncated strategic vote -> parse_error -> missing, not a complete vote.
    partial = json.dumps({"ranking": ["A"], "first_choice": "A", "reasons": {}, "blockers": []},
                         ensure_ascii=False) + "\n" + M
    m = _weigh({"claude:execution-failure": _vb(["A", "B"]), "gpt:correctness": partial,
                "claude:scope-boundary": _vb(["A", "B"])})
    assert any(x["reason"] == "parse_error" for x in m["panel_integrity"]["missing"])


def test_deliberation_missing_vote_inconclusive():
    # One voter is truncated with no marker -> incomplete panel -> inconclusive.
    m = _weigh({"claude:execution-failure": _vb(["A", "B"]), "gpt:correctness": _vb(["A", "B"]),
                "claude:scope-boundary": '{"ranking":["A","B"]}'})
    assert m["recommendation"] == "inconclusive"


def test_weigh_options_requires_two_options():
    with pytest.raises(ValueError):
        weigh_options("?", [{"id": "A", "text": "x"}], [MockAdapter({}, "mock")])


# ── output language (single English-source, localized prose) ──────────────────
def test_lang_directive_default_english_is_noop(monkeypatch):
    from challenge_plans.prompts import lang_directive
    monkeypatch.delenv("CHALLENGE_PLANS_LANG", raising=False)
    assert lang_directive() == ""
    monkeypatch.setenv("CHALLENGE_PLANS_LANG", "en")
    assert lang_directive() == ""


def test_lang_directive_appended_but_marker_stays_last(monkeypatch):
    # Non-English must append the prose directive WITHOUT displacing END_MARKER as the final line,
    # otherwise the panel-integrity capture would treat the output as truncated.
    from challenge_plans.prompts import build_challenger_prompt, lang_directive
    from challenge_plans.verifier import build_verifier_prompt
    from challenge_plans.deliberation import build_voter_prompt
    monkeypatch.setenv("CHALLENGE_PLANS_LANG", "zh")
    assert "in zh" in lang_directive()
    c = Concern(artifact_span="L1-2", failure_type="x", severity=Severity.HIGH,
                title="t", evidence="e", concrete_failure_step="s")
    for prompt in (build_challenger_prompt("L1: x", "plan/spec", "lens.", ("x", "y"), 3),
                   build_verifier_prompt("L1: x", c, "plan/spec"),
                   build_voter_prompt("q?", [{"id": "A", "text": "a"}, {"id": "B", "text": "b"}], "l")):
        assert "in zh" in prompt
        assert prompt.rstrip().endswith(M)


def test_synthetic_preflight_localizes_but_keeps_field_key(monkeypatch):
    # Synthetic concerns never pass through a model, so --lang localizes their title/evidence in
    # Python; the machine-readable violated_contract_field must stay the English key for dedup.
    from challenge_plans.preflight import preflight_concerns
    monkeypatch.setenv("CHALLENGE_PLANS_LANG", "zh")
    by_field = {c.violated_contract_field: c for c in preflight_concerns({}, "no headings here")}
    assert set(by_field) == {"acceptance_criteria", "non_goals"}        # keys unchanged
    assert "验收标准" in by_field["acceptance_criteria"].title           # prose localized
    monkeypatch.setenv("CHALLENGE_PLANS_LANG", "en")
    en = {c.violated_contract_field: c for c in preflight_concerns({}, "no headings here")}
    assert "Missing measurable" in en["acceptance_criteria"].title       # English fallback intact


# ── doctor remediation (don't just report state — tell humans/agents how to fix it) ──
def test_doctor_remediation_hints_are_actionable():
    from challenge_plans.cli import _remediation
    from challenge_plans.adapters import ClaudeAdapter, CodexAdapter, ProbeState
    # not-logged-in must point at the login action; not-installed at an install path.
    assert "/login" in _remediation(ClaudeAdapter(), ProbeState.NOT_LOGGED_IN)
    assert "install" in _remediation(CodexAdapter(), ProbeState.NOT_INSTALLED).lower()
    # ready needs no remediation.
    assert _remediation(ClaudeAdapter(), ProbeState.READY) == ""
