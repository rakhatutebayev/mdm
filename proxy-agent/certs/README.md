# Bundled MDM trust anchor (root CA)

Place your **NOCKO / corporate root CA** (or full chain) in PEM format as:

```
mdm-ca.pem
```

in this directory **before** building a distribution or running `install.sh` from the source tree.

- `install.sh` copies `certs/mdm-ca.pem` → `/etc/nocko-agent/certs/mdm-ca.pem` when the file exists.
- The agent uses it for:
  - **HTTPS** to `mdm_url` (`httpx` verify)
  - **MQTT over TLS** (broker certificate verification)

If `mdm-ca.pem` is missing, the agent falls back to **system** certificate store (public PKI).

**Do not commit** production private roots to a public repo; use CI to inject `mdm-ca.pem` into the tarball, or ship via internal package mirror.
