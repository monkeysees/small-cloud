"""Google authorization-code exchange; provider tokens never leave this boundary."""
import base64
import hashlib
import json
import urllib.request
import urllib.parse
import urllib.error

import jwt
from .common import Failure


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Failure('NETWORK_ERROR', 'Unexpected HTTP redirect was refused.', 503)


class Google:
    def __init__(self, client_id, client_secret, *,
                 authorization_endpoint='https://accounts.google.com/o/oauth2/v2/auth',
                 token_endpoint='https://oauth2.googleapis.com/token',
                 jwks_uri='https://www.googleapis.com/oauth2/v3/certs', opener=None):
        self.client_id, self.client_secret = client_id, client_secret
        self.authorization_endpoint, self.token_endpoint, self.jwks_uri = authorization_endpoint, token_endpoint, jwks_uri
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def authorization_url(self, redirect_uri, state, nonce, pkce):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(pkce.encode()).digest()).rstrip(b'=').decode()
        return self.authorization_endpoint + '?' + urllib.parse.urlencode({
            'client_id': self.client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
            'scope': 'openid email profile', 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'prompt': 'select_account'})

    def fetch(self, request):
        with self.opener.open(request, timeout=30) as response:
            body = response.read(262145)
            if len(body) > 262144:
                raise ValueError('Oversized provider response')
            return json.loads(body)

    def exchange(self, code, redirect_uri, nonce, pkce):
        try:
            result = self.fetch(urllib.request.Request(self.token_endpoint, urllib.parse.urlencode({
                'code': code, 'client_id': self.client_id, 'client_secret': self.client_secret,
                'redirect_uri': redirect_uri, 'grant_type': 'authorization_code', 'code_verifier': pkce}).encode()))
            token = result['id_token']
            header = jwt.get_unverified_header(token)
            if header['alg'] != 'RS256':
                raise ValueError('Unsupported signature')
            keys = self.fetch(self.jwks_uri)['keys']
            key = next(key for key in keys if key.get('kid') == header.get('kid') and key.get('kty') == 'RSA')
            claims = jwt.decode(token, jwt.PyJWK(key, algorithm='RS256').key,
                                algorithms=['RS256'], audience=self.client_id,
                                issuer=['https://accounts.google.com', 'accounts.google.com'],
                                options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce', 'email']})
            if (claims['nonce'] != nonce or claims.get('email_verified') is not True
                    or not isinstance(claims['sub'], str) or not claims['sub'] or len(claims['sub']) > 255
                    or claims.get('azp', self.client_id) != self.client_id
                    or not isinstance(claims.get('name', ''), str)):
                raise ValueError('Invalid identity claims')
            return {**claims, 'name': claims.get('name', '')[:500]}
        except (OSError, ValueError, KeyError, StopIteration, TypeError, jwt.PyJWTError):
            raise Failure('AUTH_REQUIRED', 'Google sign-in could not be verified; start again.', 401) from None
