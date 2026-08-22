"""Driven (outbound) adapters: profile-specific implementations of each port.

``local`` is the SDK-free working offline stack (the test/CI default); ``gcp`` holds the managed
cloud implementations with lazy SDK imports; ``onprem`` holds fail-fast portability placeholders.
"""
