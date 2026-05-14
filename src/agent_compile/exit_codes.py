"""Tool-level exit codes.

Range 30-39, distinct from image-compile (20-29) and the wrapper container (3-7).
See `integrations/agent-compile-build-brief-v0_1.md` §Error handling and exit codes.
"""

SUCCESS = 0
TEMPLATE_EXISTS = 30
TEMPLATE_SCHEMA = 31
NOT_FOUND = 32
CYCLE = 33
FLAVOUR_MISMATCH = 34
MATRIX_BROKEN = 35
TEST_FAILED = 36
SNAPSHOT_FAILED = 37
WRITE_FAILED = 38
CONFIG = 39
