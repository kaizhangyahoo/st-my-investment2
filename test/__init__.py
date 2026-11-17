"""Test suites for the FastAPI backend and the legacy API clients.

Layout:

    test/unitTest/          one function or class in isolation, no orchestration
    test/functionalTest/    a feature exercised through its real entry point, offline
    test/nonFunctionalTest/ performance and resilience, not "does it work"
    test/support/           shared stubs and fixtures

Everything here is offline. Run from the REPO ROOT -- `backend` is a PEP 420 namespace
package, so the root has to be on sys.path and `-t .` is not optional:

    python -m unittest discover -s test -t .
    python -m unittest discover -s test/unitTest -t .

Browser-level end-to-end tests are not here: they live with the skill that owns them,
at `.agent/skills/playwright_testing/examples/`, and they target the legacy Streamlit
app on port 8501 rather than this backend.
"""
