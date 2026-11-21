# VPS Deployment Guide

Run the single-account Compose deployment on the VPS and reach its loopback API through an SSH tunnel. The API key is required for protected routes through the tunnel.

## On the VPS

1. Install Docker Engine 28 or later with the Compose and Buildx plugins. Use a non-root deployment user with authorized Docker access.
2. Place the repository in a directory owned by the deployment user. Follow the [Docker guide](docker.md) there to provision one account file, set the local proxy API key, build the image, and start the service.
3. Restrict inbound SSH at the provider and host firewalls to your intended client networks. Keep ports 8741 and 443 closed in both firewalls for this setup.
4. Confirm the API is bound to the VPS loopback address.

   ```bash
   docker compose -f docker-compose.example.yml port zerogravity 8741
   curl -fsS http://127.0.0.1:8741/health
   ```

   The port command should print `127.0.0.1:8741`. The health endpoint reports that the process is running.

## From the client machine

In a terminal, open an SSH tunnel using your VPS user and hostname.

```bash
ssh -NT -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:8741:127.0.0.1:8741 deploy@vps.example.com
```

In a second terminal, check the tunneled endpoint.

```bash
curl -fsS http://127.0.0.1:8741/health
```

Configure Claude Code with `http://127.0.0.1:8741` and the API key from the VPS. Keep the SSH terminal open while using the client. If port 8741 is already in use on the client machine, change the first port in `-L` and use that port in the client URL. [Claude Code configuration](clients.md#claude-code)
