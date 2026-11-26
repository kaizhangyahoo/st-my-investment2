"""The three JSON files the backend owns, each behind a store object (P1).

The point of the indirection is S4, where these become Firestore collections: a store is the
one place that knows how a file is laid out, so swapping the backing implementation does not
touch a caller. Until then each service keeps exporting module-level functions that delegate to
a default store instance, so P1 changes no call sites.

Every store resolves `settings.*_FILE` inside the call rather than caching it at construction.
The tests point the paths at a temp directory by patching the settings object after import, and
a path captured in `__init__` would ignore them -- and in Compose the same indirection is what
lets one env var move the file.
"""
