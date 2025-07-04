"""Authentication utility functions (JWT encode/decode/etc.)."""

import logging
from datetime import datetime, timedelta, timezone

from config import get_secret
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

logger = logging.getLogger(__name__)

security = HTTPBearer()

# Load token settings from environment/config
ALGORITHM = get_secret("ALGORITHM")
SECRET_KEY = get_secret("SECRET_KEY")
TOKEN_GRACE_PERIOD_MINUTES = get_secret("TOKEN_GRACE_PERIOD_MINUTES")
TOKEN_EXPIRE_MINUTES = get_secret("TOKEN_EXPIRE_MINUTES")


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    """Verify the validity of a JWT token including a grace period.

    Args:
        credentials (HTTPAuthorizationCredentials): Token provided in the Authorization header.

    Returns:
        dict: The decoded JWT payload if valid.

    Raises:
        HTTPException: If the token is invalid or expired.
    """
    try:
        token = credentials.credentials
        payload = decode_token(token)
        current_time = datetime.now(timezone.utc)
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        # Allow for a grace period after token expiration
        if current_time <= exp_time + timedelta(
            minutes=int(TOKEN_GRACE_PERIOD_MINUTES),
        ):
            return payload

        raise HTTPException(
            status_code=401,
            detail="Verify Token has expired",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_token(data: dict):
    """Create a new JWT token using the provided payload.

    Args:
        data (dict): Payload data to include in the token.

    Returns:
        str: Encoded JWT token.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=int(TOKEN_EXPIRE_MINUTES),
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str):
    """Decode and verify a JWT token.

    Args:
        token (str): The JWT token to decode.

    Returns:
        dict: Decoded token payload.

    Raises:
        HTTPException: If the token is invalid, expired, or has invalid claims.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Decode Token has expired")
    except jwt.JWTClaimsError:
        raise HTTPException(
            status_code=401,
            detail="Decode Invalid token claims",
        )
    except jwt.JWTError as e:
        if "Signature verification failed" in str(e):
            raise HTTPException(
                status_code=401,
                detail="Decode Invalid token signature",
            )
        if "Invalid audience" in str(e):
            raise HTTPException(
                status_code=401,
                detail="Decode Invalid token audience",
            )
        if "Invalid issuer" in str(e):
            raise HTTPException(
                status_code=401,
                detail="Decode Invalid token issuer",
            )
        logger.info(f"Unexpected JWT error: {e!s}")
        raise HTTPException(
            status_code=401,
            detail="Decode Invalid authentication credentials",
        )


def renew_token(current_token: str):
    """Renew an existing token if it is nearing expiration.

    Args:
        current_token (str): The token to renew.

    Returns:
        dict: A dictionary with the new token and renewal status.

    Raises:
        HTTPException: If the token has already expired or is otherwise invalid.

    """
    try:
        payload = decode_token(current_token)
        current_time = datetime.now(timezone.utc)
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        if current_time > exp_time:
            raise HTTPException(
                status_code=401,
                detail="Renew Token has expired",
            )

        # If the token is within the grace period, issue a new one
        if (exp_time - current_time) < timedelta(
            minutes=int(TOKEN_GRACE_PERIOD_MINUTES),
        ):
            new_token = create_token(data={"sub": "user-UI"})
            logger.info(f"Token renewed for user {payload.get('sub')}")
            return {"token": new_token, "renewed": True}

        # Otherwise, return the existing token
        return {"token": current_token, "renewed": False}
    except JWTError:
        raise HTTPException(status_code=401, detail="Renew Invalid token")
