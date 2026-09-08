#!/usr/bin/env bash
# Run as root on the dedicated Ubuntu 24.04 control host.
set -euo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo 'Root required' >&2; exit 1; }
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Ubuntu 24.04 required' >&2; exit 1; }
control_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$control_dir/../harden.sh"
install -d -m 0755 /srv/small-cloud /etc/postgresql-common
install -d -m 0700 /srv/small-cloud/source /srv/small-cloud/secrets /srv/small-cloud/logs /etc/small-cloud
# Do not create a second cluster on the system-default path during package install.
printf 'create_main_cluster = false\n' > /etc/postgresql-common/createcluster.conf
export DEBIAN_FRONTEND=noninteractive
# Package post-install hooks must not expose an unconfigured registry or gateway.
systemctl mask --runtime caddy.service docker-registry.service postgresql.service postgresql@16-main.service
apt-get update -qq
apt-get install -y -qq postgresql-16 caddy docker-registry age openssl skopeo
install -d -o postgres -g postgres -m 0700 /srv/small-cloud/postgresql
if [[ ! -f /etc/postgresql/16/main/postgresql.conf ]]; then
  pg_createcluster 16 main --datadir /srv/small-cloud/postgresql
fi
install -d -o postgres -g postgres -m 0755 /etc/postgresql/16/main/conf.d
pg_conftool 16 main set include_dir conf.d
if [[ ! -f /etc/small-cloud/database.key ]]; then
  openssl req -x509 -newkey rsa:3072 -nodes -days 365 -subj '/CN=Small Cloud database' \
    -addext 'subjectAltName=IP:10.42.0.2' -addext 'basicConstraints=critical,CA:TRUE' \
    -keyout /etc/small-cloud/database.key -out /etc/small-cloud/database-ca.crt 2>/dev/null
fi
chown postgres:postgres /etc/small-cloud/database.key
chmod 0600 /etc/small-cloud/database.key
chmod 0755 /etc/small-cloud
chmod 0644 /etc/small-cloud/database-ca.crt
cat > /etc/postgresql/16/main/conf.d/small-cloud.conf <<'EOF'
listen_addresses = '127.0.0.1,10.42.0.2'
password_encryption = 'scram-sha-256'
ssl = on
ssl_cert_file = '/etc/small-cloud/database-ca.crt'
ssl_key_file = '/etc/small-cloud/database.key'
max_connections = 100
shared_buffers = '256MB'
log_statement = 'none'
log_min_error_statement = 'panic'
EOF
cat > /etc/postgresql/16/main/pg_hba.conf <<'EOF'
local all postgres peer
hostssl all all 10.42.0.3/32 scram-sha-256
hostssl all all 127.0.0.1/32 scram-sha-256
host all all 0.0.0.0/0 reject
host all all ::/0 reject
EOF
chown postgres:postgres /etc/postgresql/16/main/conf.d/small-cloud.conf /etc/postgresql/16/main/pg_hba.conf
systemctl unmask --runtime postgresql.service postgresql@16-main.service
systemctl enable postgresql
systemctl restart postgresql@16-main
runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 --dbname postgres <<'EOF'
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
REVOKE ALL ON DATABASE template1 FROM PUBLIC;
REVOKE ALL ON DATABASE template0 FROM PUBLIC;
EOF
if [[ ! -f /srv/small-cloud/secrets/identity.age ]]; then
  age-keygen -o /srv/small-cloud/secrets/identity.age 2>/dev/null
fi
install -m 0755 "$control_dir/tool_database.py" /usr/local/sbin/small-cloud-tool-database
install -d -o docker-registry -g docker-registry -m 0700 /srv/small-cloud/registry
cat > /etc/docker/registry/config.yml <<'EOF'
version: 0.1
log:
  level: warn
storage:
  maintenance:
    uploadpurging:
      enabled: true
      age: 23h
      interval: 1h
      dryrun: false
  filesystem:
    rootdirectory: /srv/small-cloud/registry
  delete:
    enabled: true
http:
  addr: 127.0.0.1:5000
EOF
chown root:docker-registry /etc/docker/registry/config.yml
chmod 0640 /etc/docker/registry/config.yml
install -d -m 0755 /etc/systemd/system/docker-registry.service.d
cat > /etc/systemd/system/docker-registry.service.d/storage.conf <<'EOF'
[Service]
ReadWritePaths=/srv/small-cloud/registry
EOF
cat > /etc/caddy/Caddyfile <<'EOF'
{
    admin off
    email monkeyseesone@gmail.com
}
small-cloud.monkeysees.one {
    header Cache-Control "no-store"
    respond "Small Cloud is not accepting workloads. Authentication and deployment are not enabled." 503
}
EOF
chmod 0644 /etc/caddy/Caddyfile
# Persist certificates; the Ubuntu service uses /var/lib/caddy as HOME.
install -d -o caddy -g caddy -m 0700 /srv/small-cloud/caddy
install -d -m 0755 /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/storage.conf <<'EOF'
[Service]
Environment=XDG_DATA_HOME=/srv/small-cloud/caddy
ReadWritePaths=/srv/small-cloud/caddy
EOF
install -d -m 0755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/small-cloud.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=256M
RuntimeMaxUse=64M
MaxRetentionSec=7day
EOF
cat > /etc/logrotate.d/postgresql-common <<'EOF'
/var/log/postgresql/*.log {
    daily
    rotate 7
    maxsize 10M
    missingok
    notifempty
    compress
    copytruncate
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl unmask --runtime caddy.service docker-registry.service
systemctl enable caddy docker-registry
systemctl restart caddy docker-registry systemd-journald
printf 'Control services configured; workload admission remains closed.\n'
