## Catalyst Center custom logic

### Challenges Addressed

The Cisco Catalyst Center API does not always present the relationships between different API endpoints in a straightforward manner. For example, using child relationship in API endpoint URL: "/parent/%v/children" can be confusing. Imagine it this way: you know a parent exists, but it is unclear who the children are. This custom logic resolves that issue by creating those connections, allowing you to easily understand how things are related.


### How Does It Work?

It uses "resource mappings" to link related information within Catalyst Center. Think of these mappings as instructions that tell the tool how to find related pieces of information.

### Example of a Mapping:

Let's say you want to find all the "layer2Handoffs" within a "fabricSite". Use the mapping below:

```json
{
    "/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs": {
        "source_endpoint": "/dna/intent/api/v1/sda/fabricSites?limit=500",
        "source_key": "id",
        "target_endpoint": "/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=%v",
        "target_key": "fabricId"
    }
}
```

### Explanation of the Mapping:
- **"/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs"**: This is the specific type of information we're looking for (the "layer2Handoffs").

- **source_endpoint**: This is where we start looking for information. (/dna/intent/api/v1/sda/fabricSites?limit=500) We retrieve list of all `fabricSites`:

From this endpoint, we get data like:
```json
{
    "response": [
        {
            "id": "12c25131-f133-4e96-9fd9-e619424050f0",
            "siteId": "866e0cf6-f4be-4c43-a027-2b7eea03cd7d",
            "authenticationProfileName": "name1",
            "isPubSubEnabled": true
        },
        {
            "id": "2c69fff7-a569-476e-98f0-5afa5867c80d",
            "siteId": "8fde290e-022c-4d7f-a997-0ce18acf8862",
            "authenticationProfileName": "name2",
            "isPubSubEnabled": true
        }
    ],
    "version": "string"
}
```
**source_key**: From that list, we need a specific piece of information to help us find the related "layer2Handoffs" In this case, it's the "id" of each fabric. So, from the example above, we grab these IDs: `["12c25131-f133-4e96-9fd9-e619424050f0", "2c69fff7-a569-476e-98f0-5afa5867c80d"]`

**target_endpoint**: Now that we have the "fabric IDs", we use them to find the "layer2Handoffs" associated with each fabric. This is the address where we'll find that information (`/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=%v`).

The `%v` is a placeholder where we put the fabricId. So, we would look at 

`/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=12c25131-f133-4e96-9fd9-e619424050f0`

and 

`/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs?fabricId=2c69fff7-a569-476e-98f0-5afa5867c80d`

**target_key**: This tells us what the "fabric ID" is called in the address of the "target endpoint". In this case, it's called `fabricId`.


### Where is this used?

The mappings are stored in a file called catalystcenter_lookups.json under `nac_collector/resources/` folder.

In the code [cisco_client_catalystcenter.py](./nac_collector/cisco_client_catalystcenter.py), the system checks if it has a mapping for the type of information it's looking for. If it does, it uses the mapping to find the related information and connect it together.

```python
if endpoint.get("endpoint") in self.id_lookup:
            new_endpoint = self.id_lookup[endpoint.get("endpoint")]["target_endpoint"]
```
And then if so, we use `fetch_data_alternate` to query the source_endpoint for data and attach it to our target endpoint.