"""Skills: pluggable rule and metadata modules.

Importing this package registers every built-in skill.
"""
from alexed_bru.skills import rules as _rules  # noqa: F401  (registers rules)
from alexed_bru.skills.metadata import providers as _providers  # noqa: F401
