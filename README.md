[![Tests](https://github.com/netascode/nac-collector/actions/workflows/test.yml/badge.svg)](https://github.com/netascode/nac-collector/actions/workflows/test.yml)
![Python Support](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-informational "Python Support: 3.10, 3.11, 3.12, 3.13")

# nac-collector

A CLI tool to collect data from network infrastructure devices. Supports both controller-based architectures (single controller manages multiple devices) and device-based architectures (direct device connections via RESTCONF API or SSH).

## Installation

### Using uv (recommended)

```bash
uv tool install git+https://github.com/netascode/nac-collector.git
```

### Using pip

```bash
pip install git+https://github.com/netascode/nac-collector.git
```

## Usage

The tool supports two types of architectures:
- **Controller-based**: SDWAN, ISE, NDO, FMC, CATALYSTCENTER (require `--url`)
- **Device-based**: IOSXE, IOSXR, NXOS (require `--devices-file`)

```
Usage: nac-collector [OPTIONS]

A CLI tool to collect various network configurations.

Options:
  * -s, --solution [SDWAN|ISE|NDO|FMC|CATALYSTCENTER|IOSXE|IOSXR|NXOS]
                        Solutions supported [required]
  * -u, --username TEXT Username for authentication [required]
                        [env var: NAC_USERNAME]
  * -p, --password TEXT Password for authentication [required]
                        [env var: NAC_PASSWORD]
  * --url TEXT          Base URL for the service (required for controller-based solutions)
                        [env var: NAC_URL]
  --api-token TEXT      API token for authentication (SDWAN 20.18+ only).
                        If set, --username/--password are not required.
                        [env var: NAC_API_TOKEN]
  -v, --verbosity [CRITICAL|ERROR|WARNING|INFO|DEBUG]
                        Log level [default: WARNING]
  -f, --fetch-latest    Fetch the latest endpoint definitions from
                        upstream sources
  -e, --endpoints-file TEXT
                        Path to the endpoints YAML file
  -t, --timeout INTEGER
                        Request timeout in seconds [default: 30]
  -o, --output TEXT     Path to the output ZIP file [default: nac-collector.zip]
  --devices-file TEXT   Path to the device inventory YAML file (for device-based solutions)
  --version             Show version and exit
  --help                Show this message and exit
```

Set environment variables pointing to supported solution instance:

```shell
export NAC_USERNAME=admin
export NAC_PASSWORD=Cisco123
export NAC_URL=https://10.1.1.1
```

For SDWAN 20.18+ API token authentication:

```shell
export NAC_API_TOKEN=<your-jwt-token>
export NAC_URL=https://10.1.1.1
```

## Examples

### SDWAN

Using uv (development):

```sh
# With environment variables
uv run nac-collector -s SDWAN -v DEBUG --fetch-latest

# Without environment variables
uv run nac-collector -s SDWAN --username USERNAME --password PASSWORD --url URL -v DEBUG --fetch-latest
```

Using API token (Manager 20.18+):

```sh
# With environment variable
export NAC_API_TOKEN=<your-jwt-token>
nac-collector -s SDWAN --url URL -v DEBUG --fetch-latest

# With CLI flag
nac-collector -s SDWAN --api-token <your-jwt-token> --url URL -v DEBUG --fetch-latest
```

> **Note:** `--api-token` is only supported with the SDWAN solution and requires Manager version 20.18+.
> When `--api-token` is provided, it takes precedence over `--username`/`--password` (which become optional).

Using installed package:

```sh
nac-collector -s SDWAN -v DEBUG --fetch-latest
```

### ISE

```sh
# With environment variables
nac-collector -s ISE -v DEBUG --fetch-latest

# Without environment variables
nac-collector -s ISE --username USERNAME --password PASSWORD --url URL -v DEBUG --fetch-latest
```

### Catalyst Center

```sh
# With environment variables
nac-collector -s CATALYSTCENTER -v DEBUG

# Without environment variables
nac-collector -s CATALYSTCENTER --username USERNAME --password PASSWORD --url URL -v DEBUG

Catalyst center should NOT use "--fetch-latest"
```

Catalyst Center contains some custom logic, explained in [README_catalyst_center.md](README_catalyst_center.md).

### FMC / CDFMC

```sh
# FMC With environment variables
nac-collector -s FMC -v DEBUG -e nac_collector/resources/endpoints/fmc.yaml

# FMC Without environment variables
nac-collector -s FMC --username USERNAME --password PASSWORD --url URL -v DEBUG -e nac_collector/resources/endpoints/fmc.yaml

# cdFMC With environment variables
nac-collector -s CDFMC -v DEBUG -e nac_collector/resources/endpoints/fmc.yaml

# cdFMC Without environment variables
nac-collector -s CDFMC --username none --password API_TOKEN --url URL -v DEBUG -e nac_collector/resources/endpoints/fmc.yaml
```
Notes:
- cdFMC requires username to be set, even though it's going to be ignored
- It is recommended to use the pre-populated endpoints list (via the `-e` option) instead of the auto-generated list (using `--fetch-latest`)

### NDO

```sh
# With environment variables
uv run nac-collector -s NDO -v DEBUG

# Without environment variables
uv run nac-collector -s NDO --username USERNAME --password PASSWORD --domain DOMAIN --url URL -v DEBUG
```

Using installed package:

```sh
nac-collector -s NDO -v DEBUG
```

### Meraki

The Meraki collector authenticates with an API key (passed as `--password`).

```sh
nac-collector -s MERAKI --username none --password "$MERAKI_API_KEY" --url 'https://api.meraki.com/api/v1' -v INFO --fetch-latest
```

#### Speeding up collection — filter by Organization and Network

In large environments with many organizations and networks, collection can take a long time because each network and device spawns a large number of child API calls. Use the optional scope filters below to target only the orgs and networks you need, which significantly reduces collection time.

| Variable | Purpose |
|---|---|
| `NAC_MERAKI_ORG_IDS` | Comma-separated list of org IDs. Only these orgs are collected. |
| `NAC_MERAKI_NETWORK_IDS` | Comma-separated list of network IDs. Only these networks (and devices within them) are collected; all others are dropped. |

Both filters can be used independently or together. When combined, only the specified networks within the specified orgs are collected.

```sh
# Collect a single org only
export NAC_MERAKI_ORG_IDS="1234567"

# Further narrow to specific networks within that org
export NAC_MERAKI_NETWORK_IDS="N_abc123def456,N_ghi789jkl012"

nac-collector -s MERAKI --username none --password "$MERAKI_API_KEY" --url 'https://api.meraki.com/api/v1' -v INFO --fetch-latest
```

All child data for each network that passes the filter is still collected in full (SSIDs, firewall rules, switch stacks, syslog servers, etc.).

**Note:** `NAC_MERAKI_NETWORK_IDS` only controls which networks (and their child endpoints) are collected. Org-level endpoints (admins, SAML, policy objects, etc.) are always collected in full regardless of this filter.

**Note:** Networks referred to by org-level configuration or other networks' configuration are not automatically added to the filter. Make sure to add them to the filter manually for network IDs referred to to make sense within the collected data.

### NDFC

```sh
# Required: target fabric name for data collection
export NDFC_FABRIC_NAME="FAB1"

nac-collector -s NDFC --username USERNAME --password PASSWORD --url URL -v INFO
```

### IOSXE (Device-Based Collection)

IOSXE uses a device-based architecture where configuration is collected directly from individual devices using RESTCONF API or SSH. This requires a device inventory file instead of a single controller URL.

**Supported Protocols:**
- **RESTCONF** (default): Uses HTTPS API calls to `/restconf/data/Cisco-IOS-XE-native:native`
- **SSH**: Executes `show running-config | format restconf-json` command

#### Device Inventory File

Create a YAML file with your device inventory:

```yaml
- name: Switch1
  target: https://switch1.example.com  # RESTCONF via HTTPS
  username: admin
  password: cisco123
  protocol: restconf  # default, can be omitted
- name: Switch2
  target: switch2.example.com  # SSH connection
  protocol: ssh
  # username/password will use CLI defaults if not specified
- name: Router1
  target: router1.example.com:2222  # SSH with custom port
  username: router_admin
  protocol: ssh
  # password will use CLI default
```

#### Usage Examples

```sh
# Using device inventory file
nac-collector -s IOSXE --username admin --password cisco123 --devices-file devices.yaml -v DEBUG

# Using environment variables for default credentials
export NAC_USERNAME=admin
export NAC_PASSWORD=cisco123
nac-collector -s IOSXE --devices-file devices.yaml -v DEBUG

# Custom output file
nac-collector -s IOSXE --devices-file devices.yaml --output my-collection.zip
```

#### Output Format

For device-based collection, the output ZIP archive contains individual JSON files for each device:

```
nac-collector.zip
├── Switch1.json
├── Switch2.json
└── Router1.json
```

Each JSON file contains the complete configuration data for that device in JSON format.

### IOSXR (Device-Based Collection)

IOSXR uses a device-based architecture where configuration is collected directly from individual devices using SSH. IOS-XR devices only support SSH collection.

**Supported Protocols:**
- **SSH** (only): Executes `show running-config | json unified-model` command

#### Device Inventory File

Create a YAML file with your IOS-XR device inventory:

```yaml
- name: Router1
  target: router1.example.com  # SSH connection
  username: admin
  password: cisco123
- name: Router2
  target: 10.1.1.2:22  # SSH with explicit port
  protocol: ssh  # optional, SSH is default and only supported protocol
  # username/password will use CLI defaults if not specified
- name: Router3
  target: router3.example.com
  username: router_admin
  # password will use CLI default
```

#### Usage Examples

```sh
# Using device inventory file
nac-collector -s IOSXR --username admin --password cisco123 --devices-file routers.yaml -v DEBUG

# Using environment variables for default credentials
export NAC_USERNAME=admin
export NAC_PASSWORD=cisco123
nac-collector -s IOSXR --devices-file routers.yaml -v DEBUG

# Custom output file
nac-collector -s IOSXR --devices-file routers.yaml --output iosxr-configs.zip
```

#### Output Format

For IOS-XR collection, the output ZIP archive contains individual JSON files for each router:

```
iosxr-configs.zip
├── Router1.json
├── Router2.json
└── Router3.json
```

Each JSON file contains the complete configuration data in IOS-XR JSON unified model format. The tool automatically filters out timestamp headers and comments that may appear before the JSON data.

### NXOS (Device-Based Collection)

NXOS uses a device-based architecture where configuration is collected directly from individual Nexus switches using REST API.

**Supported Protocols:**
- **REST** (only): Uses HTTPS API calls to `/api/mo/sys.json?rsp-subtree=full&rsp-prop-include=set-config-only`

#### Device Inventory File

Create a YAML file with your NXOS device inventory:

```yaml
- name: Switch1
  target: https://switch1.example.com  # REST via HTTPS
  username: admin
  password: cisco123
  protocol: rest  # default, can be omitted
- name: Switch2
  target: switch2.example.com  # HTTPS scheme will be added automatically
  username: switch_admin
  # password will use CLI default if not specified
- name: Switch3
  target: 10.1.1.3:443  # HTTPS with custom port
  # username/password will use CLI defaults if not specified
```

#### Usage Examples

```sh
# Using device inventory file
nac-collector -s NXOS --username admin --password cisco123 --devices-file switches.yaml -v DEBUG

# Using environment variables for default credentials
export NAC_USERNAME=admin
export NAC_PASSWORD=cisco123
nac-collector -s NXOS --devices-file switches.yaml -v DEBUG

# Custom output file
nac-collector -s NXOS --devices-file switches.yaml --output nxos-configs.zip
```

#### Output Format

For NXOS collection, the output ZIP archive contains individual JSON files for each switch:

```
nxos-configs.zip
├── Switch1.json
├── Switch2.json
└── Switch3.json
```

Each JSON file contains the complete configuration data in NXOS JSON format. The tool automatically handles aaaLogin authentication and session management for each device.

**Note:** Device-based solutions like IOSXE, IOSXR, and NXOS do not use endpoint files (`--endpoints-file` and `--fetch-latest` are ignored).
