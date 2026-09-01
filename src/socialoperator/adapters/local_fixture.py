from __future__ import annotations

from socialoperator.adapters.base import DeclarativeSiteAdapter
from socialoperator.config import SitePolicy


def create_local_fixture_adapter(policy: SitePolicy) -> DeclarativeSiteAdapter:
    if policy.site_id != "local_fixture" or policy.real_site:
        raise ValueError("local fixture adapter requires the synthetic local_fixture policy")
    return DeclarativeSiteAdapter(
        policy=policy,
        adapter_version="1.0.0",
        required_heading_phrases=("SocialOperator Synthetic Profile",),
        required_target_names=("Open project details", "Read the synthetic project"),
        forbidden_text_phrases=("real account data",),
    )
