# constants.py

AUTH_TYPE_MAPPING = {
    "ISE": "basic",
    "SDWAN": "token",
    # Add other solutions here
}

AUTH_ENDPOINT_MAPPING = {
    "ise_openapi": "/admin/API/apiService/get",
    "ise_ers": "/admin/API/NetworkAccessConfig/ERS",
    "sdwan": "/j_security_check",
    # Add other solutions here
}

SOLUTION_ENDPOINTS = {
    "ISE": ["ise_openapi", "ise_ers"],
    "SDWAN": ["sdwan"],
    # Add other solutions here
}

SOLUTION_AUTH_ENDPOINTS = {
    "ISE": ["/admin/API/NetworkAccessConfig/ERS", "/admin/API/apiService/get"],
    "SDWAN": ["/j_security_check"],
    # Add other solutions here
}

GIT_TMP = "./tmp"

MAX_RETRIES = 5
RETRY_AFTER = 60
TIMEOUT = 10
