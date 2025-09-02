# NDFC (Nexus Dashboard Fabric Controller) Support

This document describes the NDFC integration added to the nac-collector tool.

## Overview

The `CiscoClientNDFC` class provides support for connecting to Cisco Nexus Dashboard Fabric Controller (NDFC) and collecting configuration data via its REST API.

## Authentication

NDFC uses token-based authentication with the following characteristics:

- **Endpoint**: `POST /login`
- **Authentication Type**: Token-based (JWT)
- **Required Parameters**:
  - `domain`: NDFC domain (default: "local")
  - `userName`: NDFC username
  - `userPasswd`: NDFC password

### Authentication Flow

1. Send POST request to `/login` endpoint with credentials
2. Receive JWT token in response
3. Use token in `Authorization: Bearer <token>` header for subsequent API calls

## Usage

### Command Line

```bash
# Basic usage with default domain (local)
nac-collector -s NDFC -u admin -p password -url https://ndfc.example.com

# With custom domain
nac-collector -s NDFC -u admin -p password -url https://ndfc.example.com -d CustomDomain

# With custom endpoints file and output
nac-collector -s NDFC -u admin -p password -url https://ndfc.example.com \
  -d local -e custom_ndfc_endpoints.yaml -o ndfc_config.json

# With debug logging
nac-collector -s NDFC -u admin -p password -url https://ndfc.example.com \
  -d local -v DEBUG

# Using environment variables
export NAC_USERNAME=admin
export NAC_PASSWORD=password
export NAC_URL=https://ndfc.example.com
export NAC_DOMAIN=local
nac-collector -s NDFC
```

### Parameters

| Parameter | Short | Required | Default | Description |
|-----------|-------|----------|---------|-------------|
| `--solution` | `-s` | Yes | - | Must be set to "NDFC" |
| `--username` | `-u` | Yes | - | NDFC username (or set NAC_USERNAME env var) |
| `--password` | `-p` | Yes | - | NDFC password (or set NAC_PASSWORD env var) |
| `--url` | `-url` | Yes | - | NDFC base URL (or set NAC_URL env var) |
| `--domain` | `-d` | No | "local" | NDFC authentication domain (or set NAC_DOMAIN env var) |
| `--endpoints-file` | `-e` | No | endpoints_ndfc.yaml | Path to endpoints YAML file |
| `--output` | `-o` | No | - | Not used for NDFC (data saved to fabric-specific file) |
| `--verbosity` | `-v` | No | WARNING | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) |

**Note**: For NDFC, data is automatically saved to `nac_collector/resources/NDFC_{FABRIC_NAME}_fabric_settings.json` instead of a general output file.
