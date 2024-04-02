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

## SDWAN

```sh
poetry run nac-collector -s SDWAN --username conti --password conti123 --url https://10.62.190.131:443 -v --git-provider
```


## ISE

```sh
poetry run nac-collector -s ISE --username admin --password C1sco1234567 --url https://10.48.190.181 -v --git-provider
```