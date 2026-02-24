"""
constants.py

This module contains constant values that are used throughout the application.
"""

from pathlib import Path

GIT_TMP = Path("./tmp")

# General constants
MAX_RETRIES = 5
RETRY_AFTER = 60
TIMEOUT = 30

# ISE-specific constants
# ISE ERS API pagination size parameter
# Using a page size of 100 reduces API calls significantly for large deployments
# (e.g., from 500+ to 100 calls for 10,000 endpoints vs default size of 20)
ISE_ERS_PAGE_SIZE = 100
