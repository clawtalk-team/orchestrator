"""
Simple encryption service for sensitive config values.

Uses Fernet (symmetric encryption) with a key from environment.
For production, consider using AWS KMS or HashiCorp Vault.
"""

import os
import base64
from cryptography.fernet import Fernet


class Encryptor:
    """Encrypts and decrypts sensitive values using Fernet symmetric encryption."""

    def __init__(self):
        """Initialize encryptor with key from environment or generate one."""
        key = os.getenv("ENCRYPTION_KEY")
        if not key:
            # For development/testing, generate a key
            # In production, this should come from secure storage (KMS, Vault, etc.)
            key = Fernet.generate_key().decode()
            print(f"WARNING: Generated encryption key (not for production): {key}")

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
