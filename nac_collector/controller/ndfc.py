"""
Cisco NDFC API client module following the new upstream architecture.
Provides comprehensive support for Cisco Nexus Dashboard Fabric Controller APIs
with MSD fabric support using only YAML-defined endpoints.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import json

import httpx
from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger(__name__)


class CiscoClientNDFC(CiscoClientController):
    """
    NDFC Controller client for collecting data from Cisco Nexus Dashboard Fabric Controller.
    Extends the base CiscoClientController with NDFC-specific authentication and data collection methods.
    """
    
    # Interface types that use Port-Channel processing logic with vpcEntityId
    # These interface types must have:
    # 1. A 'vpcEntityId' field with format "serial1~serial2~vpcX" 
    # 2. Children endpoints defined in YAML configuration
    # 3. The same processing pattern for child endpoints like vPCInterfaceSetting
    PORT_CHANNEL_INTERFACE_TYPES = [
        "TrunkPort-Channel",
        "AccessPort-Channel"
        # Add new Port-Channel interface types here as needed
    ]
    
    # Interface types that use serial number + interface name processing logic
    # These interface types must have:
    # 1. 'serialNo' and 'ifName' fields in the interface data
    # 2. Children endpoints defined in YAML configuration that use {{serialNumber}} and {{ifName}} placeholders
    # 3. The same processing pattern for child endpoints like LoopbackInterfaceSetting
    SERIAL_INTERFACE_TYPES = [
        "LoopbackInterfaces",
        "AccessEthernetPorts",
        "TrunkEthernetPorts"
        # Add new serial-based interface types here as needed
    ]
    
    # VPC pair types that use peerOneId pattern
    VPC_PAIR_TYPES = [
        "VPC_Pairs"
        # Add new VPC pair-based types here as needed
    ]

    # Templates to exclude from policies filtering
    EXCLUDE_TEMPLATES = [
        "Default_VRF_Universal",
        "Default_Network_Universal",
        "NA",  # This template is used for networks attachments, but should not be included in the policies output
        "Default_VRF_Extension_Universal",
        "Default_Network_Extension_Universal"
    ]

    def __init__(self, **kwargs):
        """
        Initialize NDFC Controller client.
        
        Args:
            **kwargs: Arbitrary keyword arguments passed to parent CiscoClientController
        """
        # Extract NDFC-specific parameters before calling parent
        self.fabric_name = kwargs.pop('fabric_name', None)
        self.domain = kwargs.pop('domain', 'local')
        
        # Call parent constructor with standard parameters
        super().__init__(**kwargs)
        
        # Initialize NDFC-specific attributes
        self.is_msd_fabric = False
        self.msd_topology = {}
        self.discovered_switches = {}
        self.fabric_id = None  # Store fabric ID for endpoint variable replacement
        self.exclude_templates = self.EXCLUDE_TEMPLATES  # Template names to exclude from policies filtering
        
        logger.info("Initialized NDFC Controller for fabric: %s", self.fabric_name)

    def authenticate(self) -> bool:
        """
        Authenticate with NDFC using the credentials provided.
        Uses the /logon endpoint for NDFC authentication.
        This is the ONLY hardcoded endpoint - everything else comes from YAML.

        Returns:
            bool: True if authentication successful, False otherwise
        """
        if not self.username or not self.password:
            logger.error("Username and password are required for NDFC authentication")
            return False

        # Initialize HTTP client
        self.client = httpx.Client(
            verify=self.ssl_verify,
            timeout=self.timeout,
        )

        # This is the ONLY hardcoded endpoint - authentication endpoint
        auth_endpoint = "/login"
        auth_url = f"{self.base_url}{auth_endpoint}"
        auth_data = {
            "username": self.username,
            "password": self.password
        }

        logger.info("Authenticating with NDFC at %s", auth_url)

        try:
            response = self.client.post(auth_url, json=auth_data)

            if response.status_code == 200:
                response_data = response.json()
                
                # Extract token from response
                token = None
                for token_key in ["token", "access_token", "Jwt_Token", "jwttoken"]:
                    if token_key in response_data:
                        token = response_data[token_key]
                        logger.debug("Found authentication token")
                        break

                if not token:
                    logger.error("No valid token found in authentication response")
                    logger.debug("Available keys: %s", list(response_data.keys()))
                    return False

                # Update client headers with authentication token
                self.client.headers.update({
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                })

                # Extract and store AuthCookie from response headers
                set_cookie_header = response.headers.get("Set-Cookie")
                if set_cookie_header and "AuthCookie=" in set_cookie_header:
                    for cookie in set_cookie_header.split(","):
                        if "AuthCookie=" in cookie:
                            auth_cookie = cookie.split("AuthCookie=")[1].split(";")[0]
                            self.client.cookies.set("AuthCookie", auth_cookie)
                            logger.debug("Stored AuthCookie for session persistence")
                            break

                logger.info("NDFC authentication successful")
                return True

            else:
                logger.error("NDFC authentication failed with status: %s", response.status_code)
                if hasattr(response, 'text'):
                    logger.debug("Authentication error: %s", response.text)
                return False

        except Exception as e:
            logger.error("Authentication error: %s", str(e))
            return False

    def collect_data(self, endpoints_file: str) -> Dict[str, Any]:
        """
        Collect data from NDFC using endpoints defined in YAML file.
        
        Args:
            endpoints_file: Path to YAML file containing endpoint definitions
            
        Returns:
            Dict[str, Any]: Collected data organized by endpoint name
        """
        logger.info("Starting NDFC data collection using endpoints file: %s", endpoints_file)
        
        if not self.authenticate():
            logger.error("Authentication failed, cannot collect data")
            return {}

        # Load endpoints from YAML file
        endpoints_data = self.load_endpoints_from_file(endpoints_file)
        if not endpoints_data:
            logger.error("No endpoints loaded from file: %s", endpoints_file)
            return {}

        # Process endpoints using the abstract method
        return self.get_from_endpoints_data(endpoints_data)

    def get_from_endpoints_data(self, endpoints_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process endpoints data from YAML.
        
        Args:
            endpoints_data: List of endpoint configurations from YAML
            
        Returns:
            Dict[str, Any]: Collected data organized by endpoint name
        """
        # Handle the case where endpoints_data might be a dict with 'endpoints' key
        if isinstance(endpoints_data, dict) and 'endpoints' in endpoints_data:
            endpoints_list = endpoints_data['endpoints']
        elif isinstance(endpoints_data, list):
            endpoints_list = endpoints_data
        else:
            logger.error("Invalid endpoints data format: %s", type(endpoints_data))
            return {}

        if not endpoints_list:
            logger.error("No endpoints data provided")
            return {}

        logger.info("Processing %d endpoints from YAML data", len(endpoints_list))
        
        # Check if MSD fabric by looking for MSD endpoints in data
        self._detect_msd_fabric_from_endpoints(endpoints_list)
        
        result = {}
        
        # First pass: Process Fabric_Configuration to extract fabric ID
        self._extract_fabric_id_from_endpoints(endpoints_list, result)
        
        # Process each endpoint from YAML
        for endpoint in endpoints_list:
            endpoint_name = endpoint.get("name")
            if not endpoint_name:
                logger.warning("Skipping endpoint without name: %s", endpoint)
                continue
                
            # Skip Fabric_Configuration if already processed
            if endpoint_name == "Fabric_Configuration" and endpoint_name in result:
                continue
                
            result[endpoint_name] = []
            
            try:
                if self.is_msd_fabric and endpoint_name == "MSD_Fabric_Associations":
                    # Process MSD associations first
                    self._process_msd_endpoint(endpoint, result)
                elif self.is_msd_fabric and endpoint_name != "MSD_Fabric_Associations":
                    # Process endpoint for each member fabric
                    self._process_endpoint_for_msd_fabrics(endpoint, result)
                else:
                    # Process single-site endpoint
                    self._process_endpoint_single_site(endpoint, result)
                    
            except Exception as e:
                logger.error("Error processing endpoint %s: %s", endpoint_name, str(e))
                result[endpoint_name].append({
                    "data": {},
                    "endpoint": endpoint.get("endpoint", ""),
                    "error": str(e)
                })
        
        logger.info("Completed NDFC data collection")
        return result

    def _detect_msd_fabric_from_endpoints(self, endpoints_data: List[Dict[str, Any]]):
        """
        Detect MSD fabric by building MSD tree structure.
        
        Logic:
        - Root of MSD tree has "fabricState": "msd"
        - Members have "fabricState": "member" and "fabricParent" != "None"
        - If NDFC_FABRIC_NAME points to the MSD root, process endpoints for MSD (root + all members)
        - If NDFC_FABRIC_NAME points to a non-root fabric, treat it as a standalone fabric
        
        Args:
            endpoints_data: List of endpoint configurations from YAML
        """
        # Look for MSD endpoint in YAML
        msd_endpoint_config = None
        for endpoint in endpoints_data:
            if endpoint.get("name") == "MSD_Fabric_Associations":
                msd_endpoint_config = endpoint
                break
        
        if not msd_endpoint_config:
            logger.info("No MSD endpoint in YAML - single-site fabric")
            self.is_msd_fabric = False
            return
        
        try:
            # Use the endpoint from YAML
            endpoint_url = msd_endpoint_config["endpoint"]
            logger.info("Checking MSD fabric associations using YAML endpoint")
            
            msd_data = self.fetch_data(endpoint_url)
            if not msd_data:
                logger.info("No MSD associations found - single-site fabric")
                self.is_msd_fabric = False
                return
            
            # Build MSD tree structure
            msd_root = None
            member_fabrics = []
            
            if isinstance(msd_data, list):
                for association in msd_data:
                    if isinstance(association, dict):
                        fabric_state = association.get("fabricState")
                        fabric_name = association.get("fabricName")
                        fabric_parent = association.get("fabricParent")
                        
                        if fabric_state == "msd":
                            # Found MSD root
                            msd_root = fabric_name
                            logger.debug("Found MSD root: %s", msd_root)
                        elif fabric_state == "member" and fabric_parent and fabric_parent != "None":
                            # Found MSD member with valid parent
                            if fabric_name:
                                member_fabrics.append(fabric_name)
                                logger.debug("Found MSD member: %s with parent: %s", fabric_name, fabric_parent)
            
            # Determine if provided fabric-name is MSD root
            if msd_root and self.fabric_name == msd_root:
                # Fabric is MSD root - process MSD topology
                self.is_msd_fabric = True
                all_fabrics = [msd_root] + member_fabrics
                self.msd_topology = {
                    "msd_root": msd_root,
                    "member_fabrics": member_fabrics,
                    "all_fabrics": all_fabrics,
                    "primary_fabric": self.fabric_name
                }
                logger.info("Fabric %s is MSD root with members: %s", self.fabric_name, member_fabrics)
            else:
                # Fabric is not MSD root - treat as standalone
                self.is_msd_fabric = False
                logger.info("Fabric %s is not MSD root - treating as standalone fabric", self.fabric_name)
                if msd_root:
                    logger.debug("MSD root in environment is: %s", msd_root)
                
        except Exception as e:
            logger.warning("Error during MSD detection: %s", str(e))
            self.is_msd_fabric = False

    def _extract_fabric_id_from_endpoints(self, endpoints_data: List[Dict[str, Any]], result: Dict[str, Any]):
        """
        Extract fabric ID from Fabric_Configuration endpoint to use for variable replacement.
        
        Args:
            endpoints_data: List of endpoint configurations from YAML
            result: Result dictionary to store the fabric configuration data
        """
        # Look for Fabric_Configuration endpoint in YAML
        fabric_config_endpoint = None
        for endpoint in endpoints_data:
            if endpoint.get("name") == "Fabric_Configuration":
                fabric_config_endpoint = endpoint
                break
        
        if not fabric_config_endpoint:
            logger.info("No Fabric_Configuration endpoint found - fabric ID will not be available")
            return
        
        try:
            # Process Fabric_Configuration endpoint first
            endpoint_name = fabric_config_endpoint["name"]
            result[endpoint_name] = []
            
            if self.is_msd_fabric:
                # For MSD fabrics, process for all fabrics to find the correct ID
                self._process_endpoint_for_msd_fabrics(fabric_config_endpoint, result)
                
                # Extract fabric ID from the results for the current fabric
                for fabric_data in result[endpoint_name]:
                    if fabric_data.get("fabric") == self.fabric_name:
                        data = fabric_data.get("data", {})
                        if isinstance(data, dict) and "id" in data:
                            self.fabric_id = data["id"]
                            logger.info("Extracted fabric ID %s for MSD fabric %s", self.fabric_id, self.fabric_name)
                            break
                        elif isinstance(data, list) and len(data) > 0 and "id" in data[0]:
                            self.fabric_id = data[0]["id"]
                            logger.info("Extracted fabric ID %s for MSD fabric %s", self.fabric_id, self.fabric_name)
                            break
            else:
                # For standalone fabrics, process normally
                self._process_endpoint_single_site(fabric_config_endpoint, result)
                
                # Extract fabric ID from the result
                if result[endpoint_name]:
                    data = result[endpoint_name][0].get("data", {})
                    if isinstance(data, dict) and "id" in data:
                        self.fabric_id = data["id"]
                        logger.info("Extracted fabric ID %s for fabric %s", self.fabric_id, self.fabric_name)
                    elif isinstance(data, list) and len(data) > 0 and "id" in data[0]:
                        self.fabric_id = data[0]["id"]
                        logger.info("Extracted fabric ID %s for fabric %s", self.fabric_id, self.fabric_name)
                        
        except Exception as e:
            logger.warning("Error extracting fabric ID: %s", str(e))
            self.fabric_id = None

    def _process_msd_endpoint(self, endpoint: Dict[str, Any], result: Dict[str, Any]):
        """
        Process MSD-specific endpoint using YAML configuration.
        
        Args:
            endpoint: Endpoint configuration from YAML
            result: Result dictionary to append data to
        """
        endpoint_name = endpoint["name"]
        endpoint_url = endpoint["endpoint"]
        
        # Replace %v placeholder with fabric name if present
        if self.fabric_name and "%v" in endpoint_url:
            endpoint_url = endpoint_url.replace("%v", self.fabric_name)
            
        # Replace {{fabricID}} placeholder with fabric ID if present
        if self.fabric_id and "{{fabricID}}" in endpoint_url:
            endpoint_url = endpoint_url.replace("{{fabricID}}", str(self.fabric_id))
            logger.debug("Replaced {{fabricID}} with %s in MSD endpoint URL", self.fabric_id)
        
        logger.debug("Processing MSD endpoint: %s -> %s", endpoint_name, endpoint_url)
        
        try:
            data = self.fetch_data(endpoint_url)
            
            # Fix escaped JSON strings in template config fields
            if data is not None:
                self._fix_escaped_json_in_data(data)
                
            result[endpoint_name].append({
                "data": data if data is not None else {},
                "endpoint": endpoint_url,
            })
            logger.debug("Successfully processed MSD endpoint: %s", endpoint_name)
            
        except Exception as e:
            logger.error("Error fetching MSD data from %s: %s", endpoint_url, str(e))
            result[endpoint_name].append({
                "data": {},
                "endpoint": endpoint_url,
                "error": str(e)
            })

    def _process_endpoint_for_msd_fabrics(self, endpoint: Dict[str, Any], result: Dict[str, Any]):
        """
        Process endpoint for each fabric in MSD deployment (root + all members).
        
        Args:
            endpoint: Endpoint configuration from YAML
            result: Result dictionary to append data to
        """
        endpoint_name = endpoint["name"]
        original_fabric = self.fabric_name
        original_fabric_id = self.fabric_id
        
        # Process endpoint for all fabrics in MSD topology (root + members)
        for fabric_name in self.msd_topology.get("all_fabrics", []):
            logger.info("Processing endpoint %s for MSD fabric: %s", endpoint_name, fabric_name)
            
            # Skip Discovered_Switches for MSD root fabric (fabricType: "MSD")
            if endpoint_name == "Discovered_Switches" and self._is_msd_root_fabric(fabric_name):
                logger.info("Skipping Discovered_Switches for MSD root fabric: %s", fabric_name)
                continue
            
            # Skip Policies, VRF_Configuration, and Network_Configuration for child fabrics
            # (collect these only from MSD root fabric)
            if endpoint_name in ["Policies", "VRF_Configuration", "Network_Configuration"] and not self._is_msd_root_fabric(fabric_name):
                logger.info("Skipping %s for MSD child fabric: %s (collect only from MSD root)", endpoint_name, fabric_name)
                continue
            
            # Temporarily switch fabric context
            self.fabric_name = fabric_name
            
            # Update fabric ID for current fabric context
            self._update_fabric_id_for_current_fabric(result)
            
            try:
                self._process_endpoint_single_site(endpoint, result)
            except Exception as e:
                logger.error("Error processing endpoint %s for fabric %s: %s", endpoint_name, fabric_name, str(e))
                result[endpoint_name].append({
                    "data": {},
                    "endpoint": endpoint.get("endpoint", ""),
                    "fabric": fabric_name,
                    "error": str(e)
                })
            finally:
                # Restore original fabric context
                self.fabric_name = original_fabric
                self.fabric_id = original_fabric_id

    def _process_endpoint_single_site(self, endpoint: Dict[str, Any], result: Dict[str, Any]):
        """
        Process endpoint for single-site fabric using YAML configuration.
        
        Args:
            endpoint: Endpoint configuration from YAML
            result: Result dictionary to append data to
        """
        endpoint_name = endpoint["name"]
        endpoint_url = endpoint["endpoint"]
        
        # Special handling for Policies endpoint with filtering
        if endpoint_name == "Policies":
            self._process_policies_endpoint_with_filtering(endpoint, result)
            return
        
        # Replace %v placeholder with fabric name if present
        if self.fabric_name and "%v" in endpoint_url:
            endpoint_url = endpoint_url.replace("%v", self.fabric_name)
            
        # Replace {{fabricID}} placeholder with fabric ID if present
        if self.fabric_id and "{{fabricID}}" in endpoint_url:
            endpoint_url = endpoint_url.replace("{{fabricID}}", str(self.fabric_id))
            logger.debug("Replaced {{fabricID}} with %s in endpoint URL for fabric %s", self.fabric_id, self.fabric_name)
        
        logger.debug("Processing endpoint: %s -> %s", endpoint_name, endpoint_url)
        
        try:
            data = self.fetch_data(endpoint_url)
            
            # Fix escaped JSON strings in template config fields
            if data is not None:
                self._fix_escaped_json_in_data(data)
            
            # Add fabric context for MSD scenarios
            result_entry = {
                "data": data if data is not None else {},
                "endpoint": endpoint_url,
                "fabric": self.fabric_name
            }
            
            if self.is_msd_fabric:
                result_entry["fabric"] = self.fabric_name
            
            result[endpoint_name].append(result_entry)
            logger.debug("Successfully processed endpoint: %s", endpoint_name)
            
            # Process children endpoints if they exist
            if "children" in endpoint and isinstance(endpoint["children"], list):
                logger.debug("Processing children endpoints for: %s", endpoint_name)
                self._process_children_endpoints(endpoint, result)
            
            
            
        except Exception as e:
            logger.error("Error fetching data from %s: %s", endpoint_url, str(e))
            result_entry = {
                "data": {},
                "endpoint": endpoint.get("endpoint", ""),
                "fabric": self.fabric_name,
                "error": str(e)
            }
            
            if self.is_msd_fabric:
                result_entry["fabric"] = self.fabric_name
                
            result[endpoint_name].append(result_entry)

    def _is_msd_root_fabric(self, fabric_name: str) -> bool:
        """
        Check if the given fabric name is an MSD root fabric (fabricType: "MSD").
        
        Args:
            fabric_name: Name of the fabric to check
            
        Returns:
            bool: True if fabric is MSD root, False otherwise
        """
        # Look for the fabric in MSD topology
        msd_root = self.msd_topology.get("msd_root")
        return fabric_name == msd_root

    def _update_fabric_id_for_current_fabric(self, result: Dict[str, Any]):
        """
        Update fabric ID for the current fabric context by looking up Fabric_Configuration data.
        
        Args:
            result: Result dictionary containing Fabric_Configuration data
        """
        if "Fabric_Configuration" not in result:
            logger.warning("No Fabric_Configuration data available to extract fabric ID for %s", self.fabric_name)
            return
            
        # Look for fabric ID in the existing Fabric_Configuration results
        for fabric_data in result["Fabric_Configuration"]:
            fabric_from_data = fabric_data.get("fabric")
            if fabric_from_data == self.fabric_name:
                data = fabric_data.get("data", {})
                if isinstance(data, dict) and "id" in data:
                    self.fabric_id = data["id"]
                    logger.debug("Updated fabric ID to %s for fabric %s", self.fabric_id, self.fabric_name)
                    return
                elif isinstance(data, list) and len(data) > 0 and "id" in data[0]:
                    self.fabric_id = data[0]["id"]
                    logger.debug("Updated fabric ID to %s for fabric %s", self.fabric_id, self.fabric_name)
                    return
        
        logger.warning("Could not find fabric ID for fabric %s in Fabric_Configuration data", self.fabric_name)

    def _extract_serial_numbers_from_switches(self, discovered_switches_data):
        """
        Extract serial numbers from Discovered_Switches endpoint data.
        
        Parameters:
            discovered_switches_data (list): List of discovered switches data entries
            
        Returns:
            list: List of serial numbers found in the switches data
        """
        serial_numbers = []
        
        for switch_entry in discovered_switches_data:
            data = switch_entry.get("data", {})
            
            # Handle different data structures
            switches_list = []
            if isinstance(data, list):
                switches_list = data
            elif isinstance(data, dict):
                # Check for common wrapper keys
                for key in ["switches", "data", "response", "inventory"]:
                    if key in data and isinstance(data[key], list):
                        switches_list = data[key]
                        break
                else:
                    # If no wrapper found, treat the dict as a single switch
                    switches_list = [data]
            
            # Extract serial numbers from switches
            for switch in switches_list:
                if isinstance(switch, dict):
                    # Try different possible field names for serial numbers
                    for serial_field in ["serialNumber", "serial_number", "serial", "deviceSerialNumber"]:
                        if serial_field in switch and switch[serial_field]:
                            serial_numbers.append(str(switch[serial_field]))
                            break
        
        logger.debug("Extracted %d serial numbers from discovered switches", len(serial_numbers))
        return serial_numbers

    def _process_policies_endpoint_with_filtering(self, endpoint, endpoint_dict):
        """
        Process Policies endpoint by fetching all policies and filtering by discovered switch serial numbers, autogenerated policies, policies based on specific templates.

        Parameters:
            endpoint (dict): The endpoint configuration containing name and endpoint URL.
            endpoint_dict (dict): The dictionary to store results in.
        """
        endpoint_name = endpoint["name"]
        endpoint_url = endpoint["endpoint"]
        
        # Replace %v placeholder with fabric name if present
        if self.fabric_name and "%v" in endpoint_url:
            endpoint_url = endpoint_url.replace("%v", self.fabric_name)
            
        # Replace {{fabricID}} placeholder with fabric ID if present
        if self.fabric_id and "{{fabricID}}" in endpoint_url:
            endpoint_url = endpoint_url.replace("{{fabricID}}", str(self.fabric_id))
            logger.debug("Replaced {{fabricID}} with %s in Policies endpoint URL", self.fabric_id)

        # Initialize list for this endpoint if not exists
        if endpoint_name not in endpoint_dict:
            endpoint_dict[endpoint_name] = []

        logger.info(
            "Processing Policies endpoint with client-side filtering by serial numbers"
        )

        # Ensure Discovered_Switches data exists for serial correlation
        if "Discovered_Switches" not in endpoint_dict:
            logger.error(
                "Cannot process Policies endpoint: Discovered_Switches data not available"
            )
            logger.error(
                "Make sure Discovered_Switches endpoint is defined before Policies endpoint"
            )
            endpoint_dict[endpoint_name].append(
                {
                    "data": {},
                    "endpoint": endpoint_url,
                    "fabric": self.fabric_name,
                    "error": "Discovered_Switches data not available",
                }
            )
            return

        try:
            logger.debug("Fetching all policies from endpoint: %s", endpoint_url)

            # Make the API request using the parent class fetch_data method
            all_policies_data = self.fetch_data(endpoint_url)

            if all_policies_data is not None:
                logger.info("Successfully retrieved all policies data")

                # Fix escaped JSON strings in template config fields
                self._fix_escaped_json_in_data(all_policies_data)

                # For reporting/metadata only: gather serials from Discovered_Switches
                serial_numbers = self._extract_serial_numbers_from_switches(
                    endpoint_dict["Discovered_Switches"]
                )

                if not serial_numbers:
                    logger.warning("No serial numbers found in Discovered_Switches data")
                    endpoint_dict[endpoint_name].append(
                        {
                            "data": {},
                            "endpoint": endpoint_url,
                            "fabric": self.fabric_name,
                            "error": "No serial numbers found in Discovered_Switches",
                        }
                    )
                    return

                logger.info(
                    "Found %d switches with serial numbers, filtering policies",
                    len(serial_numbers),
                )

                # Filter policies based on discovered switch serial numbers (extracted internally)
                filtered_policies = self._filter_by_discovered_Serial_numbers(
                    all_policies_data, endpoint_dict
                )

                # Filter out autogenerated policies
                filtered_policies = self._filter_autogenerated_policies(filtered_policies)

                #Filter out policies that are based on templates: 'Default_VRF_Universal' or 'Default_Network_Universal' 
                logger.debug("Applying template filtering with exclude_templates: %s", self.exclude_templates)
                filtered_policies = self._filter_specyfic_template_policies(
                    filtered_policies, self.exclude_templates
                ) 

                # Store the filtered results
                endpoint_dict[endpoint_name].append(
                    {
                        "data": filtered_policies,
                        "fabric": self.fabric_name,
                        "endpoint": endpoint_url,
                        "filtered_serial_numbers": serial_numbers,
                        "total_policies_received": len(all_policies_data)
                        if isinstance(all_policies_data, list)
                        else 1,
                        "filtered_policies_count": len(filtered_policies)
                        if isinstance(filtered_policies, list)
                        else 1,
                    }
                )

                logger.info(
                    "Policy filtering completed: %d policies filtered from %d total policies for %d switches",
                    len(filtered_policies)
                    if isinstance(filtered_policies, list)
                    else 1,
                    len(all_policies_data)
                    if isinstance(all_policies_data, list)
                    else 1,
                    len(serial_numbers),
                )

            else:
                logger.error("Failed to fetch policies data")
                endpoint_dict[endpoint_name].append(
                    {
                        "data": {},
                        "endpoint": endpoint_url,
                        "fabric": self.fabric_name,
                        "error": "Failed to fetch policies data",
                    }
                )

        except Exception as e:
            logger.error("Unexpected error fetching policies data: %s", str(e))
            endpoint_dict[endpoint_name].append(
                {"data": {}, "endpoint": endpoint_url, "fabric": self.fabric_name, "error": str(e)}
            )

    def _filter_by_discovered_Serial_numbers(
        self,
        data,
        endpoint_dict,
        serial_fields=None,
        match_any=True,
    ):
        """
        Filter items to include only those that reference serial numbers discovered in
        the previously fetched Discovered_Switches endpoint.

        This is generalized for any endpoint payload (Policies, VPC pairs, etc.).

        Parameters:
            data (dict or list): Raw data returned from an API endpoint (can be a list
                of items or a dict possibly wrapped in common keys like 'data'/'response').
            endpoint_dict (dict): The aggregate endpoints dictionary containing
                'Discovered_Switches' entries used to extract serial numbers.
            serial_fields (str | list[str] | None): Optional field paths to check for
                serial numbers within each item. Supports dot-separated nested paths.
                When None, a recursive heuristic search looks for keys containing
                'serial'.
            match_any (bool): If True, include an item when any field path contains a
                serial matching the discovered serials; if False, require all provided
                field paths to match.

        Returns:
            list: Filtered list of items that reference the discovered serial numbers.
        """
        # Guard: ensure Discovered_Switches exist
        if "Discovered_Switches" not in endpoint_dict:
            logger.error(
                "Discovered_Switches data not available in endpoint_dict; skipping serial filtering"
            )
            return []

        discovered_serials = self._extract_serial_numbers_from_switches(
            endpoint_dict["Discovered_Switches"]
        )
        serial_set = set(sn for sn in discovered_serials if sn)
        logger.debug(
            "Filtering endpoint items by discovered serial numbers (count=%d), fields=%s",
            len(serial_set),
            serial_fields if serial_fields is not None else "<auto>",
        )
        if not serial_set:
            logger.warning("No discovered serial numbers found; returning empty result")
            return []

        # Normalize incoming payload into a list of items
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                items = data["data"]
            elif "response" in data and isinstance(data["response"], list):
                items = data["response"]
            else:
                # Single object; treat as one item
                items = [data]
        else:
            logger.warning("Unexpected endpoint data format: %s", type(data))
            return []

        def _iter_values_by_path(obj, path):
            """Yield values from obj following a dot-separated path. Supports list traversal."""
            if obj is None:
                return
            if not path:
                yield obj
                return
            head, *tail = path.split(".")
            tail_path = ".".join(tail) if tail else ""
            if isinstance(obj, dict):
                if head in obj:
                    yield from _iter_values_by_path(obj[head], tail_path)
            elif isinstance(obj, list):
                # Head could be an index or a wildcard-like segment; try to cast to int
                idx = None
                try:
                    idx = int(head)
                except Exception:
                    idx = None
                if idx is not None:
                    if 0 <= idx < len(obj):
                        yield from _iter_values_by_path(obj[idx], tail_path)
                else:
                    # Iterate all and keep walking
                    for el in obj:
                        yield from _iter_values_by_path(el, tail_path or head)

        def _recursive_serial_candidates(obj):
            """Recursively find candidate serial values by key heuristics (auto mode)."""
            if obj is None:
                return []
            candidates = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key_lower = str(k).lower()
                    if "serial" in key_lower:  # matches 'serial', 'serialnumber', etc.
                        if isinstance(v, (str, int)):
                            candidates.append(str(v))
                        elif isinstance(v, list):
                            for el in v:
                                if isinstance(el, (str, int)):
                                    candidates.append(str(el))
                                else:
                                    candidates.extend(_recursive_serial_candidates(el))
                        elif isinstance(v, dict):
                            candidates.extend(_recursive_serial_candidates(v))
                    else:
                        candidates.extend(_recursive_serial_candidates(v))
            elif isinstance(obj, list):
                for el in obj:
                    candidates.extend(_recursive_serial_candidates(el))
            return candidates

        # Normalize serial_fields to a list of paths or None
        if isinstance(serial_fields, str):
            fields_to_check = [serial_fields]
        elif isinstance(serial_fields, list) and all(isinstance(f, str) for f in serial_fields):
            fields_to_check = serial_fields
        else:
            fields_to_check = None  # auto/heuristic mode

        filtered_items = []

        logger.debug("Processing %d items for serial filtering", len(items))

        for item in items:
            if not isinstance(item, dict):
                logger.debug("Skipping non-dict item: %s", item)
                continue

            matched = False

            if fields_to_check:
                # Gather discovered serials per field
                discovered_by_field = []
                for path in fields_to_check:
                    values = [
                        str(v)
                        for v in _iter_values_by_path(item, path)
                        if isinstance(v, (str, int))
                    ]
                    discovered_by_field.append(set(values))

                if match_any:
                    # Any field containing a matching serial passes
                    matched = any(bool(s & serial_set) for s in discovered_by_field)
                else:
                    # All fields must contain at least one matching serial
                    matched = all(bool(s & serial_set) for s in discovered_by_field)
            else:
                # Auto/heuristic mode: recursively scan keys containing 'serial'
                candidates = set(_recursive_serial_candidates(item))
                matched = bool(candidates & serial_set)

            if matched:
                filtered_items.append(item)

        logger.info(
            "Serial filtering results: %d items matched out of %d total items",
            len(filtered_items),
            len(items),
        )

        return filtered_items

    def _filter_autogenerated_policies(self, policies_data):
        """
        Filter policies data to only include policies with "autoGenerated" set to false.

        Parameters:
            policies_data (dict or list): The raw policies data from NDFC API.

        Returns:
            list: Filtered list of policies 
        """


        # Handle different response structures
        if isinstance(policies_data, dict):
            # Check for common NDFC response patterns
            if "data" in policies_data and isinstance(policies_data["data"], list):
                policies_list = policies_data["data"]
            elif isinstance(policies_data, dict):
                # Single policy object - convert to list for consistent processing
                policies_list = [policies_data]
            else:
                policies_list = []
        elif isinstance(policies_data, list):
            policies_list = policies_data
        else:
            logger.warning("Unexpected policies data format: %s", type(policies_data))
            return []

        filtered_policies = []

        logger.debug("Processing %d policies for filtering", len(policies_list))

        for policy in policies_list:
            if isinstance(policy, dict) and "autoGenerated" in policy:
                if isinstance(policy["autoGenerated"], bool):
                    # Only include policies where autoGenerated is False
                    if not policy["autoGenerated"]:
                        filtered_policies.append(policy)
                        logger.debug(
                            "Including non-autogenerated policy %s",
                            policy.get("policyId", "unknown"),
                        )
                    else:
                        logger.debug(
                            "Excluding autogenerated policy %s",
                            policy.get("policyId", "unknown"),
                        )
            else:
                logger.debug("Policy missing autoGenerated field: %s", policy)

        logger.info(
            "Policy filtering results: %d policies matched out of %d total policies",
            len(filtered_policies),
            len(policies_list),
        )

        return filtered_policies

    def _filter_specyfic_template_policies(self, policies_data, template_names):
        """
        Filter out policies data which are based on specific templates.

        Parameters:
            policies_data (dict or list): The raw policies data from NDFC API.
            template_names (list): List of template names to filter out.

        Returns:
            list: Filtered list of policies 
        """


        # Handle different response structures
        if isinstance(policies_data, dict):
            # Check for common NDFC response patterns
            if "data" in policies_data and isinstance(policies_data["data"], list):
                policies_list = policies_data["data"]
            elif isinstance(policies_data, dict):
                # Single policy object - convert to list for consistent processing
                policies_list = [policies_data]
            else:
                policies_list = []
        elif isinstance(policies_data, list):
            policies_list = policies_data
        else:
            logger.warning("Unexpected policies data format: %s", type(policies_data))
            return []

        filtered_policies = []
        template_names_set = set(template_names)  # Convert to set for faster lookup
        
        logger.debug("Template filtering: excluding templates %s from %d policies", template_names, len(policies_list))

        logger.debug("Processing %d policies for filtering", len(policies_list))

        for policy in policies_list:
            if isinstance(policy, dict) and "templateName" in policy:
                if isinstance(policy["templateName"], str):
                    # Only include policies where autoGenerated is False
                    if policy["templateName"] not in template_names_set:
                        filtered_policies.append(policy)
                        logger.debug(
                            "Including policy %s",
                            policy.get("policyId", "unknown"),
                        )
                    else:
                        logger.debug(
                            "Excluding templated policy %s",
                            policy.get("policyId", "unknown"),
                        )
            else:
                logger.debug("Policy missing templateName field: %s", policy)

        logger.info(
            "Policy filtering results: %d policies matched out of %d total policies",
            len(filtered_policies),
            len(policies_list),
        )

        return filtered_policies

    def _fix_escaped_json_in_data(self, data):
        """
        Recursively traverse the data structure and fix escaped JSON strings
        in vrfTemplateConfig and networkTemplateConfig fields.
        
        Args:
            data: The data structure to process (dict, list, or other)
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['vrfTemplateConfig', 'networkTemplateConfig'] and isinstance(value, str):
                    try:
                        # Parse the escaped JSON string into a proper object
                        parsed_json = json.loads(value)
                        data[key] = parsed_json
                        logger.debug("Fixed escaped JSON in %s field", key)
                        self._fix_escaped_json_in_data(parsed_json)
                    except json.JSONDecodeError as e:
                        logger.warning("Could not parse %s field as JSON: %s", key, str(e))
                elif key == 'dhcpServers' and isinstance(value, str):
                    stripped_value = value.strip()
                    if stripped_value and stripped_value[0] in '{[':
                        try:
                            # Decode escaped DHCP servers payloads within network template config
                            parsed_json = json.loads(stripped_value)
                            data[key] = parsed_json
                            logger.debug("Fixed escaped JSON in dhcpServers field")
                            self._fix_escaped_json_in_data(parsed_json)
                        except json.JSONDecodeError as e:
                            logger.warning("Could not parse dhcpServers field as JSON: %s", str(e))
                else:
                    # Recursively process nested structures
                    self._fix_escaped_json_in_data(value)
        elif isinstance(data, list):
            for item in data:
                self._fix_escaped_json_in_data(item)
    
    def _process_children_endpoints(self, parent_endpoint, endpoint_dict):
        """
        Process children endpoints for a given parent endpoint.
        Specifically handles Network_Configuration -> Network_Attachments logic.

        Parameters:
            parent_endpoint (dict): The parent endpoint configuration.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        logger.debug("Processing children endpoints for parent: %s", parent_name)

        # Special handling for child endpoints based on parent type
        if parent_name == "Network_Configuration":
            self._process_network_attachments(parent_endpoint, endpoint_dict)
        elif parent_name == "VRF_Configuration":
            self._process_vrf_attachments(parent_endpoint, endpoint_dict)
       
        elif parent_name == "Discovered_Switches":
            self._process_switch_interfaces(parent_endpoint, endpoint_dict)
        elif parent_name in self.PORT_CHANNEL_INTERFACE_TYPES:
            # Handle Port-Channel interfaces that use vpcEntityId pattern
            self._process_port_channel_children(parent_endpoint, endpoint_dict)
        elif parent_name in self.VPC_PAIR_TYPES:
            # Handle VPC pair endpoints that use peerOneId pattern
            self._process_vpc_pairs_children(parent_endpoint, endpoint_dict)
        
        else:
            # Generic children processing for other endpoints (if needed in the future)
            logger.warning("Generic children processing not yet implemented for: %s", parent_name)

    def _process_attachment_data(self, attachment_data):
        """
        Process the raw attachment data from the API response.
        
        Parameters:
            attachment_data (dict or list): Raw attachment data from NDFC API.
            
        Returns:
            list: Processed list of network attachments.
        """
        logger.debug("Processing attachment data {{%s}}", attachment_data)
        # Handle different response structures
        if isinstance(attachment_data, list):
            # Check if list contains objects with lanAttachList
            processed_data = []
            for item in attachment_data:
                if isinstance(item, dict) and "lanAttachList" in item:
                    # Extract the lanAttachList from each item
                    lan_attach_list = item["lanAttachList"]
                    if isinstance(lan_attach_list, list):
                        processed_data.extend(lan_attach_list)
                    elif lan_attach_list:
                        processed_data.append(lan_attach_list)
                else:
                    # Direct attachment item
                    processed_data.append(item)
            return processed_data
        elif isinstance(attachment_data, dict):
            # Check for common NDFC response patterns
            if "data" in attachment_data:
                data = attachment_data["data"]
                return data if isinstance(data, list) else [data] if data else []
            elif "response" in attachment_data:
                data = attachment_data["response"]
                return data if isinstance(data, list) else [data] if data else []
            elif "lanAttachList" in attachment_data:
                data = attachment_data["lanAttachList"]
                return data if isinstance(data, list) else [data] if data else []
            else:
                # Direct object response - wrap in list
                return [attachment_data]
        else:
            logger.warning("Unexpected attachment data type: %s", type(attachment_data))
            return []
    
    def _process_switch_interfaces(self, parent_endpoint, endpoint_dict):
        """
        Process interface children endpoints for Discovered_Switches.
        Fetches interface data for each discovered switch and adds it to the switch data.

        Parameters:
            parent_endpoint (dict): The parent Discovered_Switches endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configurations
        children_endpoints = parent_endpoint.get("children", [])
        
        if not children_endpoints:
            logger.debug("No children endpoints found for %s", parent_name)
            return

        logger.info("Processing %d children endpoints for %s", len(children_endpoints), parent_name)
        
        # Debug: Check how many Discovered_Switches entries we have
        total_entries = len(endpoint_dict[parent_name])
        logger.debug("Found %d Discovered_Switches entries to process", total_entries)

        # Process each Discovered_Switches entry
        for config_index, config_entry in enumerate(endpoint_dict[parent_name]):
            if not config_entry.get("data"):
                continue
            
            # In MSD scenarios, only process the entry that matches the current fabric context
            # to avoid processing the same switches multiple times from accumulated entries
            entry_fabric = config_entry.get("fabric")
            if self.is_msd_fabric and entry_fabric and entry_fabric != self.fabric_name:
                logger.debug("Skipping Discovered_Switches entry for fabric %s (currently processing %s)", 
                           entry_fabric, self.fabric_name)
                continue
            
            logger.debug("Processing Discovered_Switches entry %d for fabric %s", config_index, entry_fabric)
            
            # Handle both list and single object data structures
            switches_data = config_entry["data"]
            if not isinstance(switches_data, list):
                switches_data = [switches_data] if switches_data else []
            
            # Process each switch in the data
            for switch_index, switch in enumerate(switches_data):
                # Skip switches without valid data (like the empty objects in the JSON)
                if not switch or not isinstance(switch, dict) or not switch.get("hostName"):
                    continue
                
                host_name = switch.get("hostName")
                serial_number = switch.get("serialNumber")
                switch_fabric_name = switch.get("fabricName")
                
                # Skip switches that don't belong to the current fabric being processed
                # This prevents duplicate processing in MSD deployments where switches 
                # from other fabrics might be returned in the Discovered_Switches response
                current_fabric = config_entry.get("fabric")
                logger.debug("Switch fabric check: switch %s belongs to fabric %s, currently processing fabric %s", 
                           host_name, switch_fabric_name, current_fabric)
                if switch_fabric_name and current_fabric and switch_fabric_name != current_fabric:
                    logger.debug("Skipping switch %s (belongs to fabric %s, currently processing fabric %s)", 
                               host_name, switch_fabric_name, current_fabric)
                    continue
                
                logger.debug("Processing interfaces for switch: %s (serial: %s)", host_name, serial_number)
                
                # Initialize interfaces container if not present or if it's null
                if "interfaces" not in switch or switch["interfaces"] is None:
                    switch["interfaces"] = {}
                
                # Process each child endpoint for this switch
                for child_endpoint in children_endpoints:
                    child_name = child_endpoint["name"]
                    child_url = child_endpoint["endpoint"]
                    
                    logger.debug("Processing child endpoint %s for switch %s", child_name, host_name)
                    
                    # Get the switch's actual fabric information 
                    switch_fabric_name = switch.get("fabricName")
                    switch_fabric_id = switch.get("fid")
                    
                    # Replace placeholders in the URL using switch's actual fabric info
                    if switch_fabric_name and "%v" in child_url:
                        child_url = child_url.replace("%v", switch_fabric_name)
                    
                    if switch_fabric_id and "{{fabricID}}" in child_url:
                        child_url = child_url.replace("{{fabricID}}", str(switch_fabric_id))
                        logger.debug("Using switch's fabric ID %s for %s in fabric %s", switch_fabric_id, host_name, switch_fabric_name)
                    
                    if host_name and "{{hostName}}" in child_url:
                        child_url = child_url.replace("{{hostName}}", host_name)
                    
                    if serial_number and "{{serialNumber}}" in child_url:
                        child_url = child_url.replace("{{serialNumber}}", serial_number)
                    
                    logger.debug("Fetching %s interfaces from: %s", child_name, child_url)
                    
                    try:
                        # Fetch the interface data
                        interface_data = self.fetch_data(child_url)
                        
                        if interface_data is not None:
                            logger.debug("Successfully retrieved %s for switch: %s", child_name, host_name)
                            
                            # Process the interface data (normalize structure)
                            processed_interfaces = self._process_interface_data(interface_data)
                            
                            # Add the interface data to the switch under the child endpoint name
                            if processed_interfaces: 
                                switch["interfaces"][child_name] = processed_interfaces
                                
                                # Check if this child endpoint has its own children (nested children)
                                if "children" in child_endpoint and isinstance(child_endpoint["children"], list):
                                    logger.debug("Processing nested children for %s on switch %s", child_name, host_name)
                                    self._process_nested_children_for_interfaces(child_endpoint, processed_interfaces, host_name)
                            
                            logger.debug("Processed child name: %s", child_name)
                            
                            logger.info("Added %d %s interfaces for switch: %s", 
                                      len(processed_interfaces) if isinstance(processed_interfaces, list) else 1, 
                                      child_name, host_name)
                        else:
                            logger.warning("Failed to fetch %s for switch: %s", child_name, host_name)
                            switch["interfaces"][child_name] = []
                    
                    except Exception as e:
                        logger.error("Error fetching %s for switch %s: %s", child_name, host_name, str(e))
                        switch["interfaces"][child_name] = []

    def _process_interface_data(self, interface_data):
        """
        Process the raw interface data from the API response.
        
        Parameters:
            interface_data (dict or list): Raw interface data from NDFC API.
            
        Returns:
            list: Processed list of interfaces.
        """
        logger.debug("Processing interface data: %s", type(interface_data))
        
        # Handle different response structures
        if isinstance(interface_data, list):
            return interface_data
        elif isinstance(interface_data, dict):
            # Check for common NDFC response patterns
            if "data" in interface_data:
                data = interface_data["data"]
                return data if isinstance(data, list) else [data] if data else []
            elif "response" in interface_data:
                data = interface_data["response"]
                return data if isinstance(data, list) else [data] if data else []
            else:
                # Direct object response - wrap in list
                return [interface_data]
        else:
            logger.warning("Unexpected interface data type: %s", type(interface_data))
            return []

    def _process_vrf_attachments(self, parent_endpoint, endpoint_dict):
        """
        Process VRF_Attachments children endpoints for VRF_Configuration.
        Only processes vrfs with vrfStatus = "DEPLOYED".

        Parameters:
            parent_endpoint (dict): The parent Network_Configuration endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configuration
        children_endpoints = parent_endpoint.get("children", [])
        attachments_endpoint = None
        
        for child in children_endpoints:
            if child["name"] == "VRF_Attachments":
                attachments_endpoint = child
                break
        
        if not attachments_endpoint:
            logger.warning("VRF_Attachments child endpoint not found")
            return

        # Process each VRF_Configuration entry
        for config_index, config_entry in enumerate(endpoint_dict[parent_name]):
            if not config_entry.get("data"):
                continue
            
            # Handle both list and single object data structures
            vrf_data = config_entry["data"]
            if not isinstance(vrf_data, list):
                vrf_data = [vrf_data] if vrf_data else []
            
            # Process each vrf in the data
            for vrf_index, vrf in enumerate(vrf_data):
                vrf_status = vrf.get("vrfStatus")
                vrf_name = vrf.get("vrfName")
                
                if vrf_status == "DEPLOYED" and vrf_name:
                    logger.info("Processing VRF_Attachments for deployed vrf: %s", vrf_name)
                    
                    # Build the attachment endpoint URL
                    attachment_url = attachments_endpoint["endpoint"]
                    
                    # Replace placeholders in the URL
                    if self.fabric_name and "%v" in attachment_url:
                        attachment_url = attachment_url.replace("%v", self.fabric_name)
                    
                    if "{{vrf_name}}" in attachment_url:
                        attachment_url = attachment_url.replace("{{vrf_name}}", vrf_name)
                    
                    logger.debug("Fetching vrf attachments from: %s", attachment_url)
                    
                    try:
                        # Fetch the attachment data
                        attachment_data = self.fetch_data(attachment_url)
                        
                        if attachment_data is not None:
                            logger.debug("Successfully retrieved vrf attachments for: %s", vrf_name)
                            
                            # Process the attachment data
                            processed_attachments = self._process_attachment_data(attachment_data)
                            
                            # Add the vrf_attach_group to the vrf
                            vrf["vrf_attach_group"] = processed_attachments
                            
                            logger.info("Added %d vrf attachments for vrf: %s", 
                                      len(processed_attachments) if isinstance(processed_attachments, list) else 1, 
                                      vrf_name)
                        else:
                            logger.warning("Failed to fetch vrf attachments for: %s", vrf_name)
                            vrf["vrf_attach_group"] = []
                    
                    except Exception as e:
                        logger.error("Error fetching vrf attachments for %s: %s", vrf_name, str(e))
                        vrf["vrf_attach_group"] = []
                else:
                    if vrf_status != "DEPLOYED":
                        logger.debug("Skipping vrf %s with status: %s", vrf_name or "unnamed", vrf_status)
                    else:
                        logger.debug("Skipping vrf with missing vrfName")

    def _process_network_attachments(self, parent_endpoint, endpoint_dict):
        """
        Process Network_Attachments children endpoints for Network_Configuration.
        Only processes networks with networkStatus = "DEPLOYED".

        Parameters:
            parent_endpoint (dict): The parent Network_Configuration endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configuration
        children_endpoints = parent_endpoint.get("children", [])
        attachments_endpoint = None
        
        for child in children_endpoints:
            if child["name"] == "Network_Attachments":
                attachments_endpoint = child
                break
        
        if not attachments_endpoint:
            logger.warning("Network_Attachments child endpoint not found")
            return

        # Process each Network_Configuration entry
        for config_index, config_entry in enumerate(endpoint_dict[parent_name]):
            if not config_entry.get("data"):
                continue
            
            # Handle both list and single object data structures
            networks_data = config_entry["data"]
            if not isinstance(networks_data, list):
                networks_data = [networks_data] if networks_data else []
            
            # Process each network in the data
            for network_index, network in enumerate(networks_data):
                network_status = network.get("networkStatus")
                network_name = network.get("networkName")
                
                if network_status == "DEPLOYED" and network_name:
                    logger.info("Processing Network_Attachments for deployed network: %s", network_name)
                    
                    # Build the attachment endpoint URL
                    attachment_url = attachments_endpoint["endpoint"]
                    
                    # Replace placeholders in the URL
                    if self.fabric_name and "%v" in attachment_url:
                        attachment_url = attachment_url.replace("%v", self.fabric_name)
                    
                    if "{{network_name}}" in attachment_url:
                        attachment_url = attachment_url.replace("{{network_name}}", network_name)
                    
                    logger.debug("Fetching network attachments from: %s", attachment_url)
                    
                    try:
                        # Fetch the attachment data
                        attachment_data = self.fetch_data(attachment_url)
                        
                        if attachment_data is not None:
                            logger.debug("Successfully retrieved network attachments for: %s", network_name)
                            
                            # Process the attachment data
                            processed_attachments = self._process_attachment_data(attachment_data)
                            
                            # Add the network_attach_group to the network
                            network["network_attach_group"] = processed_attachments
                            
                            logger.info("Added %d network attachments for network: %s", 
                                      len(processed_attachments) if isinstance(processed_attachments, list) else 1, 
                                      network_name)
                        else:
                            logger.warning("Failed to fetch network attachments for: %s", network_name)
                            network["network_attach_group"] = []
                    
                    except Exception as e:
                        logger.error("Error fetching network attachments for %s: %s", network_name, str(e))
                        network["network_attach_group"] = []
                else:
                    if network_status != "DEPLOYED":
                        logger.debug("Skipping network %s with status: %s", network_name or "unnamed", network_status)
                    else:
                        logger.debug("Skipping network with missing networkName")

    def _process_port_channel_children(self, parent_endpoint, endpoint_dict):
        """
        Process children endpoints for Port-Channel interface types (TrunkPort-Channel, AccessPort-Channel, etc.).
        Fetches child endpoint data (like vPCInterfaceSetting) for each Port-Channel interface.
        
        This method handles all interface types that:
        1. Have a 'vpcEntityId' field with format "serial1~serial2~vpcX"
        2. Are defined in the PORT_CHANNEL_INTERFACE_TYPES class constant
        
        To add support for new Port-Channel interface types:
        1. Add the interface type name to PORT_CHANNEL_INTERFACE_TYPES constant
        2. Define the interface endpoint and children in the YAML configuration
        3. No code changes are required as this method handles them generically

        Parameters:
            parent_endpoint (dict): The parent Port-Channel endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configurations
        children_endpoints = parent_endpoint.get("children", [])
        
        if not children_endpoints:
            logger.debug("No children endpoints defined for %s", parent_name)
            return

        logger.info("Processing %d children endpoints for %s", len(children_endpoints), parent_name)
        
        # Get Port-Channel data from the endpoint_dict
        port_channels = endpoint_dict.get(parent_name, [])
        
        if not port_channels:
            logger.warning("No %s data found to process children for", parent_name)
            return

        # Process each Port-Channel interface
        processed_count = 0
        for port_channel_data in port_channels:
            # Extract vpcEntityId which contains the pattern "serial1~serial2~vpcX"
            vpc_entity_id = port_channel_data.get("vpcEntityId")
            
            if not vpc_entity_id:
                logger.debug("No vpcEntityId found in %s data, skipping", parent_name)
                continue

            # Parse the vpcEntityId to extract vpcPair and vPC_name
            vpc_pair, vpc_name = self._parse_vpc_entity_id(vpc_entity_id)
            
            if not vpc_pair or not vpc_name:
                logger.warning("Failed to parse vpcEntityId: %s", vpc_entity_id)
                continue

            logger.debug("Processing %s children for vpcPair=%s, vPC_name=%s", parent_name, vpc_pair, vpc_name)

            # Process each child endpoint
            for child_endpoint in children_endpoints:
                child_name = child_endpoint["name"]
                child_url = child_endpoint["endpoint"]

                # Replace variables in the child endpoint URL
                child_url = child_url.replace("{{vpcPair}}", vpc_pair)
                child_url = child_url.replace("{{vPC_name}}", vpc_name)

                # Replace fabric ID if present
                if self.fabric_id and "{{fabricID}}" in child_url:
                    child_url = child_url.replace("{{fabricID}}", str(self.fabric_id))

                logger.debug("Fetching child endpoint: %s -> %s", child_name, child_url)

                try:
                    response = self.client.get(f"{self.base_url}{child_url}")
                    response.raise_for_status()
                    child_data = response.json()

                    # Save child data directly to the Port-Channel entry using the child endpoint name as key
                    port_channel_data[child_name] = child_data

                    processed_count += 1
                    logger.debug("Successfully processed and saved child endpoint %s to %s entry for %s", child_name, parent_name, vpc_name)

                except Exception as e:
                    logger.error("Error processing child endpoint %s for %s: %s", child_name, vpc_name, str(e))
                    # Set empty data on error to maintain consistent structure
                    port_channel_data[child_name] = {}

        logger.info("Completed processing %s children. Processed %d items", parent_name, processed_count)

    def _process_vpc_pairs_children(self, parent_endpoint, endpoint_dict):
        """
        Process children endpoints for VPC pair types (VPC_Pairs).
        Fetches child endpoint data (like VPC_PeerLinkSettings) for each VPC pair.
        
        This method handles all VPC pair types that:
        1. Have a 'peerOneId' field
        2. Are defined in the VPC_PAIR_TYPES class constant
        
        To add support for new VPC pair types:
        1. Add the new type to the VPC_PAIR_TYPES list
        2. Ensure the child endpoint uses {{peerOneId}} placeholder in the YAML
        
        Parameters:
            parent_endpoint (dict): The parent VPC pair endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configurations
        children_endpoints = parent_endpoint.get("children", [])
        
        if not children_endpoints:
            logger.debug("No children endpoints defined for %s", parent_name)
            return

        logger.info("Processing %d children endpoints for %s", len(children_endpoints), parent_name)
        
        # Get VPC pairs data from the endpoint_dict
        vpc_pairs_entries = endpoint_dict.get(parent_name, [])
        
        if not vpc_pairs_entries:
            logger.warning("No %s data found to process children for", parent_name)
            return

        # Extract VPC pairs from the nested data structure
        # VPC_Pairs structure: [{"data": [vpc_pair_objects], "endpoint": "...", "fabric": "..."}]
        all_vpc_pairs = []
        for entry in vpc_pairs_entries:
            if isinstance(entry, dict) and "data" in entry:
                vpc_data = entry["data"]
                if isinstance(vpc_data, list):
                    all_vpc_pairs.extend(vpc_data)
                elif vpc_data:  # single object
                    all_vpc_pairs.append(vpc_data)

        if not all_vpc_pairs:
            logger.warning("No VPC pair data found in %s entries", parent_name)
            return

        # Process each VPC pair
        processed_count = 0
        for vpc_pair_data in all_vpc_pairs:
            # Extract peerOneId which identifies the VPC pair
            peer_one_id = vpc_pair_data.get("peerOneId")
            
            if not peer_one_id:
                logger.debug("No peerOneId found in %s data, skipping", parent_name)
                continue

            logger.debug("Processing %s children for peerOneId=%s", parent_name, peer_one_id)

            # Process each child endpoint
            for child_endpoint in children_endpoints:
                child_name = child_endpoint["name"]
                child_url = child_endpoint["endpoint"]

                # Replace peerOneId variable in the child endpoint URL
                child_url = child_url.replace("{{peerOneId}}", str(peer_one_id))

                # Replace fabric ID if present
                if self.fabric_id and "{{fabricID}}" in child_url:
                    child_url = child_url.replace("{{fabricID}}", str(self.fabric_id))

                logger.debug("Fetching child endpoint: %s -> %s", child_name, child_url)

                try:
                    response = self.client.get(f"{self.base_url}{child_url}")
                    response.raise_for_status()
                    child_data = response.json()

                    # Save child data directly to the VPC pair entry using the child endpoint name as key
                    vpc_pair_data[child_name] = child_data

                    processed_count += 1
                    logger.debug("Successfully processed and saved child endpoint %s to %s entry for peerOneId=%s", child_name, parent_name, peer_one_id)

                except Exception as e:
                    logger.error("Error processing child endpoint %s for peerOneId=%s: %s", child_name, peer_one_id, str(e))
                    # Set empty data on error to maintain consistent structure
                    vpc_pair_data[child_name] = {}

        logger.info("Completed processing %s children. Processed %d items", parent_name, processed_count)

    def _process_serial_interface_children(self, parent_endpoint, endpoint_dict):
        """
        Process children endpoints for interface types that use serialNumber + ifName pattern.
        Fetches child endpoint data (like LoopbackInterfaceSetting) for each interface.
        
        This method handles all interface types that:
        1. Have 'serialNo' and 'ifName' fields in the interface data
        2. Are defined in the SERIAL_INTERFACE_TYPES class constant
        3. Use {{serialNumber}} and {{ifName}} placeholders in child endpoints
        
        To add support for new serial-based interface types:
        1. Add the interface type name to SERIAL_INTERFACE_TYPES constant
        2. Define the interface endpoint and children in the YAML configuration
        3. No code changes are required as this method handles them generically

        Parameters:
            parent_endpoint (dict): The parent interface endpoint.
            endpoint_dict (dict): The dictionary containing the processed data.
        """
        parent_name = parent_endpoint["name"]
        
        # Get the children endpoint configurations
        children_endpoints = parent_endpoint.get("children", [])
        
        if not children_endpoints:
            logger.debug("No children endpoints defined for %s", parent_name)
            return

        logger.info("Processing %d children endpoints for %s", len(children_endpoints), parent_name)
        
        # Get interface data from the endpoint_dict
        interfaces = endpoint_dict.get(parent_name, [])
        
        if not interfaces:
            logger.warning("No %s data found to process children for", parent_name)
            return

        # Process each interface
        processed_count = 0
        for interface_data in interfaces:
            # Extract serialNo and ifName from the interface data
            serial_number = interface_data.get("serialNo")
            if_name = interface_data.get("ifName")
            
            if not serial_number or not if_name:
                logger.debug("Missing serialNo or ifName in %s data, skipping", parent_name)
                continue

            logger.debug("Processing %s children for serialNumber=%s, ifName=%s", parent_name, serial_number, if_name)

            # Process each child endpoint
            for child_endpoint in children_endpoints:
                child_name = child_endpoint["name"]
                child_url = child_endpoint["endpoint"]

                # Replace variables in the child endpoint URL
                child_url = child_url.replace("{{serialNumber}}", serial_number)
                child_url = child_url.replace("{{ifName}}", if_name)

                # Replace fabric ID if present
                if self.fabric_id and "{{fabricID}}" in child_url:
                    child_url = child_url.replace("{{fabricID}}", str(self.fabric_id))

                logger.debug("Fetching child endpoint: %s -> %s", child_name, child_url)

                try:
                    response = self.client.get(f"{self.base_url}{child_url}")
                    response.raise_for_status()
                    child_data = response.json()

                    # Save child data directly to the interface entry using the child endpoint name as key
                    interface_data[child_name] = child_data

                    processed_count += 1
                    logger.debug("Successfully processed and saved child endpoint %s to %s entry for %s", child_name, parent_name, if_name)

                except Exception as e:
                    logger.error("Error processing child endpoint %s for %s: %s", child_name, if_name, str(e))
                    # Set empty data on error to maintain consistent structure
                    interface_data[child_name] = {}

        logger.info("Completed processing %s children. Processed %d items", parent_name, processed_count)

    def _process_nested_children_for_interfaces(self, parent_endpoint, interface_data, host_name):
        """
        Process nested children endpoints for interface data (like Port-Channel interfaces -> vPCInterfaceSetting).
        
        Parameters:
            parent_endpoint (dict): The parent endpoint configuration with children
            interface_data (list): The interface data from the parent endpoint 
            host_name (str): The hostname of the switch being processed
        """
        parent_name = parent_endpoint["name"]
        children_endpoints = parent_endpoint.get("children", [])
        
        if not children_endpoints:
            return
            
        logger.info("Processing %d nested children for %s interfaces on switch %s", 
                   len(children_endpoints), parent_name, host_name)
        
        # Process each interface entry in the interface_data
        for interface_entry in interface_data if isinstance(interface_data, list) else [interface_data]:
            if not isinstance(interface_entry, dict):
                continue
                
            # For Port-Channel interfaces (TrunkPort-Channel, AccessPort-Channel, etc.), look for vpcEntityId
            if parent_name in self.PORT_CHANNEL_INTERFACE_TYPES:
                vpc_entity_id = interface_entry.get("vpcEntityId")
                
                if not vpc_entity_id:
                    logger.debug("No vpcEntityId found in %s interface, skipping nested children", parent_name)
                    continue
                
                # Parse the vpcEntityId to extract vpcPair and vPC_name
                vpc_pair, vpc_name = self._parse_vpc_entity_id(vpc_entity_id)
                
                if not vpc_pair or not vpc_name:
                    logger.warning("Failed to parse vpcEntityId: %s", vpc_entity_id)
                    continue
                
                logger.debug("Processing nested children for vpcPair=%s, vPC_name=%s on switch %s", 
                           vpc_pair, vpc_name, host_name)
                
                # Process each nested child endpoint
                for child_endpoint in children_endpoints:
                    child_name = child_endpoint["name"]
                    child_url = child_endpoint["endpoint"]
                    
                    # Replace variables in the child endpoint URL
                    child_url = child_url.replace("{{vpcPair}}", vpc_pair)
                    child_url = child_url.replace("{{vPC_name}}", vpc_name)
                    
                    # Replace fabric ID if present
                    if self.fabric_id and "{{fabricID}}" in child_url:
                        child_url = child_url.replace("{{fabricID}}", str(self.fabric_id))
                    
                    logger.debug("Fetching nested child endpoint: %s -> %s", child_name, child_url)
                    
                    try:
                        response = self.client.get(f"{self.base_url}{child_url}")
                        response.raise_for_status()
                        child_data = response.json()
                        
                        # Save child data directly to the interface entry using the child endpoint name as key
                        interface_entry[child_name] = child_data
                        
                        logger.debug("Successfully processed and saved nested child endpoint %s to interface entry for %s on switch %s", 
                                   child_name, vpc_name, host_name)
                        
                    except Exception as e:
                        logger.error("Error processing nested child endpoint %s for %s on switch %s: %s", 
                                   child_name, vpc_name, host_name, str(e))
                        # Set empty data on error to maintain consistent structure
                        interface_entry[child_name] = {}
                        
            # For serial-based interfaces (LoopbackInterfaces, etc.), look for serialNo and ifName
            elif parent_name in self.SERIAL_INTERFACE_TYPES:
                serial_number = interface_entry.get("serialNo")
                if_name = interface_entry.get("ifName")
                
                if not serial_number or not if_name:
                    logger.debug("No serialNo or ifName found in %s interface, skipping nested children", parent_name)
                    continue
                
                logger.debug("Processing nested children for serialNumber=%s, ifName=%s on switch %s", 
                           serial_number, if_name, host_name)
                
                # Process each nested child endpoint
                for child_endpoint in children_endpoints:
                    child_name = child_endpoint["name"]
                    child_url = child_endpoint["endpoint"]
                    
                    # Replace variables in the child endpoint URL
                    child_url = child_url.replace("{{serialNumber}}", serial_number)
                    child_url = child_url.replace("{{ifName}}", if_name)
                    
                    # Replace fabric ID if present
                    if self.fabric_id and "{{fabricID}}" in child_url:
                        child_url = child_url.replace("{{fabricID}}", str(self.fabric_id))
                    
                    logger.debug("Fetching nested child endpoint: %s -> %s", child_name, child_url)
                    
                    try:
                        response = self.client.get(f"{self.base_url}{child_url}")
                        response.raise_for_status()
                        child_data = response.json()
                        
                        # Save child data directly to the interface entry using the child endpoint name as key
                        interface_entry[child_name] = child_data
                        
                        logger.debug("Successfully processed and saved nested child endpoint %s to interface entry for %s on switch %s", 
                                   child_name, if_name, host_name)
                        
                    except Exception as e:
                        logger.error("Error processing nested child endpoint %s for %s on switch %s: %s", 
                                   child_name, if_name, host_name, str(e))
                        # Set empty data on error to maintain consistent structure
                        interface_entry[child_name] = {}

    def _parse_vpc_entity_id(self, vpc_entity_id: str) -> tuple:
        """
        Parse vpcEntityId string to extract vpcPair and vPC_name.
        
        Expected format: "serial1~serial2~vpcX"
        Example: "FDO26260888~FDO26260897~vpc10"
        
        Parameters:
            vpc_entity_id (str): The vpcEntityId string to parse
            
        Returns:
            tuple: (vpcPair, vPC_name) where vpcPair is "serial1~serial2" and vPC_name is "vpcX"
        """
        if not vpc_entity_id or not isinstance(vpc_entity_id, str):
            logger.warning("Invalid vpcEntityId provided: %s", vpc_entity_id)
            return None, None

        # Split by '~' to get components
        parts = vpc_entity_id.split('~')
        
        if len(parts) != 3:
            logger.warning("vpcEntityId does not have expected format 'serial1~serial2~vpcX': %s", vpc_entity_id)
            return None, None

        # Extract components
        serial1, serial2, vpc_name = parts
        
        # Validate that vpc_name starts with "vpc"
        if not vpc_name.startswith("vpc"):
            logger.warning("vPC name does not start with 'vpc': %s", vpc_name)
            return None, None

        # Construct vpcPair as "serial1~serial2"
        vpc_pair = f"{serial1}~{serial2}"
        
        logger.debug("Parsed vpcEntityId '%s' -> vpcPair='%s', vPC_name='%s'", vpc_entity_id, vpc_pair, vpc_name)
        
        return vpc_pair, vpc_name

    def load_endpoints_from_file(self, endpoints_file: str) -> List[Dict[str, Any]]:
        """
        Load endpoints configuration from YAML file.

        Args:
            endpoints_file: Path to YAML file

        Returns:
            List[Dict[str, Any]]: List of endpoint configurations
        """
        try:
            with open(endpoints_file, 'r', encoding='utf-8') as f:
                yaml_data = self.yaml.load(f)
                return yaml_data.get('endpoints', [])
        except FileNotFoundError:
            logger.error("Endpoints file not found: %s", endpoints_file)
            return []
        except Exception as e:
            logger.error("Error loading endpoints file: %s", str(e))
            return []
