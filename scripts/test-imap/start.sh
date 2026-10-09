#!/usr/bin/env bash
# Startet einen lokalen Dovecot-IMAPS-Testserver mit eigener Test-CA.
# NUR für automatische Tests – enthält ein Testpostfach mit festem Testpasswort.
#
# Voraussetzungen: dovecot-imapd, openssl, Root-Rechte (für /etc/hosts und Dovecot).
# Ergebnis: imap.quitly.test:10993, Benutzer "test@quitly.test", Passwort "test-passwort-123".
# Die CA liegt danach in $DIR/ca.pem (für QUITLY_IMAP_CA_FILE).
set -euo pipefail

DIR="${QUITLY_TEST_IMAP_DIR:-/tmp/quitly-test-imap}"
HOST="imap.quitly.test"
PORT="${QUITLY_TEST_IMAP_PORT:-10993}"

mkdir -p "$DIR"/{mail,run,home}
cd "$DIR"

if [ ! -f ca.pem ]; then
  # Strenge X.509-Prüfung (Python ≥ 3.13) verlangt keyUsage/Key-Identifier
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=Quitly Test CA" \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" -keyout ca.key -out ca.pem 2>/dev/null
  openssl req -newkey rsa:2048 -nodes -subj "/CN=$HOST" -keyout server.key -out server.csr 2>/dev/null
  printf "subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\nauthorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n" "$HOST" > ext.cnf
  openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 30 \
    -extfile ext.cnf -out server.pem 2>/dev/null
  # Zweites Zertifikat für einen falschen Hostnamen (Test: Hostname-Prüfung)
  openssl req -newkey rsa:2048 -nodes -subj "/CN=falsch.quitly.test" -keyout wrong.key -out wrong.csr 2>/dev/null
  printf "subjectAltName=DNS:falsch.quitly.test\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\nauthorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n" > wrong.cnf
  openssl x509 -req -in wrong.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 30 \
    -extfile wrong.cnf -out wrong.pem 2>/dev/null
fi

grep -q " $HOST\$" /etc/hosts || echo "127.0.0.1 $HOST" >> /etc/hosts
grep -q " falsch.quitly.test\$" /etc/hosts || echo "127.0.0.1 falsch.quitly.test" >> /etc/hosts

echo "test@quitly.test:{PLAIN}test-passwort-123::::::" > users
chown -R dovecot:dovecot mail home
chmod 640 users server.key && chgrp dovecot users server.key

cat > dovecot.conf <<EOF
base_dir = $DIR/run
state_dir = $DIR/run
log_path = $DIR/dovecot.log
protocols = imap
listen = ${QUITLY_TEST_IMAP_LISTEN:-127.0.0.1}
ssl = required
ssl_cert = <$DIR/server.pem
ssl_key = <$DIR/server.key
ssl_min_protocol = TLSv1.2
disable_plaintext_auth = yes
auth_mechanisms = plain
mail_location = maildir:$DIR/mail/%u
mail_uid = dovecot
mail_gid = dovecot
first_valid_uid = 1
passdb {
  driver = passwd-file
  args = scheme=PLAIN username_format=%u $DIR/users
}
userdb {
  driver = static
  args = uid=dovecot gid=dovecot home=$DIR/home/%u
}
namespace inbox {
  inbox = yes
  separator = /
  mailbox Trash {
    special_use = \\Trash
    auto = subscribe
  }
  mailbox Sent {
    special_use = \\Sent
    auto = subscribe
  }
  mailbox Junk {
    special_use = \\Junk
    auto = subscribe
  }
}
service imap-login {
  inet_listener imap {
    port = 0
  }
  inet_listener imaps {
    port = $PORT
    ssl = yes
  }
}
service anvil {
  chroot =
}
service imap-login {
  chroot =
}
EOF

dovecot -c "$DIR/dovecot.conf" stop 2>/dev/null || true
sleep 0.5
dovecot -c "$DIR/dovecot.conf" </dev/null >/dev/null 2>&1
for _ in $(seq 1 20); do
  if (echo > /dev/tcp/127.0.0.1/"$PORT") 2>/dev/null; then
    echo "Dovecot läuft auf $HOST:$PORT (CA: $DIR/ca.pem)"
    exit 0
  fi
  sleep 0.3
done
echo "Dovecot startet nicht – siehe $DIR/dovecot.log" >&2
exit 1
