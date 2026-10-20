"""Signing in with Hardcover: OAuth authorization code flow with PKCE.

https://docs.hardcover.app/api/oauth/
"""
import asyncio
import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import httpx

from .api import AuthError, HardcoverError

log = logging.getLogger(__name__)

DISCOVERY_URL = "https://api.hardcover.app/.well-known/oauth-authorization-server"
ISSUER = "https://api.hardcover.app"

# Profile basics, plus public and followers-only library entries. Private entries are
# deliberately out of reach: a wrap-up is for sharing.
SCOPES = ["read:me:content", "read:library:public", "read:library:following"]


class Provider:
    """Hardcover's OAuth endpoints, read from its discovery document on first use."""

    def __init__(self, client, client_id, client_secret, redirect_uri):
        self.client = client
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._metadata = None
        self._lock = asyncio.Lock()

    async def metadata(self):
        async with self._lock:
            if self._metadata is None:
                try:
                    resp = await self.client.get(DISCOVERY_URL)
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    raise HardcoverError(f"Couldn't reach Hardcover's sign-in service: {e}") from e
                metadata = resp.json()
                if metadata.get("issuer") != ISSUER:
                    raise HardcoverError("Unexpected issuer in Hardcover's discovery document")
                self._metadata = metadata
        return self._metadata

    async def authorization_url(self, state, code_verifier):
        endpoint = (await self.metadata())["authorization_endpoint"]
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{endpoint}?{urlencode(params)}"

    async def exchange_code(self, code, code_verifier):
        """Trade the authorization code for tokens; returns Hardcover's token response."""
        endpoint = (await self.metadata())["token_endpoint"]
        try:
            resp = await self.client.post(endpoint, auth=(self.client_id, self.client_secret), data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            })
        except httpx.HTTPError as e:
            raise HardcoverError(f"Couldn't reach Hardcover's sign-in service: {e}") from e
        if resp.status_code == 400:
            # invalid_grant and friends: an expired, reused or tampered code
            raise AuthError("Hardcover didn't accept the sign-in; please try again.")
        if resp.status_code != 200:
            # e.g. 401 invalid_client: our client ID or secret is wrong
            raise HardcoverError(f"HTTP {resp.status_code} from Hardcover's token endpoint "
                                 f"({error_code(resp)})")
        tokens = resp.json()
        if not tokens.get("access_token"):
            raise HardcoverError("Hardcover's token response had no access token")
        return tokens

    async def revoke(self, token, hint):
        """Ask Hardcover to cancel a token. Best effort: failures are only logged."""
        try:
            endpoint = (await self.metadata())["revocation_endpoint"]
            resp = await self.client.post(endpoint, auth=(self.client_id, self.client_secret),
                                          data={"token": token, "token_type_hint": hint})
            if resp.status_code != 200:
                log.warning("revoking %s failed: HTTP %s", hint, resp.status_code)
        except (httpx.HTTPError, HardcoverError, KeyError) as e:
            log.warning("revoking %s failed: %s", hint, e)


def error_code(resp):
    """The OAuth `error` field of a failed response (never contains secrets)."""
    try:
        return str(resp.json().get("error", "no error code"))[:100]
    except ValueError:
        return "no error code"


def new_state():
    return secrets.token_urlsafe(32)


def new_code_verifier():
    return secrets.token_urlsafe(64)


def code_challenge(code_verifier):
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
