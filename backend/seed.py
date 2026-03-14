"""Seed initial data matching the previously mocked frontend data."""
import asyncio
from database import AsyncSessionLocal, engine, Base
from models import Customer, Device, NetworkInfo, MonitorInfo, EnrollmentToken
import secrets


def tok() -> str:
    return "enroll-" + secrets.token_urlsafe(8).upper()


CUSTOMERS_DATA = [
    {"slug": "default", "name": "DEFAULT_CUSTOMER"},
    {"slug": "nocko", "name": "NOCKO IT"},
    {"slug": "strattech", "name": "Strategic Technology Solutions"},
    {"slug": "almatygroup", "name": "Almaty Group"},
    {"slug": "delta", "name": "Delta Corp"},
]

DEVICES_DATA = [
    {
        "slug": "default",
        "device": dict(device_name="DESKTOP-RAKHAT01", platform="Windows", device_type="Desktop",
                       model="OptiPlex 7090", manufacturer="Dell Inc.",
                       serial_number="DL-7090-2024-A1B2", udid="A1B2C3D4E5F60001001100120013",
                       os_version="Windows 11 Pro 23H2", architecture="x64",
                       owner="admin@it-uae.com", enrollment_method="Agent", status="Enrolled"),
        "network": dict(ip_address="192.168.1.101", mac_address="AA:BB:CC:DD:EE:01",
                        hostname="DESKTOP-RAKHAT01", wifi_ssid="Office-5G",
                        connection_type="Wi-Fi", dns_server="8.8.8.8, 8.8.4.4",
                        default_gateway="192.168.1.1"),
        "monitors": [
            dict(display_index=1, model="Dell U2722D", serial_number="CN-0WK37P-74184-8B6-08BR",
                 display_size='27" IPS', resolution="2560 × 1440 (QHD)", refresh_rate="60 Hz",
                 color_depth="32-bit", connection_type="DisplayPort 1.4", hdr_support=True),
            dict(display_index=2, model="Dell P2422H", serial_number="CN-0XYZA1-74184-9C2-01BK",
                 display_size='24" IPS', resolution="1920 × 1080 (FHD)", refresh_rate="60 Hz",
                 color_depth="32-bit", connection_type="HDMI 2.0", hdr_support=False),
        ],
    },
    {
        "slug": "default",
        "device": dict(device_name="LAPTOP-USER02", platform="Windows", device_type="Laptop",
                       model="ThinkPad X1 Carbon Gen 11", manufacturer="Lenovo",
                       serial_number="LN-X1C-2024-C3D4", udid="B2C3D4E5F60120130014001500160017",
                       os_version="Windows 10 Pro 22H2", architecture="x64",
                       owner="user2@it-uae.com", enrollment_method="Agent", status="Enrolled"),
        "network": dict(ip_address="192.168.1.102", mac_address="AA:BB:CC:DD:EE:02",
                        hostname="LAPTOP-USER02", wifi_ssid="Office-2G",
                        connection_type="Wi-Fi", dns_server="192.168.1.1",
                        default_gateway="192.168.1.1"),
        "monitors": [
            dict(display_index=1, model="ThinkPad X1 Built-in IPS", serial_number="LN-IPS14-2024-E7F8G9",
                 display_size='14"', resolution="1920 × 1200 (WUXGA)", refresh_rate="60 Hz",
                 color_depth="32-bit", connection_type="Built-in eDP", hdr_support=False),
        ],
    },
    {
        "slug": "nocko",
        "device": dict(device_name="RAKHATUTEBA511A", platform="macOS", device_type="Tablet",
                       model="Parallels ARM Virtual Machine",
                       manufacturer="Parallels International GmbH.",
                       serial_number="Parallels-FD F9 41 14 7A 16 43 13 88 3F 42 3E 83 09 78 52",
                       udid="0D9E8096AF0AEE4A8565B0F8B5004FE9",
                       os_version="macOS 14 Sonoma (ARM)", architecture="arm64 (Apple Silicon)",
                       owner="hr@it-uae.com", enrollment_method="MDM Profile", status="Enrolled"),
        "network": dict(ip_address="10.211.55.14", mac_address="F2:3A:4B:5C:6D:7E",
                        hostname="Rakhatuteba511A.local", wifi_ssid="Parallels Shared Network",
                        connection_type="Ethernet (Virtual)", dns_server="10.211.55.1",
                        default_gateway="10.211.55.1"),
        "monitors": [
            dict(display_index=1, model="Parallels Virtual Display", serial_number="VIRT-PRL-0000-0001",
                 display_size="—", resolution="2560 × 1600 (Virtual)", refresh_rate="60 Hz",
                 color_depth="32-bit", connection_type="Virtual GPU (Parallels)", hdr_support=False),
        ],
    },
    {
        "slug": "nocko",
        "device": dict(device_name="PC-FINANCE-01", platform="Windows", device_type="Desktop",
                       model="ProDesk 600 G6", manufacturer="HP Inc.",
                       serial_number="HP-PD600-2024-E5F6",
                       udid="C3D4E5F601001300140015001600170018",
                       os_version="Windows 11 Pro 23H2", architecture="x64",
                       owner="finance@it-uae.com", enrollment_method="AutoPilot", status="Pending"),
        "network": dict(ip_address="—", mac_address="AA:BB:CC:DD:EE:04",
                        hostname="PC-FINANCE-01", wifi_ssid="—", connection_type="—",
                        dns_server="—", default_gateway="—"),
        "monitors": [
            dict(display_index=1, model="HP EliteDisplay E243", serial_number="HP-E243-2024-01BK",
                 display_size='23.8"', resolution="1920 × 1080 (FHD)", refresh_rate="60 Hz",
                 color_depth="24-bit", connection_type="VGA / DisplayPort", hdr_support=False),
        ],
    },
    {
        "slug": "strattech",
        "device": dict(device_name="WS-ST-001", platform="Windows", device_type="Desktop",
                       model="EliteDesk 800", manufacturer="HP Inc.",
                       serial_number="HP-EL800-ST-001", udid="D4E5F6010014001500160017",
                       os_version="Windows 11 Pro 23H2", architecture="x64",
                       owner="john@strattech.com", enrollment_method="Agent", status="Enrolled"),
        "network": dict(ip_address="10.10.1.50", mac_address="BB:CC:DD:EE:FF:01",
                        hostname="WS-ST-001", wifi_ssid="StratTech-Corp",
                        connection_type="Ethernet", dns_server="10.10.1.1",
                        default_gateway="10.10.1.1"),
        "monitors": [
            dict(display_index=1, model="HP E24 G4", serial_number="HP-E24G4-ST-001",
                 display_size='23.8"', resolution="1920 × 1080 (FHD)", refresh_rate="60 Hz",
                 color_depth="24-bit", connection_type="DisplayPort", hdr_support=False),
        ],
    },
    {
        "slug": "almatygroup",
        "device": dict(device_name="iPhone-CEO", platform="iOS", device_type="Smartphone",
                       model="iPhone 15 Pro", manufacturer="Apple Inc.",
                       serial_number="APPLE-IP15P-CEO-001", udid="E5F60100150016001700180019",
                       os_version="iOS 17.4", architecture="arm64",
                       owner="ceo@almaty.kz", enrollment_method="MDM Profile", status="Enrolled"),
        "network": dict(ip_address="192.168.50.10", mac_address="CC:DD:EE:FF:00:01",
                        hostname="iPhone-CEO.local", wifi_ssid="AlmatyGroup-Office",
                        connection_type="Wi-Fi", dns_server="8.8.8.8",
                        default_gateway="192.168.50.1"),
        "monitors": [],
    },
    {
        "slug": "delta",
        "device": dict(device_name="Samsung-Galaxy-S24", platform="Android", device_type="Smartphone",
                       model="Galaxy S24", manufacturer="Samsung Electronics",
                       serial_number="SAM-S24-DELTA-001", udid="F60100160017001800190020",
                       os_version="Android 14", architecture="arm64",
                       owner="user@delta.com", enrollment_method="MDM Profile", status="Enrolled"),
        "network": dict(ip_address="172.16.0.25", mac_address="DD:EE:FF:00:11:01",
                        hostname="galaxy-s24.local", wifi_ssid="Delta-WiFi",
                        connection_type="Wi-Fi", dns_server="172.16.0.1",
                        default_gateway="172.16.0.1"),
        "monitors": [],
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        from sqlalchemy import select, text
        result = await db.execute(select(Customer).limit(1))
        if result.scalar_one_or_none():
            print("✅  Database already seeded, skipping.")
            return

        # Create customers
        customer_map: dict[str, Customer] = {}
        for cdata in CUSTOMERS_DATA:
            c = Customer(name=cdata["name"], slug=cdata["slug"])
            db.add(c)
            customer_map[cdata["slug"]] = c
        await db.flush()

        # Create tokens
        for c in customer_map.values():
            db.add(EnrollmentToken(customer_id=c.id, token=tok()))

        # Create devices
        for entry in DEVICES_DATA:
            customer = customer_map[entry["slug"]]
            device = Device(customer_id=customer.id, **entry["device"])
            db.add(device)
            await db.flush()

            db.add(NetworkInfo(device_id=device.id, **entry["network"]))
            for mon in entry["monitors"]:
                db.add(MonitorInfo(device_id=device.id, **mon))

        await db.commit()
        print("✅  Database seeded successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
