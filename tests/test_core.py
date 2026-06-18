"""Offline unit tests — no API calls. Run: pytest"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from intake_agent.approvals import AutoApprover, ReviewApprover
from intake_agent.config import Config, load_config, save_config
from intake_agent.extract import extract
from intake_agent.ledger import Ledger
from intake_agent.models import Outcome, Verdict
from intake_agent.mover import Mover
from intake_agent.profile import build_repo_profile
from intake_agent.tools import SandboxError, ToolContext


def _mover(tmp_path: Path, policy="auto") -> Mover:
    repo = tmp_path / "repo"
    (repo / "00_intake" / "review").mkdir(parents=True)
    cfg = Config(repo_root=str(repo), new_folder_policy=policy)
    ledger = Ledger(db_path=tmp_path / "h.db")
    approver = AutoApprover() if policy == "auto" else ReviewApprover()
    return Mover(cfg, ledger, approver, logging.getLogger("test"))


# ------------------------------------------------------------------- config
def test_config_roundtrip(tmp_path: Path):
    cfg = Config(repo_root=str(tmp_path), model="claude-x", new_folder_policy="review",
                 confidence_threshold=0.7)
    path = save_config(cfg, tmp_path / "config.toml")
    loaded = load_config(path)
    assert loaded.repo_root == str(tmp_path)
    assert loaded.model == "claude-x"
    assert loaded.new_folder_policy == "review"
    assert loaded.confidence_threshold == 0.7


def test_config_validate_catches_missing_repo(tmp_path: Path):
    cfg = Config(repo_root=str(tmp_path / "nope"))
    assert any("does not exist" in p for p in cfg.validate())


def test_intake_can_be_absolute(tmp_path: Path):
    external = tmp_path / "Downloads"
    cfg = Config(repo_root=str(tmp_path / "repo"), intake_dir=str(external))
    assert cfg.intake_path == external


# -------------------------------------------------------------- sandbox/tools
def test_sandbox_blocks_escape(tmp_path: Path):
    repo = tmp_path / "repo"; repo.mkdir()
    staged = tmp_path / "stage" / "f.txt"; staged.parent.mkdir(); staged.write_text("x")
    ctx = ToolContext(repo_root=repo, staged_file=staged)
    assert ctx.resolve("sub/file.txt") == (repo / "sub/file.txt").resolve()
    assert ctx.resolve(str(staged)) == staged.resolve()
    with pytest.raises(SandboxError):
        ctx.resolve("../../etc/passwd")
    with pytest.raises(SandboxError):
        ctx.resolve(str(tmp_path / "secret.txt"))


# ----------------------------------------------------------------- mover
def test_dest_traversal_rejected(tmp_path: Path):
    m = _mover(tmp_path)
    with pytest.raises(ValueError):
        m._safe_dest_folder("../escape")
    with pytest.raises(ValueError):
        m._safe_dest_folder("")


def test_safe_filename(tmp_path: Path):
    m = _mover(tmp_path)
    assert m._safe_filename("keep", "orig.pdf") == "orig.pdf"
    assert m._safe_filename("2026_invoice.pdf", "orig.pdf") == "2026_invoice.pdf"
    # missing extension is restored from the original
    assert m._safe_filename("2026_invoice", "orig.pdf") == "2026_invoice.pdf"
    # path components are stripped
    assert m._safe_filename("../../evil.pdf", "orig.pdf") == "evil.pdf"


def test_move_and_dedup(tmp_path: Path):
    m = _mover(tmp_path)
    src = m.config.intake_path / "a.txt"
    src.write_text("hello")
    v = Verdict(Outcome.MOVE, dest_folder="docs/", new_filename="keep", confidence=0.9, reason="r")
    res = m.apply(v, src)
    assert res.outcome == Outcome.MOVE
    assert res.dest_path.exists()
    assert res.dest_path.relative_to(m.config.repo_path).as_posix() == "docs/a.txt"

    # identical content dropped again -> duplicate -> review
    src2 = m.config.intake_path / "a.txt"
    src2.write_text("hello")
    res2 = m.apply(v, src2)
    assert res2.outcome == Outcome.REVIEW


def test_low_confidence_downgraded(tmp_path: Path):
    m = _mover(tmp_path)
    src = m.config.intake_path / "b.txt"; src.write_text("x")
    v = Verdict(Outcome.MOVE, dest_folder="docs/", confidence=0.1, reason="unsure")
    res = m.apply(v, src)
    assert res.outcome == Outcome.REVIEW


def test_review_policy_blocks_new_folder(tmp_path: Path):
    m = _mover(tmp_path, policy="review")
    src = m.config.intake_path / "c.txt"; src.write_text("x")
    v = Verdict(Outcome.MOVE, dest_folder="brand/new/folder/", confidence=0.9, reason="r")
    res = m.apply(v, src)
    assert res.outcome == Outcome.REVIEW


def test_undo_restores(tmp_path: Path):
    m = _mover(tmp_path)
    src = m.config.intake_path / "d.txt"; src.write_text("y")
    v = Verdict(Outcome.MOVE, dest_folder="filed/", confidence=0.9, reason="r")
    res = m.apply(v, src)
    assert res.ledger_id is not None
    restored = m.undo(res.ledger_id)
    assert (m.config.intake_path / "d.txt").exists()
    assert "00_intake" in restored
    # folder we created should be pruned
    assert not (m.config.repo_path / "filed").exists()


# ----------------------------------------------------------------- profile
def test_profile_excludes_inbox_and_noise(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "admin" / "Finance").mkdir(parents=True)
    (repo / "00_intake").mkdir()
    (repo / ".git").mkdir()
    (repo / "node_modules").mkdir()
    text = build_repo_profile(repo, repo / "00_intake")
    assert "admin/" in text and "Finance/" in text
    assert "00_intake" not in text
    assert ".git" not in text and "node_modules" not in text


# ----------------------------------------------------------------- watcher skip
def test_rules_file_is_never_routed(tmp_path: Path):
    from intake_agent.watcher import IntakeService
    repo = tmp_path / "repo"
    (repo / "00_intake" / "review").mkdir(parents=True)
    cfg = Config(repo_root=str(repo), rules_file="00_intake/intake.rules.md")
    cfg.rules_path.write_text("# rules", encoding="utf-8")
    svc = IntakeService(cfg, "sk-ant-fake")
    try:
        doc = cfg.intake_path / "invoice.pdf"; doc.write_text("x")
        assert svc._should_skip(cfg.rules_path) is True
        assert svc._should_skip(doc) is False
    finally:
        svc.ledger.close()


# ----------------------------------------------------------------- extract
def test_extract_text(tmp_path: Path):
    f = tmp_path / "n.txt"; f.write_text("Invoice from Acme")
    r = extract(f)
    assert r.kind == "text" and "Acme" in r.text
