"""
Android Enterprise EMM Service
Uses Google Android Management API (AMAPI) to manage Android devices.

Docs: https://developers.google.com/android/management/reference/rest
"""
import json
from typing import Optional
from app.config import get_settings
from app.models.command import CommandType

settings = get_settings()


def _get_amapi_service():
    """Build Google AMAPI client from service account."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/androidmanagement"],
        )
        return build("androidmanagement", "v1", credentials=creds)
    except Exception as e:
        print(f"[Android EMM] Cannot build AMAPI service: {e}")
        return None


async def create_enrollment_token(org_id: str, is_byod: bool = False) -> dict:
    """
    Create an Android Enterprise enrollment token.
    Returns enrollment url and QR code token.
    """
    service = _get_amapi_service()
    enterprise_id = settings.ANDROID_ENTERPRISE_ID

    if not service or not enterprise_id:
        # Return stub token for development
        import uuid
        stub_token = str(uuid.uuid4())
        return {
            "enrollment_token": stub_token,
            "qr_code_token": stub_token,
            "enrollment_url": f"https://enterprise.google.com/android/enroll?et={stub_token}",
            "expires_at": None,
        }

    policy_name = f"enterprises/{enterprise_id}/policies/{'byod' if is_byod else 'managed'}"

    token_response = service.enterprises().enrollmentTokens().create(
        parent=f"enterprises/{enterprise_id}",
        body={
            "policyName": policy_name,
            "duration": "604800s",  # 7 days
        }
    ).execute()

    return {
        "enrollment_token": token_response.get("value"),
        "qr_code_token": token_response.get("qrCode"),
        "enrollment_url": token_response.get("enrollmentTokenUrl"),
        "expires_at": token_response.get("expirationTimestamp"),
    }


async def send_android_command(device, command: CommandType, payload: dict) -> bool:
    """
    Send an AMAPI command to an Android device.
    Maps internal CommandType to Google AMAPI command names.
    """
    service = _get_amapi_service()
    if not service or not device.android_id or not settings.ANDROID_ENTERPRISE_ID:
        print(f"[Android EMM] Stub: command {command} sent to {device.id}")
        return True

    enterprise_id = settings.ANDROID_ENTERPRISE_ID
    device_name = f"enterprises/{enterprise_id}/devices/{device.android_id}"

    amapi_command_map = {
        CommandType.ANDROID_LOCK: {"type": "LOCK"},
        CommandType.ANDROID_WIPE: {"type": "RESET_PASSWORD", "resetPasswordFlags": ["WIPE_DATA"]},
        CommandType.ANDROID_RESET_PASSWORD: {
            "type": "RESET_PASSWORD",
            "newPassword": payload.get("new_password", ""),
            "resetPasswordFlags": [],
        },
    }

    amapi_cmd = amapi_command_map.get(command)
    if not amapi_cmd:
        print(f"[Android EMM] No AMAPI mapping for {command}")
        return False

    service.enterprises().devices().issueCommand(
        name=device_name,
        body=amapi_cmd,
    ).execute()
    return True


async def get_android_device_info(android_device_id: str) -> Optional[dict]:
    """Fetch device details from Android Management API."""
    service = _get_amapi_service()
    if not service or not settings.ANDROID_ENTERPRISE_ID:
        return None

    enterprise_id = settings.ANDROID_ENTERPRISE_ID
    device_name = f"enterprises/{enterprise_id}/devices/{android_device_id}"

    try:
        return service.enterprises().devices().get(name=device_name).execute()
    except Exception as e:
        print(f"[Android EMM] Failed to get device info: {e}")
        return None
