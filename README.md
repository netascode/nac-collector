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

Options:
  -s, --solution [SDWAN|ISE]  Solutions supported [SDWAN, ISE]  [required]
  -u, --username TEXT         Username for authentication  [required]
  -p, --password TEXT         Password for authentication  [required]
  -url, --url TEXT            Base URL for the service  [required]
  -v, --verbose               Enable verbose output
  -g, --git-provider          Generate endpoint.yaml automatically using
                              provider github repo
  --help                      Show this message and exit.
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
poetry run nac-collector -s SDWAN -v --git-provider
```

- without env variables
```sh
poetry run nac-collector -s SDWAN --username USERNAME --password PASSWORD --url URL -v --git-provider
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
poetry run nac-collector -s ISE --username USERNAME --password PASSWORD --url URL -v --git-provider
```

If you installed the project with pip, you can run the script directly from the command line:

```sh
nac-collector -s ISE -v --git-provider
```

## Tests

To run tests, firt install depedencies with test group included

```sh
poetry install --with test
```

The you can run test by simply running
```sh
poetry run pytest
```