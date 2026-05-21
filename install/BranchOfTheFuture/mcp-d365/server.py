"""
MCP Server for Dynamics 365 Dataverse
Exposes D365 customer data as tools for any MCP-compatible AI client.
Reusable across banking customers -- swap org URL and credentials.

Tools:
  - d365_customer_lookup: Search contacts by name
  - d365_check_in_queue: Get branch check-in queue
  - d365_log_activity: Create a task/note on a contact record
  - d365_recent_activities: Get recent activities for a contact

Run: python server.py
"""

import os
import sys
import json
import time
import logging
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

# ---------------------------------------------------------------------------
# Configuration -- swap these for different customers/tenants
# ---------------------------------------------------------------------------
D365_ORG_URL = os.environ.get(
    "D365_ORG_URL",
    "https://orgdf28000a.crm.dynamics.com"
)
D365_API_URL = D365_ORG_URL + "/api/data/v9.2"
D365_TENANT = os.environ.get(
    "D365_TENANT",
    "D365DemoTSCE32685848.onmicrosoft.com"
)
# Public client ID for device code flow (Azure PowerShell)
D365_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-d365")

# ---------------------------------------------------------------------------
# Token management (shared with main app via cache file)
# ---------------------------------------------------------------------------
_token_cache = None
_token_expiry = 0
_TOKEN_CACHE_FILE = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'NPUDemo',
    'd365_token_cache.json'
)


def _get_token() -> str | None:
    """Get a valid D365 access token. Uses cached file from main app or MSAL."""
    global _token_cache, _token_expiry

    if _token_cache and time.time() < (_token_expiry - 300):
        return _token_cache

    try:
        import msal

        cache = msal.SerializableTokenCache()
        if os.path.exists(_TOKEN_CACHE_FILE):
            with open(_TOKEN_CACHE_FILE, "r") as f:
                cache.deserialize(f.read())

        authority = f"https://login.microsoftonline.com/{D365_TENANT}"
        scope = [D365_ORG_URL + "/.default"]
        app = msal.PublicClientApplication(
            D365_CLIENT_ID, authority=authority, token_cache=cache
        )

        # Try silent acquisition from cache
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scope, account=accounts[0])
            if result and "access_token" in result:
                _token_cache = result["access_token"]
                _token_expiry = time.time() + result.get("expires_in", 3600)
                if cache.has_state_changed:
                    with open(_TOKEN_CACHE_FILE, "w") as f:
                        f.write(cache.serialize())
                logger.info("D365 token acquired silently")
                return _token_cache

        logger.warning("No cached D365 token. Authenticate via the main app first.")
        return None

    except ImportError:
        logger.error("msal not installed")
        return None
    except Exception as e:
        logger.error(f"Token error: {e}")
        return None


