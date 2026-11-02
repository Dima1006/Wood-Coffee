"""Pure helpers with no web-framework imports (easy to test)."""
import hashlib
import hmac
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_SCRYPT = dict(n=2**14, r=8, p=1)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(calc.hex(), digest)


def slugify(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "venue"


def format_zl(grosze: int) -> str:
    return f"{grosze // 100},{grosze % 100:02d} zł"


# "Small 6.50", "Latte 0.5l 12,00 zł", or just "5.00"
_PRICE_LINE = re.compile(r"^(.*?)[\s:=]*(\d+(?:[.,]\d{1,2})?)\s*(?:zł|zl|pln)?$", re.I)


def parse_prices(text: str) -> list[tuple[str, int]]:
    """Parse one 'label price' pair per line into [(label, grosze)]."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Add at least one price.")
    if len(lines) > 10:
        raise ValueError("At most 10 sizes per item.")
    result = []
    for line in lines:
        match = _PRICE_LINE.match(line)
        if not match:
            raise ValueError(f"Can't read the price in: “{line}”. Use e.g. “Small 6.50”.")
        label = match.group(1).strip()[:40]
        try:
            grosze = int(Decimal(match.group(2).replace(",", ".")) * 100)
        except InvalidOperation:
            raise ValueError(f"Invalid price in: “{line}”.")
        if not 0 < grosze <= 100_000:
            raise ValueError(f"Price out of range in: “{line}”.")
        result.append((label, grosze))
    if len(result) > 1 and any(not label for label, _ in result):
        raise ValueError("When there are several prices, give each one a name (e.g. “Small 6.50”).")
    return result


def prices_to_text(variants) -> str:
    return "\n".join(
        f"{v['label']} {v['price'] // 100}.{v['price'] % 100:02d}".strip() for v in variants
    )
