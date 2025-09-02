# INSTRUCTION

## Installation

This project uses [Poetry](https://python-poetry.org/) for dependency management.

You can install the project with the following command:

```bash
poetry install
```

Or with pip:

```bash
pip3 install .
```

## Usage

```cli
Usage: nac-collector [OPTIONS]

  A CLI tool to collect various network configurations.

Options:
  --version                       Show the version and exit.
  -v, --verbosity LVL             Either CRITICAL, ERROR, WARNING, INFO or
                                  DEBUG
  -s, --solution [SDWAN|ISE|NDO|FMC|CATALYSTCENTER]
                                  Solutions supported [SDWAN, ISE, NDO, FMC,
                                  CATALYSTCENTER]  [required]
  -u, --username TEXT             Username for authentication. Can also be set
                                  using the NAC_USERNAME environment variable
                                  [required]
  -p, --password TEXT             Password for authentication. Can also be set
                                  using the NAC_PASSWORD environment variable
                                  [required]
  -url, --url TEXT                Base URL for the service. Can also be set
                                  using the NAC_URL environment variable
                                  [required]
  -g, --git-provider              Generate endpoint.yaml automatically using
                                  provider github repo
  -e, --endpoints-file TEXT       Path to the endpoints YAML file
  -t, --timeout INTEGER           Request timeout in seconds. Default is 30.
  -o, --output TEXT               Path to the output json file
  -h, --help                      Show this message and exit.
```

Set environment variables pointing to supported solution instance:

```shell
export NAC_USERNAME=admin
export NAC_PASSWORD=Cisco123
export NAC_URL=https://10.1.1.1
```

## SDWAN

If you installed with `poetry install` command:

- with env variables

```sh
poetry run nac-collector -s SDWAN -v DEBUG --git-provider
```

- without env variables

```sh
poetry run nac-collector -s SDWAN --username USERNAME --password PASSWORD --url URL -v DEBUG --git-provider
```

If you installed the project with pip, you can run the script directly from the command line:

```sh
nac-collector -s SDWAN -v --git-provider
```

## ISE

If you installed with `poetry install` command:

- with env variables

```sh
poetry run nac-collector -s ISE -v --git-provider
```

- without env variables

```sh
poetry run nac-collector -s ISE --username USERNAME --password PASSWORD --url URL -v DEBUG --git-provider
```

If you installed the project with pip, you can run the script directly from the command line:

```sh
nac-collector -s ISE -v DEBUG --git-provider
```

## Catalyst Center

If you installed with `poetry install` command:

- with env variables

```sh
poetry run nac-collector -s CATALYSTCENTER -v DEBUG --git-provider
```

- without env variables

```sh
poetry run nac-collector -s CATALYSTCENTER --username USERNAME --password PASSWORD --url URL -v DEBUG --git-provider
```

If you installed the project with pip, you can run the script directly from the command line:

```sh
nac-collector -s CATALYSTCENTER -v DEBUG --git-provider
```

It contains some custom logic, explained in [README_catalyst_center.md](README_catalyst_center.md)