def _api_get(path: str, params: dict | None = None) -> dict | None:
    """Authenticated GET to Dataverse Web API."""
    token = _get_token()
    if not token:
        return None
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Prefer": "odata.include-annotations=*",
        }
        resp = requests.get(D365_API_URL + path, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"API GET {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"API GET failed: {e}")
        return None


def _api_post(path: str, payload: dict) -> dict | None:
    """Authenticated POST to Dataverse Web API."""
    token = _get_token()
    if not token:
        return None
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        resp = requests.post(D365_API_URL + path, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201, 204):
            return resp.json() if resp.text else {"status": "created"}
        logger.error(f"API POST {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"API POST failed: {e}")
        return None


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
if _HAS_MCP:
    mcp = FastMCP(
        "Dynamics 365 Banking",
        instructions="MCP server for Dynamics 365 Dataverse. Provides tools to look up customers, check branch queues, log activities, and view recent interactions."
    )
    _tool_decorator = mcp.tool()
else:
    mcp = None
    _tool_decorator = lambda fn: fn  # no-op when imported directly by Flask


@_tool_decorator
def d365_customer_lookup(name: str) -> str:
    """Look up a customer contact in Dynamics 365 by name.
    Returns customer profile including name, email, phone, address, and account details.
    Use this when the advisor asks about a specific customer or needs to pull up a client profile.

    Args:
        name: Customer name to search for (full or partial)
    """
    safe_name = name.replace("'", "''")
    result = _api_get(
        "/contacts",
        params={
            "$filter": f"contains(fullname,'{safe_name}')",
            "$select": "contactid,fullname,emailaddress1,telephone1,mobilephone,"
                       "address1_composite,jobtitle,description",
            "$top": "3",
        },
    )

    if not result or not result.get("value"):
        # Fallback demo data
        if "rodriguez" in name.lower() or "jackie" in name.lower():
            return json.dumps({
                "source": "demo",
                "customer": {
                    "name": "Jackie Marie Rodriguez",
                    "email": "jackie.rodriguez@email.com",
                    "phone": "(248) 555-0147",
                    "address": "1847 Maple Avenue, Troy, MI 48083",
                    "account_type": "Retail",
                    "source": "Referral",
                    "notes": "New client. Interested in 529 Plan and Roth IRA conversion.",
                },
            })
        return f"No customer found matching '{name}'."

    contacts = []
    for c in result["value"]:
        contacts.append({
            "id": c.get("contactid"),
            "name": c.get("fullname"),
            "email": c.get("emailaddress1", "N/A"),
            "phone": c.get("telephone1") or c.get("mobilephone", "N/A"),
            "address": c.get("address1_composite", "N/A"),
            "title": c.get("jobtitle", ""),
            "notes": c.get("description", ""),
        })

    return json.dumps({"source": "live", "contacts": contacts}, indent=2)


@_tool_decorator
def d365_check_in_queue() -> str:
    """Get the current branch check-in queue from the kiosk Power App.
    Returns a list of customers currently waiting in the branch lobby.
    Use this when the branch manager asks who is waiting or what the queue looks like.
    """
    result = _api_get(
        "/ikl_checkinentities",
        params={
            "$select": "ikl_name,ikl_checkintime,ikl_reason,ikl_status_new,ikl_meetingduration",
            "$orderby": "ikl_checkintime desc",
            "$top": "10",
        },
    )

    if not result or not result.get("value"):
        # Demo fallback
        return json.dumps({
            "source": "demo",
            "queue": [
                {
                    "name": "Jackie Rodriguez",
                    "check_in_time": "1:45 PM",
                    "reason": "New account opening + 529 plan inquiry",
                    "status": "Waiting",
                    "estimated_duration": "30 min",
                },
                {
                    "name": "Marcus Chen",
                    "check_in_time": "1:52 PM",
                    "reason": "Wire transfer assistance",
                    "status": "Waiting",
                    "estimated_duration": "15 min",
                },
            ],
            "message": "2 customers waiting in lobby",
        })

    queue = []
    for record in result["value"]:
        checkin_time = record.get("ikl_checkintime", "")
        if checkin_time:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(checkin_time.replace("Z", "+00:00"))
                checkin_time = dt.strftime("%I:%M %p").lstrip("0")
            except Exception:
                pass

        queue.append({
            "name": record.get("ikl_name", "Unknown"),
            "check_in_time": checkin_time,
            "reason": record.get("ikl_reason", "Not specified"),
            "status": record.get("ikl_status_new", "Waiting"),
            "estimated_duration": record.get("ikl_meetingduration", "N/A"),
        })

    return json.dumps({
        "source": "live",
        "queue": queue,
        "message": f"{len(queue)} customer(s) in queue",
    }, indent=2)


@_tool_decorator
def d365_log_activity(customer_name: str, note: str, activity_type: str = "task") -> str:
    """Log an activity (task or note) on a customer's D365 contact record.
    Use this when the advisor wants to log meeting notes, follow-up tasks, or any activity.

    Args:
        customer_name: Name of the customer to log the activity on
        note: The note or task description to log
        activity_type: Type of activity -- "task" or "note" (default: task)
    """
    # Find the contact
    safe_name = customer_name.replace("'", "''")
    contact_result = _api_get(
        "/contacts",
        params={
            "$filter": f"contains(fullname,'{safe_name}')",
            "$select": "contactid,fullname",
            "$top": "1",
        },
    )

    if not contact_result or not contact_result.get("value"):
        return f"Could not find contact '{customer_name}' in D365."

    contact = contact_result["value"][0]
    contact_id = contact["contactid"]
    contact_name = contact["fullname"]

    # Create the activity
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    payload = {
        "subject": f"{activity_type.title()}: {note[:80]}",
        "description": f"{note}\n\nLogged by on-device AI assistant (NPU). No data egress.",
        "regardingobjectid_contact@odata.bind": f"/contacts({contact_id})",
        "scheduledend": now,
        "prioritycode": 2,
    }

    result = _api_post("/tasks", payload)
    if result:
        activity_id = result.get("activityid", "created")
        return json.dumps({
            "source": "live",
            "status": "success",
            "message": f"Activity logged on {contact_name}'s record",
            "activity_id": activity_id,
            "timestamp": now,
        })

    return f"Failed to log activity on {contact_name}'s record. D365 may be unreachable."


@_tool_decorator
def d365_recent_activities(customer_name: str) -> str:
    """Get recent activities and timeline entries for a customer.
    Use this when the advisor asks about recent interactions, meeting history, or account activity.

    Args:
        customer_name: Name of the customer
    """
    safe_name = customer_name.replace("'", "''")
    contact_result = _api_get(
        "/contacts",
        params={
            "$filter": f"contains(fullname,'{safe_name}')",
            "$select": "contactid,fullname",
            "$top": "1",
        },
    )

    if not contact_result or not contact_result.get("value"):
        return f"No contact found matching '{customer_name}'."

    contact = contact_result["value"][0]
    contact_id = contact["contactid"]

    activities = _api_get(
        "/activitypointers",
        params={
            "$filter": f"_regardingobjectid_value eq {contact_id}",
            "$select": "subject,description,actualstart,activitytypecode,statecode",
            "$orderby": "actualstart desc",
            "$top": "5",
        },
    )

    if not activities or not activities.get("value"):
        return json.dumps({
            "source": "live",
            "customer": contact["fullname"],
            "activities": [],
            "message": "No recent activities found.",
        })

    items = []
    for act in activities["value"]:
        date = (act.get("actualstart") or "")[:10]
        items.append({
            "date": date,
            "type": act.get("activitytypecode", "activity"),
            "subject": act.get("subject", ""),
            "description": (act.get("description") or "")[:150],
            "status": "completed" if act.get("statecode") == 1 else "open",
        })

    return json.dumps({
        "source": "live",
        "customer": contact["fullname"],
        "activities": items,
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not _HAS_MCP:
        print("ERROR: 'mcp' package required to run as standalone server. pip install mcp")
        sys.exit(1)
    logger.info(f"Starting MCP D365 Server")
    logger.info(f"  Org: {D365_ORG_URL}")
    logger.info(f"  Tenant: {D365_TENANT}")
    logger.info(f"  Token cache: {_TOKEN_CACHE_FILE}")
    mcp.run(transport="stdio")
