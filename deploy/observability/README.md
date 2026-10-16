# Local observability deployment

Grafana has no default password. Before starting this stack, supply
GRAFANA_ADMIN_PASSWORD_FILE pointing to a private file outside the repository
containing a unique high-entropy password. Compose refuses to start without it;
the file is mounted as a Docker secret and read through Grafana's file setting.
Do not put its contents in a compose file, command line, or source control.

Published monitoring ports bind only to 127.0.0.1. Production exposure requires
an independently configured authenticated TLS proxy and access controls. Do not
change these bindings to all interfaces as a substitute for that configuration.
An existing Grafana data volume retains its existing admin credentials; changing
the bootstrap secret does not rotate an already initialized administrator account.
Any such rotation is an explicit operator task.
