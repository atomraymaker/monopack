import typing
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3

if typing.TYPE_CHECKING:
    from ..shared import schema


def build_payload():
    return {"ok": True}
