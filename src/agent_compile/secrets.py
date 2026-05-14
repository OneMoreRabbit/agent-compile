"""Derive the agent's secret manifest from a resolved flavour_json + template manifest.

SecretRef shape (per [[openclaw-config-templates-brief-v0_2]] §1):

    { "source": "env", "id": "<NAME>" }

Anywhere this shape appears in the resolved JSON, ``<NAME>`` joins the secret
set. We also union in the template chain's declared ``secret_manifest``
(typically rare extras for custom skills).

Output schema matches [[openclaw-config-templates-brief-v0_2]] §2.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List


def _walk_secret_refs(node: Any) -> Iterator[str]:
    """Yield env-var ids from every SecretRef shape under ``node``."""
    if isinstance(node, dict):
        source = node.get("source")
        ident = node.get("id")
        if source == "env" and isinstance(ident, str) and ident:
            yield ident
            return
        for v in node.values():
            yield from _walk_secret_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_secret_refs(v)


def collect_names(
    flavour_json: Dict[str, Any], template_manifest: List[str]
) -> List[str]:
    """Return the sorted union of SecretRef ids + template manifest names."""
    names = set(_walk_secret_refs(flavour_json))
    names.update(template_manifest or [])
    return sorted(names)


def derive_secret_manifest(
    flavour_json: Dict[str, Any],
    template_manifest: List[str],
    agent_name: str,
    vault_prefix: str = "agents",
) -> List[Dict[str, Any]]:
    """Return the secrets manifest as a list of dicts ready for YAML emission."""
    names = collect_names(flavour_json, template_manifest)
    return [
        {
            "name": name,
            "vault_path": f"{vault_prefix}/{agent_name}/{name}",
            "required": True,
        }
        for name in names
    ]
