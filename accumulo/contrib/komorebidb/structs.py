from datetime import datetime, timezone
from typing import Iterable, Optional, Union
from uuid import uuid4

from accumulo import Mutation
from accumulo.core.structs import encode

from . import komorebi_pb2


T_ENCODABLE = Union[str, bytes]

METADATA_COMPONENT_PREFIX = '_meta\x00'
METADATA_COMPONENT_PREFIX_BYTES = METADATA_COMPONENT_PREFIX.encode()


def datetime_to_timestamp_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def deserialize_pb_encoded_key_set(pb_encoded_key_set: bytes):
    key_set = komorebi_pb2.KeySet()
    key_set.ParseFromString(pb_encoded_key_set)
    return key_set


class View:

    def __init__(self, lookup_term: str, qualifier: Optional[str] = None, visibility: str = '',
                 value: T_ENCODABLE = b'', family: T_ENCODABLE = b''):
        self.lookup_term = lookup_term
        if qualifier is None:
            qualifier = uuid4().hex
        self.qualifier = qualifier
        self.visibility = visibility
        self.family = family
        self.value = value

    def mutation(self, timestamp_ms: int):
        """Generates the mutation representing the view."""
        return Mutation(self.lookup_term, self.family, self.qualifier, self.visibility, timestamp_ms, self.value)

    @staticmethod
    def pb_key_from_mutation(mutation: Mutation):
        """Generates the protobuf Key object representing the view."""
        return komorebi_pb2.Key(
            row=mutation.row_bytes,
            cf=mutation.cf_bytes,
            cq=mutation.cq_bytes,
            visibility=mutation.visibility_bytes
        )


class Component:

    def __init__(self, doc_id: str, component_type: str, qualifier: Optional[str] = None,
                 visibility: str = '', content: T_ENCODABLE = b'', views: Optional[Iterable[View]] = None):
        self.doc_id = doc_id
        self.component_type = component_type
        if qualifier is None:
            qualifier = uuid4().hex
        self.qualifier = qualifier
        self.visibility = visibility
        self.content = content
        if views is None:
            views = []
        self.views = views


class RevisionBase:
    """A revision is used to generate mutations.

    All mutations created from the same revision will use the same timestamp.
    """

    def __init__(self, timestamp_ms: Optional[int] = None):
        if timestamp_ms is None:
            timestamp_ms = datetime_to_timestamp_ms(datetime.now(tz=timezone.utc))
        self.timestamp_ms = timestamp_ms

    def mutations(self):
        raise NotImplementedError


class Revision(RevisionBase):
    """Use a revision to create mutations for adding component instances."""

    def __init__(self, components: Iterable[Component], timestamp_ms: Optional[int] = None):
        super().__init__(timestamp_ms)
        self.components = components

    def mutations(self):
        mutations = []
        for component in self.components:
            component_mutation = Mutation(component.doc_id, component.component_type, component.qualifier,
                                          component.visibility, self.timestamp_ms, component.content)
            view_mutations = [
                Mutation(
                    view.lookup_term, view.family, view.qualifier, view.visibility, self.timestamp_ms, view.value
                ) for view in component.views
            ]
            view_keys = [
                komorebi_pb2.Key(
                    row=m.row_bytes, cf=m.cf_bytes, cq=m.cq_bytes, visibility=m.visibility_bytes
                ) for m in view_mutations
            ]
            # Add view keys for the component and component metadata records
            view_keys.extend([
                komorebi_pb2.Key(
                    row=component_mutation.row_bytes, cf=component_mutation.cf_bytes, cq=component_mutation.cq_bytes,
                    visibility=component_mutation.visibility_bytes
                ),
                komorebi_pb2.Key(
                    row=component_mutation.row_bytes, cf=METADATA_COMPONENT_PREFIX_BYTES + component_mutation.cf_bytes,
                    cq=component_mutation.cq_bytes, visibility=component_mutation.visibility_bytes
                )
            ])
            view_key_set = komorebi_pb2.KeySet(keys=view_keys)
            view_key_set_pb_encoded: bytes = view_key_set.SerializeToString()
            component_metadata_mutation = [
                Mutation(component.doc_id, METADATA_COMPONENT_PREFIX + component.component_type,
                         component.qualifier, component.visibility, self.timestamp_ms, view_key_set_pb_encoded)
            ]
            mutations.extend([
                *view_mutations,
                component_mutation,
                component_metadata_mutation
            ])
        return mutations


class RevisionDelete(RevisionBase):
    """Use a delete revision to create mutations for deleting component instances.

    The revision instance accepts a collection of component metadata content blobs.
    """

    def __init__(self, pb_encoded_key_sets: Iterable[bytes], timestamp_ms: Optional[int] = None):
        super().__init__(timestamp_ms)
        self.pb_encoded_key_sets = pb_encoded_key_sets

    def mutations(self):
        delete_mutations = []
        for pb_encoded_key_set in self.pb_encoded_key_sets:
            key_set = deserialize_pb_encoded_key_set(pb_encoded_key_set)
            delete_mutations.extend([
                Mutation(k.row, k.cf, k.cq, k.visibility, self.timestamp_ms, delete=True) for k in key_set
            ])
