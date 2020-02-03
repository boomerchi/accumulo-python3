# Komorebi DB

> Work in progress.

Use *Komorebi* as a reference schema for using Accumulo as a simple document
store. Komorebi accounts for managing current views based upon dynamic
document attributes, and is well-suited for situations where replication and
eventual-consistency are important.

Komorebi is inspired by the [Command and Query Responsibility Segregation (CQRS)](https://docs.microsoft.com/en-us/azure/architecture/patterns/cqrs)
design pattern.

This package provides utilities for building Python 3 applications that
use Accumulo and the Komorebi schema.

## Overview

A __document__ is comprised of a number of *components*. A __component__
describes some attribute of the document. A component may describe a simple
attribute, such as a document name or title, or a more complex attribute, such
as a JSON blob or binary content.

A *component instance* is immutable. A component instance cannot be modified, 
but it can be deleted. Updating an attribute of a document is realized by
deleting an old component instance and adding a new one. 

A component instance may include a number of *views*. A __view__ is indexed
context that is associated with the component instance. A view will usually be
a lookup term that refers back to the document that owns the component
instance, but this is not a required convention.

## Schema

Komorebi describes two types of Accumulo records, *component records* and 
*view records*. A component record is indexed by its document identifier, 
whereas a view record is indexed by a lookup term.

### Component Records

A component record has the schema:

|Row ID|CF|CQ|Visibility|Value|
|---|---|---|---|---|
|`<doc_id>`|`<component_type>`|`<instance_qualifier>`|`<visibility>`|`<content>`|

The `component_type` property informs the type of document attribute that is 
described by the component instance. It is highly recommended that component 
instances with the same component type use the same content schema (and
otherwise behave similarly). It is also recommended that the component type 
include a version, in order to better accommodate schema evolution. For 
instance, the component type `user.info.v1` is preferred over the component 
type `user.info`. 

The `component_qualifier` property uniquely identifies the specific component
instance. Within a document, the component qualifier must be unique among all
component instances with the same component type, including those instances
that have been deleted. 

A document can have multiple components with the same component type. The 
component qualifier may be used to distinguish between these instances. As long
as the uniqueness requirements are respected, a component qualifier may utilize
any format and embed additional content. For instance, it may make sense to
use component qualifiers with a timestamp prefix if it is desired to keep 
component instances sorted by time.

### View Records

A view record has the schema:

|Row ID|CF|CQ|Visibility|Value|
|---|---|---|---|---|
|`<lookup_term>`|`<cf>`|`<view_qualifier>`|`<visibility>`|`<value>`|

The `<lookup_term>` property is intentionally flexible. It is recommended that
the lookup term include a prefix that describes the type of view (e.g. 
`NameToUserId`) so that entries in the same logical view are sorted together,
although this is not a requirement. A lookup term may also embed a key value 
pair.

The `<view_qualifier>` must be a unique identifier for the view record. A UUID
is suitable for most situations, although the view qualifier may also embed
other information (similarly to component records). The primary purpose of the
view qualifier is to ensure that a component instance does not generate views 
that overwrite the views of another component instance.

The `<visibility>` of a view record does not have to be equivalent to the 
visibility of the component instance that owns the view. 

The `<cf>` (i.e. *column family*) property is unused. A client may use the 
column family property to utilize locality groups among view records.

It is appropriate for a view record to mimic a component record (in which case
the lookup term is going to be a document identifier), as long as all 
uniqueness conventions are respected.


### Component Metadata Records

A *component metadata record* (or *metadata record*) is a special type of 
component record that associates a component instance with its associated
views. 

A component metadata record has the schema:

|Row ID|CF|CQ|Visibility|Value|
|---|---|---|---|---|
|`<doc_id>`|`_m\x00<component_type>`|`<instance_qualifier>`|`<visibility>`|`<content>`|

The content of a component metadata record is an encoded blob of content that
informs what Accumulo records need to be deleted when the component instance is
deleted. For a particular component instance, the associated component metadata
record will have the same `<doc_id>`, `<instance_qualifier>`, and `visibility`.
The only difference is that the `<component_type>` has the prefix `_m\x00`. 

It is important that there is a consistent, deterministic convention for 
getting the metadata record for a given component instance. The choice of 
encoding (and even the `_m\x00` prefix) is at the discretion of the client.

It is not a requirement to create metadata records for component instances that
do not have associated views. However, in this case, it is recommended that the
`<component_type>` property inform that the component instance does not have an
associated metadata record.

### Writing Clients

#### Adding document attributes

To add a document attribute (i.e. a specific component instance):
1. Create a mutation for the component instance record
2. Create mutations for the associated view records
3. If there are associated view records, create a mutation for a component
  metadata record that associates the view records with the component
  instance.
  
Observe that the existence of a document is predicated upon the existence of
component instances.

It generally makes sense to commit these mutations in bulk. It also makes sense
for these mutations to use the same timestamp.

#### Deleting document attributes

To delete a document attribute (i.e. a specific component instance):
1. Refer to the component metadata record to get any associated Accumulo 
  records.
2. Create a mutation to delete the component instance.
3. Create a mutation to delete the component metadata record (for that 
  instance).
4. Create mutations to delete the associated Accumulo records.

As with attribute creation, it generally makes sense to commit these mutations
in bulk, and using the same timestamp.

#### Updating a document attribute

Updating a document attribute is realized by deleting a component instance and
adding another. A component instance itself is immutable, and all of its
associated records (i.e. component and views) should be created or deleted in a
single atomic transaction.

#### Deleting documents

The recommended way to delete a document is to delete all of its components.

#### Caching component metadata

It is appropriate to cache component metadata records because components are
immutable. When deleting a component, it is advantageous to reference a cached
copy of the component metadata, rather than having to perform an Accumulo scan
to fetch the component metadata. 

#### Replication

To replicate the document store between Accumulo instances, it is satisfactory
to replicate the mutations. 
