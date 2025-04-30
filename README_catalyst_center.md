## Catalyst Center custom logic

### Challenges Addressed

Catalyst Center does not inherently provide simple child relationships in its API endpoints. The custom mappings above resolve this limitation by programmatically linking related resources.

### Custom Resource Mappings

The resource mappings are used to establish relationships between Catalyst Center endpoints. 
Example:

```json
{
    "/dna/intent/api/v1/sda/fabricDevices": {
        "source_endpoint": "/dna/intent/api/v1/sda/fabricSites?limit=500",
        "source_key": "id",
        "target_endpoint": "/dna/intent/api/v1/sda/fabricDevices?fabricId=%v",
        "target_key": "siteId"
    },
    "/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs": {
        "source_endpoint": "/dna/intent/api/v1/sda/fabricSites?limit=500",
        "source_key": "id",
        "target_endpoint": "/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=%v",
        "target_key": "fabricId"
    }
}
```

### Explanation of Resource Mappings
```json
"/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs": {
        "source_endpoint": "/dna/intent/api/v1/sda/fabricSites?limit=500",
        "source_key": "id",
        "target_endpoint": "/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=%v",
        "target_key": "fabricId"
```
"/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs" - while handling this endpoint
source_endpoint - from this endpoint

source_key - get these data (as a list, as it returns multiple records)

target_endpoint - Use this endpoint (or endpoints) instead - this has to be here, because there is no rule whether we use id in url, query param or something else.

target_key - how source_key is named in target_endpoint


### Usage in code

The file is located in `nac_collector\resources\catalystcenter_lookups.json`.

In `nac_collector\cisco_client_catalystcenter.py`, we check wheter our endpoint is in the list

```python
if endpoint.get("endpoint") in self.id_lookup:
            new_endpoint = self.id_lookup[endpoint.get("endpoint")]["target_endpoint"]
```
And then if so, we use `fetch_data_alternate` to query the source_endpoint for data and attach it to our target endpoint.