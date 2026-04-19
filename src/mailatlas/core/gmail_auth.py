from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Protocol


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class GmailAuthConfig:
    client_id: str
    client_secret: str | None = None
    email: str | None = None
    scopes: tuple[str, ...] = (GMAIL_SEND_SCOPE,)
    token_url: str = GOOGLE_TOKEN_URL
    auth_url: str = GOOGLE_AUTH_URL
    timeout_seconds: int = 300


@dataclass(frozen=True)
class GmailAuthResult:
    status: str
    store_path: str
    store_type: str
    email: str | None
    scopes: tuple[str, ...]
    expires_at: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": "gmail",
            "store_type": self.store_type,
            "store_path": self.store_path,
            "email": self.email,
            "scopes": list(self.scopes),
            "expires_at": self.expires_at,
        }


class TokenStore(Protocol):
    store_type: str
    store_path: str

    def load(self) -> dict[str, Any] | None:
        ...

    def save(self, token: dict[str, Any]) -> None:
        ...

    def delete(self) -> bool:
        ...


class FileTokenStore:
    store_type = "file"

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path else default_gmail_token_path()

    @property
    def store_path(self) -> str:
        return self.path.as_posix()

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, token: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(json.dumps(token, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temp_path.replace(self.path)
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def delete(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True


class KeyringTokenStore:
    store_type = "keychain"
    service_name = "MailAtlas Gmail OAuth"
    username = "default"

    @property
    def store_path(self) -> str:
        return f"keyring://{self.service_name}/{self.username}"

    @staticmethod
    def _keyring_module():
        try:
            import keyring  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "Gmail keychain storage requires the optional keyring dependency. "
                "Install with: python -m pip install 'mailatlas[keychain]'"
            ) from error
        return keyring

    @classmethod
    def is_available(cls) -> bool:
        try:
            cls._keyring_module()
        except RuntimeError:
            return False
        return True

    def load(self) -> dict[str, Any] | None:
        raw_token = self._keyring_module().get_password(self.service_name, self.username)
        if not raw_token:
            return None
        return json.loads(raw_token)

    def save(self, token: dict[str, Any]) -> None:
        self._keyring_module().set_password(
            self.service_name,
            self.username,
            json.dumps(token, indent=2, sort_keys=True),
        )

    def delete(self) -> bool:
        keyring = self._keyring_module()
        try:
            keyring.delete_password(self.service_name, self.username)
        except Exception as error:
            if error.__class__.__name__ == "PasswordDeleteError":
                return False
            raise
        return True


def create_gmail_token_store(
    path: str | Path | None = None,
    *,
    token_store: str | None = None,
) -> TokenStore:
    if path:
        return FileTokenStore(path)

    env_token_store = os.environ.get("MAILATLAS_GMAIL_TOKEN_STORE")
    env_token_file = os.environ.get("MAILATLAS_GMAIL_TOKEN_FILE")
    if env_token_file and token_store is None and env_token_store is None:
        return FileTokenStore(env_token_file)

    mode = (token_store or env_token_store or "auto").strip()
    normalized_mode = mode.lower()

    if normalized_mode in {"auto", ""}:
        if KeyringTokenStore.is_available():
            return KeyringTokenStore()
        return FileTokenStore()
    if normalized_mode in {"keychain", "keyring"}:
        store = KeyringTokenStore()
        store._keyring_module()
        return store
    if normalized_mode == "file":
        return FileTokenStore()

    return FileTokenStore(mode)


class _OAuthCallbackServer(HTTPServer):
    oauth_query: dict[str, list[str]] | None = None


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        self.server.oauth_query = urllib.parse.parse_qs(parsed.query)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"MailAtlas Gmail auth complete. You can close this browser tab.")

    def log_message(self, format: str, *args: object) -> None:
        return


def default_gmail_token_path() -> Path:
    override = os.environ.get("MAILATLAS_GMAIL_TOKEN_FILE")
    if override:
        return Path(override).expanduser().resolve()

    config_home = os.environ.get("MAILATLAS_CONFIG_HOME")
    if config_home:
        return (Path(config_home).expanduser() / "gmail-token.json").resolve()

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return (Path(xdg_config_home).expanduser() / "mailatlas" / "gmail-token.json").resolve()

    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "MailAtlas" / "gmail-token.json").resolve()

    return (Path.home() / ".config" / "mailatlas" / "gmail-token.json").resolve()


def _token_scopes(token: dict[str, Any]) -> tuple[str, ...]:
    raw_scopes = token.get("scope") or token.get("scopes") or GMAIL_SEND_SCOPE
    if isinstance(raw_scopes, str):
        return tuple(scope for scope in raw_scopes.split() if scope)
    if isinstance(raw_scopes, list):
        return tuple(str(scope) for scope in raw_scopes if scope)
    return (GMAIL_SEND_SCOPE,)


