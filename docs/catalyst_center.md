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


### Filtering the source list

Some target endpoints only apply to a subset of the items returned by the source endpoint (for example, managed AP locations only exist on wireless controllers). Querying the target for every source item produces `4xx`/`5xx` responses for the inapplicable ones. Two optional keys narrow the source list before the target endpoint is queried.

**source_filter**: Keep only source items whose fields match the given values. Each value may be a single value or a list of allowed values, and every listed field must match.

```yaml
source_filter:
  family: Wireless Controller
```

**source_membership_filter**: Keep only source items whose `source_field` value appears in the `membership_key` field of a second endpoint's items. Use this when the source items carry no field that identifies whether they apply, but another endpoint lists the ones that do. For example, `/dna/intent/api/v2/site` does not say which sites are fabric sites, but `/dna/intent/api/v1/sda/fabricSites` lists their `siteId`s:

```yaml
- endpoint: /dna/intent/api/v1/business/sda/authentication-profile
  source_endpoint: /dna/intent/api/v2/site
  source_membership_filter:
    source_field: id
    membership_endpoint: /dna/intent/api/v1/sda/fabricSites?limit=500
    membership_key: siteId
  source_key: groupNameHierarchy
  target_endpoint: /dna/intent/api/v1/business/sda/authentication-profile?siteNameHierarchy=%v
  target_key: siteNameHierarchy
```

If the membership endpoint cannot be fetched, the lookup is skipped rather than querying every source item.

When the membership endpoint must itself be queried once per item of another endpoint, set `membership_source_endpoint` and `membership_source_key`; `membership_endpoint` then takes a `%v` placeholder. The allowed values are collected across all of those queries.

**source_filter_any**: Keep a source item if it matches *any* of the listed conditions, each of which is a `source_filter` or a `source_membership_filter`. For example, managed AP locations exist on dedicated wireless controllers and on switches running embedded wireless, which only show up as fabric devices with the `WIRELESS_CONTROLLER_NODE` role:

```yaml
- endpoint: /dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations
  source_endpoint: /dna/intent/api/v1/network-device
  source_filter_any:
  - source_filter:
      family: Wireless Controller
  - source_membership_filter:
      source_field: id
      membership_source_endpoint: /dna/intent/api/v1/sda/fabricSites?limit=500
      membership_source_key: id
      membership_endpoint: /dna/intent/api/v1/sda/fabricDevices?fabricId=%v&deviceRoles=WIRELESS_CONTROLLER_NODE
      membership_key: networkDeviceId
  source_key: id
  target_endpoint: /dna/intent/api/v1/wirelessControllers/%v/primaryManagedApLocations
  target_key: deviceId
```

Inside `source_filter_any`, a membership condition whose endpoint cannot be fetched matches nothing, so the other conditions still apply.

### Where is this used?

The mappings are stored in `nac_collector/resources/lookups/catalystcenter.yaml`.

In [catalystcenter.py](../nac_collector/controller/catalystcenter.py), the system checks if it has a mapping for the type of information it's looking for. If it does, it uses the mapping to find the related information and connect it together.

```python
if endpoint_key and endpoint_key in self.id_lookup:
    new_endpoint = self.id_lookup[endpoint_key]["target_endpoint"]
```
And then if so, we use `fetch_data_alternate` to query the source_endpoint for data and attach it to our target endpoint.
