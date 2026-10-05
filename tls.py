"""TLS 1.3 pour le Hub : certificat auto-signé généré au premier lancement, épinglé (pinning) côté client."""
import datetime, hashlib, ipaddress, os, socket, ssl


def local_ips():
    ips = {"127.0.0.1"}
    try:
        ips.update(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.add(s.getsockname()[0]); s.close()
    except OSError:
        pass
    return sorted(ips)


def ensure_cert(folder):
    """Crée (si absent) cert.pem / key.pem (ECDSA P-256, validité 10 ans, SAN = IP locales). Retourne les chemins."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    os.makedirs(folder, exist_ok=True)
    cert_p, key_p = os.path.join(folder, "hub_cert.pem"), os.path.join(folder, "hub_key.pem")
    if os.path.exists(cert_p) and os.path.exists(key_p):
        return cert_p, key_p
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Smart DEM Hub")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in local_ips()]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    fd = os.open(key_p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(cert_p, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, key_p


def server_context(cert_p, key_p):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert_p, key_p)
    return ctx


def client_context(pem):
    """Contexte client : TLS 1.3 minimum ; seul le certificat épinglé (PEM enregistré) est accepté."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata=pem)
    if hasattr(ssl, "VERIFY_X509_PARTIAL_CHAIN"):
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def fetch_cert(host, port):
    return ssl.get_server_certificate((host, port))


def fingerprint(pem):
    return ":".join(f"{b:02X}" for b in hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest())
