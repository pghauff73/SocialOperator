from pathlib import Path

from socialoperator.config import load_config, load_site_policy
from socialoperator.policy.actions import authorize_action
from socialoperator.policy.domains import is_url_allowed
from socialoperator.policy.relevance import ScopeClassifier
from socialoperator.types import ActionRisk, OwnershipClass

ROOT = Path(__file__).resolve().parents[1]


def test_domain_and_action_policy_are_fail_closed() -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    assert is_url_allowed("http://127.0.0.1/project.html", policy)
    assert not is_url_allowed("https://example.com/project.html", policy)
    assert authorize_action(ActionRisk.NAVIGATE, config=config, site_policy=policy).allowed
    assert not authorize_action(
        ActionRisk.EXTERNAL_EFFECT,
        config=config,
        site_policy=policy,
    ).allowed


def test_scope_classifier_separates_owned_third_party_and_uncertain() -> None:
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    classifier = ScopeClassifier()
    owned = classifier.classify("This is synthetic user-owned portfolio data.", policy)
    assert owned.ownership_class is OwnershipClass.OWNED_BY_USER
    third_party = classifier.classify("Private message from another person", policy)
    assert third_party.ownership_class is OwnershipClass.THIRD_PARTY_REFERENCE
    uncertain = classifier.classify("An unrelated page", policy)
    assert uncertain.ownership_class is OwnershipClass.UNCERTAIN
