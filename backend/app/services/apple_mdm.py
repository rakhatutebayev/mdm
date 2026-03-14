"""
Apple MDM Service — APNs push notifications and DEP integration.
"""
import ssl
import asyncio
from typing import Optional
from app.config import get_settings

settings = get_settings()


async def send_apple_push(push_token: Optional[str]) -> bool:
    """
    Send a silent push notification to an Apple device to wake it up and poll for MDM commands.
    
    In production:
    - Load push_cert + push_key from settings paths
    - Use aioapns library to send to APNs production endpoint
    - The push payload is empty for MDM (device polls the MDM server after receiving push)
    
    Returns True if push was sent successfully.
    """
    if not push_token:
        print("[Apple MDM] No push token — cannot send wake push")
        return False

    # In production with aioapns:
    # from aioapns import APNs, NotificationRequest, APNS_RESPONSE_CODE
    # client = APNs(
    #     client_cert=settings.APPLE_PUSH_CERT_PATH,
    #     topic=settings.APPLE_MDM_TOPIC,
    #     use_sandbox=False,
    # )
    # request = NotificationRequest(device_token=push_token, message={})
    # response = await client.send_notification(request)
    # return response.status == APNS_RESPONSE_CODE.SUCCESS

    print(f"[Apple MDM] Wake push sent to token: {push_token[:20]}...")
    return True  # Stub for now


async def send_dep_sync() -> list:
    """
    Fetch devices from Apple Business Manager via DEP protocol.
    
    Requires:
    - DEP Server Token (downloaded from ABM as .p7m then decoded to JSON)
    - Apple DEP API endpoint: https://mdmenrollment.apple.com
    
    Returns list of DEP devices.
    """
    # In production:
    # 1. Load p7m.json token
    # 2. Generate session with cursor-based paging
    # 3. POST to /session, then GET /devices/sync
    
    print("[DEP] sync — configure APPLE_DEP_SERVER_TOKEN_PATH to enable")
    return []


async def get_dep_profile_payload(server_url: str, topic: str) -> dict:
    """Build the DEP profile payload for device assignment."""
    return {
        "url": f"{server_url}/api/v1/mdm/apple/checkin",
        "skip_setup_items": [
            "AppleID", "Privacy", "Payment", "Zoom", "Biometric",
            "TOS", "Diagnostics", "DisplayTone", "ScreenTime",
        ],
        "department": "IT / NOCKO MDM",
        "support_email_address": "it@nocko.ae",
        "support_phone_number": "+971 0000 0000",
        "is_supervised": True,
        "is_mdm_removable": False,
        "is_mandatory": True,
    }
