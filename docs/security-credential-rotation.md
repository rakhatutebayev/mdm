# Credential rotation after exposure

If any password, API token, or SSH key was shared in chat, email, or tickets, treat it as compromised.

## Immediate actions

1. **SSH**: On each affected server, set a new strong password *or* disable password auth and use `authorized_keys` only (`PasswordAuthentication no` in `sshd_config` after keys work).
2. **GitHub**: Revoke PATs that appeared in remotes or logs; rotate deploy keys if needed.
3. **Application**: Rotate `POSTGRES_PASSWORD`, enrollment tokens, and agent `auth_token` rows if you suspect replay (re-enroll agents if required).
4. **Inventory**: Search server `~/.bash_history` and CI logs for pasted secrets.

## Ongoing

- Use **SSH keys** for `root@portal` and agent hosts; store keys in a password manager.
- Keep production `.env` **only on the server** (not in git).
- Prefer **GitHub Actions secrets** for `SERVER_HOST`, `SERVER_USER`, `DEPLOY_KEY`.

See also [deployment-runbook.md](./deployment-runbook.md).
