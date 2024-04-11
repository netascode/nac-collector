# INSTRUCTION

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

with env variables:
```sh
poetry run nac-collector -s SDWAN -v --git-provider
```

without env variables:
```sh
poetry run nac-collector -s SDWAN --username USERNAME --password PASSWORD --url URL -v --git-provider
```

## ISE

with env variables:
```sh
poetry run nac-collector -s ISE -v --git-provider
```

without env variables:
```sh
poetry run nac-collector -s ISE --username USERNAME --password PASSWORD --url URL -v --git-provider
```