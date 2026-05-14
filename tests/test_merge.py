"""Tests for the three merge rules."""

from __future__ import annotations

import pytest

from agent_compile.merge import merge_json, merge_skills, merge_workspace


# --- merge_json: dict deep-merge -------------------------------------------


def test_merge_json_empty_override_keeps_parent():
    assert merge_json({"a": 1, "b": 2}, {}) == {"a": 1, "b": 2}


def test_merge_json_empty_parent_takes_override():
    assert merge_json({}, {"a": 1}) == {"a": 1}


def test_merge_json_scalar_replace():
    assert merge_json({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_json_nested_dict_merge():
    parent = {"a": {"x": 1, "y": 2}}
    override = {"a": {"y": 20, "z": 3}}
    assert merge_json(parent, override) == {"a": {"x": 1, "y": 20, "z": 3}}


def test_merge_json_deep_nested():
    parent = {"a": {"b": {"c": {"d": 1}}}}
    override = {"a": {"b": {"c": {"e": 2}}}}
    assert merge_json(parent, override) == {"a": {"b": {"c": {"d": 1, "e": 2}}}}


def test_merge_json_adds_new_key():
    assert merge_json({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


# --- merge_json: list rules ------------------------------------------------


def test_merge_json_list_replace_not_append():
    assert merge_json({"a": [1, 2, 3]}, {"a": [4, 5]}) == {"a": [4, 5]}


def test_merge_json_list_replace_empty():
    assert merge_json({"a": [1, 2, 3]}, {"a": []}) == {"a": []}


def test_merge_json_list_to_scalar():
    """Type-mismatched override wins."""
    assert merge_json({"a": [1, 2]}, {"a": "hello"}) == {"a": "hello"}


# --- merge_json: null-deletes-key ------------------------------------------


def test_merge_json_null_deletes_top_level_key():
    assert merge_json({"a": 1, "b": 2}, {"a": None}) == {"b": 2}


def test_merge_json_null_deletes_nested_key():
    parent = {"a": {"x": 1, "y": 2}}
    override = {"a": {"x": None}}
    assert merge_json(parent, override) == {"a": {"y": 2}}


def test_merge_json_null_on_absent_key_is_noop():
    assert merge_json({"a": 1}, {"b": None}) == {"a": 1}


def test_merge_json_null_deletes_dict():
    """Setting a dict-valued key to null removes the whole subtree."""
    parent = {"a": {"x": 1, "y": {"deep": True}}}
    override = {"a": None}
    assert merge_json(parent, override) == {}


def test_merge_json_null_deletes_list():
    parent = {"a": [1, 2, 3]}
    override = {"a": None}
    assert merge_json(parent, override) == {}


# --- merge_json: immutability of inputs ------------------------------------


def test_merge_json_does_not_mutate_parent():
    parent = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    _ = merge_json(parent, override)
    assert parent == {"a": {"x": 1}}


def test_merge_json_does_not_mutate_override():
    parent = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    _ = merge_json(parent, override)
    assert override == {"a": {"y": 2}}


# --- merge_workspace -------------------------------------------------------


def test_merge_workspace_replaces_existing_file():
    parent = {"AGENTS.md": "old", "SOUL.md": "soul"}
    override = {"AGENTS.md": "new"}
    assert merge_workspace(parent, override) == {"AGENTS.md": "new", "SOUL.md": "soul"}


def test_merge_workspace_adds_new_file():
    parent = {"AGENTS.md": "a"}
    override = {"TOOLS.md": "t"}
    assert merge_workspace(parent, override) == {"AGENTS.md": "a", "TOOLS.md": "t"}


def test_merge_workspace_empty_override():
    parent = {"AGENTS.md": "a"}
    assert merge_workspace(parent, {}) == {"AGENTS.md": "a"}


def test_merge_workspace_does_not_mutate_parent():
    parent = {"AGENTS.md": "a"}
    _ = merge_workspace(parent, {"AGENTS.md": "b"})
    assert parent == {"AGENTS.md": "a"}


# --- merge_skills ----------------------------------------------------------


def test_merge_skills_union_preserves_parent_order():
    parent = ["a", "b", "c"]
    override = {"add": ["d", "e"]}
    assert merge_skills(parent, override) == ["a", "b", "c", "d", "e"]


def test_merge_skills_dedupes_existing():
    parent = ["a", "b"]
    override = {"add": ["b", "c"]}
    assert merge_skills(parent, override) == ["a", "b", "c"]


def test_merge_skills_empty_override():
    parent = ["a", "b"]
    assert merge_skills(parent, {}) == ["a", "b"]


def test_merge_skills_no_add_key():
    parent = ["a"]
    assert merge_skills(parent, {"remove": ["a"]}) == ["a"]  # remove not supported MVP


def test_merge_skills_empty_parent():
    assert merge_skills([], {"add": ["a", "b"]}) == ["a", "b"]