def _with_expiration(payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    token = dict(existing or {})
    token.update(payload)
    expires_in = payload.get("expires_in")
    if expires_in is not None:
        try:
            token["expires_at"] = time.time() + int(expires_in)
        except (TypeError, ValueError):
            token["expires_at"] = None
    return token


def _post_form(url: str, values: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            payload = json.loads(response_body) if response_body else {}
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(response_body) if response_body else {}
        except json.JSONDecodeError:
            payload = {"error": response_body or str(error)}
        message = payload.get("error_description") or payload.get("error") or str(error)
        raise ValueError(f"Gmail OAuth token request failed: {message}") from error

    if not isinstance(payload, dict):
        raise ValueError("Gmail OAuth token response was not a JSON object.")
    if "error" in payload:
        message = payload.get("error_description") or payload.get("error")
        raise ValueError(f"Gmail OAuth token request failed: {message}")
    return payload


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _authorization_url(
    config: GmailAuthConfig,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    values = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    if config.email:
        values["login_hint"] = config.email
    return f"{config.auth_url}?{urllib.parse.urlencode(values)}"


def exchange_gmail_authorization_code(
    config: GmailAuthConfig,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    values = {
        "client_id": config.client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if config.client_secret:
        values["client_secret"] = config.client_secret

    payload = _post_form(config.token_url, values)
    token = _with_expiration(payload)
    token["client_id"] = config.client_id
    if config.client_secret:
        token["client_secret"] = config.client_secret
    if config.email:
        token["email"] = config.email
    return token


def refresh_gmail_token(token: dict[str, Any], *, token_url: str = GOOGLE_TOKEN_URL) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    client_id = token.get("client_id")
    if not refresh_token or not client_id:
        raise ValueError("Stored Gmail auth is missing a refresh token or client id. Run 'mailatlas auth gmail' again.")

    values = {
        "client_id": str(client_id),
        "grant_type": "refresh_token",
        "refresh_token": str(refresh_token),
    }
    if token.get("client_secret"):
        values["client_secret"] = str(token["client_secret"])

    payload = _post_form(token_url, values)
    return _with_expiration(payload, existing=token)


def run_gmail_auth_flow(
    config: GmailAuthConfig,
    *,
    store: TokenStore | None = None,
    open_browser: bool = True,
    notify: Callable[[str], None] | None = None,
    browser_open: Callable[[str], bool] = webbrowser.open,
) -> GmailAuthResult:
    store = store or create_gmail_token_store()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    server = _OAuthCallbackServer(("127.0.0.1", 0), _OAuthCallbackHandler)
    server.timeout = config.timeout_seconds
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        auth_url = _authorization_url(config, redirect_uri=redirect_uri, state=state, code_challenge=challenge)
        if notify:
            notify(auth_url)
        if open_browser:
            browser_open(auth_url)
        server.handle_request()
        query = server.oauth_query
    finally:
        server.server_close()

    if not query:
        raise TimeoutError("Timed out waiting for Gmail OAuth callback.")
    if query.get("state", [""])[0] != state:
        raise ValueError("Gmail OAuth callback state did not match.")
    if query.get("error"):
        raise ValueError(f"Gmail OAuth failed: {query['error'][0]}")
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("Gmail OAuth callback did not include an authorization code.")

    token = exchange_gmail_authorization_code(config, code=code, redirect_uri=redirect_uri, code_verifier=verifier)
    store.save(token)
    return token_status(token, store=store, authenticated_status="ok")


def load_valid_gmail_access_token(*, store: TokenStore | None = None) -> str:
    store = store or create_gmail_token_store()
    token = store.load()
    if not token:
        raise ValueError("Gmail auth is not configured. Run 'mailatlas auth gmail' or set MAILATLAS_GMAIL_ACCESS_TOKEN.")

    expires_at = token.get("expires_at")
    if token.get("access_token") and isinstance(expires_at, (int, float)) and float(expires_at) > time.time() + 60:
        return str(token["access_token"])

    refreshed = refresh_gmail_token(token)
    store.save(refreshed)
    return str(refreshed["access_token"])


def token_status(
    token: dict[str, Any] | None,
    *,
    store: TokenStore | None = None,
    authenticated_status: str = "configured",
) -> GmailAuthResult:
    store = store or create_gmail_token_store()
    if not token:
        return GmailAuthResult(
            status="not_configured",
            store_path=store.store_path,
            store_type=store.store_type,
            email=None,
            scopes=(),
            expires_at=None,
        )
    return GmailAuthResult(
        status=authenticated_status,
        store_path=store.store_path,
        store_type=store.store_type,
        email=str(token["email"]) if token.get("email") else None,
        scopes=_token_scopes(token),
        expires_at=float(token["expires_at"]) if isinstance(token.get("expires_at"), (int, float)) else None,
    )


def gmail_auth_status(*, store: TokenStore | None = None) -> GmailAuthResult:
    store = store or create_gmail_token_store()
    return token_status(store.load(), store=store)


def gmail_auth_logout(*, store: TokenStore | None = None) -> GmailAuthResult:
    store = store or create_gmail_token_store()
    deleted = store.delete()
    return GmailAuthResult(
        status="removed" if deleted else "not_configured",
        store_path=store.store_path,
        store_type=store.store_type,
        email=None,
        scopes=(),
        expires_at=None,
    )
