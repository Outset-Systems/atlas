# Atlas

A self-hosted map of your homelab: hosts, services, networks, racks,
certificates and scheduled jobs on one illustrated map, with live health from
Prometheus, Loki and Uptime Kuma.

**Status:** pre-release. The full README, install guide and configuration
reference are being written.

## Quickstart

```bash
docker build -t atlas .
docker run -d --name atlas -p 127.0.0.1:5006:5006 -v atlas-data:/data atlas
```

Then open http://127.0.0.1:5006.

## License

MIT — see [LICENSE](LICENSE).
