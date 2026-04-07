"""
Simple encryption service for sensitive config values.

Uses Fernet (symmetric encryption) with a key from environment.
For production, consider using AWS KMS or HashiCorp Vault.
"""

import base64
import os

from cryptography.fernet import Fernet


class Encryptor:
    """Encrypts and decrypts sensitive values using Fernet symmetric encryption."""

    def __init__(self):
        """Initialize encryptor with key from environment or static dev key."""
        import base64

        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            # For development/testing only: use a static fallback key
            # In production, ENCRYPTION_KEY must be set or service should fail
            print(
                "WARNING: ENCRYPTION_KEY not set, using static development key. DO NOT USE IN PRODUCTION!"
            )
            # Generate a consistent Fernet key for development
            dev_key = "dev-key-for-testing-only-do-not-use-in-production-12345678"
            key = base64.urlsafe_b64encode(dev_key[:32].ljust(32).encode()).decode()

        self.fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return ""
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string.

        Args:
            ciphertext: The base64-encoded encrypted string

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""
        return self.fernet.decrypt(ciphertext.encode()).decode()


# Global instance
_encryptor = None


def get_encryptor() -> Encryptor:
    """Get or create the global encryptor instance."""
    global _encryptor
    if _encryptor is None:
        _encryptor = Encryptor()
    return _encryptor
