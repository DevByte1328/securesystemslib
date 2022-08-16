"""Dead Simple Signing Envelope
"""

import logging
from typing import Any, Dict, List, Optional

from securesystemslib import exceptions, formats
from securesystemslib.serialization import (
    BaseDeserializer,
    BaseSerializer,
    JSONDeserializer,
    JSONSerializable,
    JSONSerializer,
    SerializationMixin,
)
from securesystemslib.signer import Key, Signature, Signer
from securesystemslib.util import b64dec, b64enc

logger = logging.getLogger(__name__)


class Envelope(SerializationMixin, JSONSerializable):
    """DSSE Envelope to provide interface for signing arbitrary data.

    Attributes:
        payload: Arbitrary byte sequence of serialized body.
        payload_type: string that identifies how to interpret payload.
        signatures: list of Signature.

    """

    def __init__(
        self, payload: bytes, payload_type: str, signatures: List[Signature]
    ):
        self.payload = payload
        self.payload_type = payload_type
        self.signatures = signatures

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Envelope):
            return False

        return (
            self.payload == other.payload
            and self.payload_type == other.payload_type
            and self.signatures == other.signatures
        )

    @staticmethod
    def _default_deserializer() -> BaseDeserializer:
        return JSONDeserializer()

    @staticmethod
    def _default_serializer() -> BaseSerializer:
        return JSONSerializer()

    @classmethod
    def from_dict(cls, data: dict) -> "Envelope":
        """Creates a DSSE Envelope from its JSON/dict representation.

        Arguments:
            data: A dict containing a valid payload, payloadType and signatures

        Raises:
            KeyError: If any of the "payload", "payloadType" and "signatures"
                fields are missing from the "data".

            FormatError: If signature in "signatures" is incorrect.

        Returns:
            A "Envelope" instance.
        """

        payload = b64dec(data["payload"])
        payload_type = data["payloadType"]

        formats.SIGNATURES_SCHEMA.check_match(data["signatures"])
        signatures = [
            Signature.from_dict(signature) for signature in data["signatures"]
        ]

        return cls(payload, payload_type, signatures)

    def to_dict(self) -> dict:
        """Returns the JSON-serializable dictionary representation of self."""

        return {
            "payload": b64enc(self.payload),
            "payloadType": self.payload_type,
            "signatures": [
                signature.to_dict() for signature in self.signatures
            ],
        }

    def pae(self) -> bytes:
        """Pre-Auth-Encoding byte sequence of self."""

        return b"DSSEv1 %d %b %d %b" % (
            len(self.payload_type),
            self.payload_type.encode("utf-8"),
            len(self.payload),
            self.payload,
        )

    def sign(self, signer: Signer) -> Signature:
        """Sign the payload and create the signature.

        Arguments:
            signer: A "Signer" class instance.

        Returns:
            A "Signature" instance.
        """

        signature = signer.sign(self.pae())
        self.signatures.append(signature)

        return signature

    def verify(self, keys: List[Key], threshold: int) -> Dict[str, Key]:
        """Verify the payload with the provided Keys.

        Arguments:
            keys: A list of public keys to verify the signatures.
            threshold: Number of signatures needed to pass the verification.

        Raises:
            ValueError: If "threshold" is not valid.
            SignatureVerificationError: If the enclosed signatures do not pass
                the verification.

        Note:
            Mandating keyid in signatures and matching them with keyid of Key
            in order to consider them for verification, is not a DSSE spec
            compliant (Issue #416).

        Returns:
            accepted_keys: A dict of unique public keys.
        """

        accepted_keys = {}
        pae = self.pae()

        # checks for threshold value.
        if threshold <= 0:
            raise ValueError("Threshold must be greater than 0")

        if len(keys) < threshold:
            raise ValueError("Number of keys can't be less than threshold")

        for signature in self.signatures:
            for key in keys:
                # If Signature keyid doesn't match with Key, skip.
                if not key.keyid == signature.keyid:
                    continue

                # If a key verifies the signature, we exit and use the result.
                try:
                    key.verify_signature(signature, pae)
                    accepted_keys[key.keyid] = key
                    break
                except exceptions.UnverifiedSignatureError:
                    # TODO: Log, Raise or continue with error?
                    continue

            # Break, if amount of recognized_signer are more than threshold.
            if len(accepted_keys) >= threshold:
                break

        if threshold > len(accepted_keys):
            raise exceptions.VerificationError(
                "Accepted signatures do not match threshold,"
                f" Found: {len(accepted_keys)}, Expected {threshold}"
            )

        return accepted_keys

    def deserialize_payload(
        self,
        class_type: Any,
        deserializer: Optional[BaseDeserializer] = None,
    ) -> Any:
        """Parse DSSE payload.

        Arguments:
            class_type: The class to be deserialized. If the default
                deserializer is used, it must implement ``JSONSerializable``.
            deserializer: ``BaseDeserializer`` implementation to use.
                Default is JSONDeserializer.

        Raises:
            DeserializationError: The payload cannot be deserialized.

        Returns:
            The deserialized object of payload.
        """

        if deserializer is None:
            deserializer = JSONDeserializer()

        payload = deserializer.deserialize(self.payload, class_type)
        return payload
