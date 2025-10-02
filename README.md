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

## Examples

### SDWAN

Using uv (development):

```sh
# With environment variables
uv run nac-collector -s SDWAN -v DEBUG --fetch-latest

# Without environment variables
uv run nac-collector -s SDWAN --username USERNAME --password PASSWORD --url URL -v DEBUG --fetch-latest
```

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
nac-collector -s CATALYSTCENTER -v DEBUG --fetch-latest

# Without environment variables
nac-collector -s CATALYSTCENTER --username USERNAME --password PASSWORD --url URL -v DEBUG --fetch-latest
```

Catalyst Center contains some custom logic, explained in [README_catalyst_center.md](README_catalyst_center.md).

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
