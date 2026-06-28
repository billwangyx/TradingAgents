import contextlib
import warnings

# Load .env files at package import so DEFAULT_CONFIG's env-var overlay
# (and every llm_clients consumer) sees the user's keys regardless of
# which entry point started the process. find_dotenv(usecwd=True) walks
# from the CWD, so the installed `tradingagents` console script picks up
# the project's .env instead of stepping up from site-packages.
# load_dotenv defaults to override=False, so it never clobbers values
# the caller has already exported.
import os as _os

try:
    from dotenv import find_dotenv, load_dotenv

    _dotenv_override = _os.environ.get("TRADINGAGENTS_DOTENV_OVERRIDE", "").lower() in ("true", "1", "yes", "on")
    # Use utf-8-sig to tolerate BOM written by PowerShell Set-Content
    load_dotenv(find_dotenv(usecwd=True), encoding="utf-8-sig", override=_dotenv_override)
    load_dotenv(find_dotenv(".env.enterprise", usecwd=True), encoding="utf-8-sig", override=False)
    del _os
    del _dotenv_override
except ImportError:
    pass

# langchain-core 1.3.3 calls surface_langchain_deprecation_warnings() in
# its own __init__, which prepends default-action filters for its
# subclassed warning categories. To suppress a specific warning we must
# install our filter AFTER langchain-core has installed its own, so import
# it first. The package is a guaranteed transitive dep via langgraph.
with contextlib.suppress(ImportError):
    import langchain_core  # noqa: F401

# langgraph-checkpoint 4.0.3 calls Reviver() at module load without an
# explicit allowed_objects, which triggers a noisy pending-deprecation
# warning from langchain-core 1.3.3 on every interpreter start. The fix
# is already merged upstream (langchain-ai/langgraph#7743, 2026-05-08)
# and will arrive in the next langgraph-checkpoint release. Remove this
# block (and the langchain_core preload above) when we bump past it.
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects`.*",
    category=PendingDeprecationWarning,
)
